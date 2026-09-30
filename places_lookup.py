"""Google Places lookup. Nominatim stays in lookup.py and runs when the flag is off.

Long-term storage is place IDs plus the visitor's own input. Listing fields
stay in the response object for the live page and the short memory cache.
"""

from __future__ import annotations

import logging
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import lookup
from places import (
    api_key,
    circle_bias,
    competitor_query,
    fetch_place,
    pick_competitors,
    search_competitors,
    search_text_ids,
    select_gaps,
    trade_term,
)

logger = logging.getLogger("mapgap.places_lookup")

_SHORT_HOSTS = {"maps.app.goo.gl", "goo.gl", "g.page"}


def places_link_view(result: dict, rid: str) -> dict[str, Any]:
    """Signed-link payload. Place IDs and the visitor's input. No listing fields."""
    stored = persistable_record(result)
    stored["v"] = 1
    stored["id"] = rid
    stored["listing"] = {}
    stored["raw"] = {"places_mode": True}
    return stored


def persistable_record(result: dict) -> dict[str, Any]:
    """The only Places-mode payload written to sqlite. Place IDs and the visitor's input."""
    user = result.get("user_input") or {}
    return {
        "places_mode": True,
        "user_input": {
            "name": user.get("name") or "",
            "city": user.get("city") or "",
            "listing_url": user.get("listing_url") or "",
        },
        "subject_place_id": result.get("subject_place_id") or "",
        "competitor_place_ids": list(result.get("competitor_place_ids") or []),
        "outcome": result.get("outcome") or "",
        "queried_at": result.get("queried_at") or "",
    }


def follow_redirect(url: str) -> str:
    """Resolve a short Maps link. The body is not parsed and the preview endpoint is not called."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": lookup.UA, "Accept": "text/html"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=lookup.TIMEOUT, context=lookup.CTX) as resp:
            return resp.geturl() or url
    except Exception:
        logger.warning("short maps link did not resolve")
        return url


def _is_short(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    return host in _SHORT_HOSTS or host.endswith(".goo.gl")


def _queried_at() -> str:
    return datetime.now().astimezone(ZoneInfo("America/New_York")).strftime("%b %-d, %Y, %-I:%M %p ET")


def _vertical(subject: dict) -> str:
    blob = " ".join(
        [
            subject.get("name") or "",
            subject.get("primary_type") or "",
            subject.get("category") or "",
            " ".join(subject.get("types") or []),
        ]
    ).lower().replace("_", " ")
    trade = any(w in blob for w in lookup.HVAC_PLUMBING) or any(
        w in blob for w in ("hvac", "plumb", "heating", "cooling", "furnace", "air condition", "drain")
    )
    if any(w in blob for w in lookup.NOT_OURS) and not trade:
        return "other"
    if trade:
        return "hvac_plumbing"
    return "unknown"


def _city_label(user_city: str, subject: dict) -> tuple[str, str]:
    """Visitor's city when they typed one, otherwise the city from Place Details."""
    typed = (user_city or "").strip()
    city = (subject.get("city") or "").strip()
    state = (subject.get("state") or "").strip()
    if typed:
        return typed, state
    city_parts = {part.lower() for part in city.split()}
    if city and state and state.lower() not in city_parts:
        return f"{city} {state}", state
    return city, state


def _empty(user: dict, outcome: str, thin_code: str, thin_reason: str, *, vertical_ok: bool = True) -> dict[str, Any]:
    name = user.get("name") or ""
    city = user.get("city") or ""
    url = user.get("listing_url") or ""
    if name and city:
        retry = f"{name}, {city}"
    else:
        retry = url or name or city
    return {
        "places_mode": True,
        "outcome": outcome,
        "queried_at": _queried_at(),
        "user_input": {"name": name, "city": city, "listing_url": url},
        "subject_place_id": "",
        "competitor_place_ids": [],
        "input": {
            "name": name or lookup.UNKNOWN,
            "city": city or lookup.UNKNOWN,
            "listing_url": url or lookup.UNKNOWN,
        },
        "retry_q": retry,
        "maps_url": url,
        "found": False,
        "listing": {
            "name": None,
            "address": None,
            "city": city or None,
            "state": None,
            "service_area": False,
            "phone": None,
            "website": None,
            "hours": None,
            "category": None,
            "rating": None,
            "review_count": None,
            "review_source": None,
            "photo_label": None,
        },
        "sources": [],
        "nearby": [],
        "attributions": [],
        "raw": {
            "places_mode": True,
            "thin": True,
            "thin_code": thin_code,
            "thin_reason": thin_reason,
            "vertical_ok": vertical_ok,
            "missing_fields": ["business name"] if outcome == "not_found" else [],
            "bullets": [],
            "city_source": "input" if city else "",
            "unlock": False,
        },
    }


def _listing_from(subject: dict, city: str, state: str) -> dict[str, Any]:
    service_area = bool(subject.get("pure_service_area"))
    address = None if service_area else (subject.get("address") or None)
    reviews = subject.get("review_count")
    return {
        "name": subject.get("name") or None,
        "address": address,
        "city": city or None,
        "state": state or None,
        "service_area": service_area,
        "phone": subject.get("phone") or None,
        "website": subject.get("website") or None,
        "hours": subject.get("hours") or None,
        "category": subject.get("category") or None,
        "rating": subject.get("rating"),
        "review_count": reviews,
        "review_source": "Google Places" if reviews is not None else None,
        "photo_label": subject.get("photo_label"),
        "photo_count": subject.get("photo_count"),
    }


def _pack(user: dict, subject: dict, competitors: list[dict], city_label: str, state: str) -> dict[str, Any]:
    gaps = select_gaps(subject, competitors)
    name = user.get("name") or ""
    city = user.get("city") or ""
    url = user.get("listing_url") or ""
    display_name = subject.get("name") or name
    if name and city:
        retry = f"{name}, {city}"
    elif display_name and city_label and not url:
        retry = f"{display_name}, {city_label}"
    else:
        retry = url or (f"{display_name}, {city_label}" if display_name and city_label else display_name or url)
    # retry_q may include a Places display name only in the live response. It is not stored.
    attributions: list[str] = []
    for place in [subject, *competitors]:
        for line in place.get("attributions") or []:
            if line not in attributions:
                attributions.append(line)
    nearby = []
    for place in competitors:
        nearby.append(
            {
                "name": place.get("name"),
                "phone": place.get("phone") or None,
                "website": place.get("website") or None,
                "category": place.get("category") or None,
                "rating": place.get("rating"),
                "review_count": place.get("review_count"),
                "photo_label": place.get("photo_label"),
                "place_id": place.get("place_id"),
                "note": "Google Places search result",
            }
        )
    thin = not competitors
    # 1 or 2 real gaps still get the paid offer. Zero gaps, and no competitors, do not.
    unlock = bool(competitors) and len(gaps) >= 1
    if not competitors:
        outcome = "no_competitors"
        thin_code = "no_competitors"
        thin_reason = "Not enough other shops came back from Places to compare."
        missing = ["other shops to compare"]
    elif len(gaps) < 3:
        outcome = "few_gaps"
        thin_code = "ok"
        thin_reason = ""
        missing = []
    else:
        outcome = "ok"
        thin_code = "ok"
        thin_reason = ""
        missing = []
    listing = _listing_from(subject, city_label, state)
    return {
        "places_mode": True,
        "outcome": outcome,
        "queried_at": _queried_at(),
        "user_input": {"name": name, "city": city, "listing_url": url},
        "subject_place_id": subject.get("place_id") or "",
        "competitor_place_ids": [c.get("place_id") for c in competitors if c.get("place_id")],
        "input": {
            "name": name or lookup.UNKNOWN,
            "city": city or city_label or lookup.UNKNOWN,
            "listing_url": url or lookup.UNKNOWN,
        },
        "retry_q": retry,
        "maps_url": subject.get("maps_uri") or url,
        "found": bool(listing.get("name")),
        "listing": listing,
        "sources": [
            {
                "id": "google_places",
                "label": "Google Places",
                "status": "ok" if competitors else "empty",
                "detail": "Live Places response for this page. Place IDs are what we keep.",
            }
        ],
        "nearby": nearby,
        "attributions": attributions,
        "raw": {
            "places_mode": True,
            "thin": thin,
            "thin_code": thin_code,
            "thin_reason": thin_reason,
            "vertical_ok": True,
            "missing_fields": missing,
            "bullets": gaps,
            "city_source": "input" if city else ("place" if city_label else ""),
            "unlock": unlock,
            "subject": {"service_area": listing["service_area"], "state": state, "city": city_label},
        },
    }


def _from_subject_id(
    subject_id: str,
    user: dict,
    *,
    bias: dict | None,
    preferred_ids: list[str] | None,
    http,
) -> dict[str, Any]:
    subject = fetch_place(subject_id, api_key=api_key(), http=http)
    vert = _vertical(subject)
    city_label, state = _city_label(user.get("city") or "", subject)
    # A Maps URL pin can sit far from the shop. Bias competitors to the Place location.
    if isinstance(subject.get("lat"), (int, float)) and isinstance(subject.get("lon"), (int, float)):
        bias = circle_bias(float(subject["lat"]), float(subject["lon"]))
    if vert == "other":
        result = _empty(
            user,
            "wrong_vertical",
            "wrong_vertical",
            "This page is HVAC and plumbing only. The Places listing does not show this business as either.",
            vertical_ok=False,
        )
        result["subject_place_id"] = subject.get("place_id") or subject_id
        result["found"] = bool(subject.get("name"))
        result["listing"] = _listing_from(subject, city_label, state)
        result["maps_url"] = subject.get("maps_uri") or user.get("listing_url") or ""
        result["attributions"] = list(subject.get("attributions") or [])
        result["raw"]["vertical_ok"] = False
        return result
    term = trade_term(
        subject.get("primary_type") or "",
        subject.get("types") or [],
        subject.get("name") or "",
        subject.get("category") or "",
    )
    query = competitor_query(term, city_label)
    found = search_competitors(query, api_key=api_key(), location_bias=bias, http=http)
    chosen = pick_competitors(found, subject.get("place_id") or subject_id, preferred_ids)
    return _pack(user, subject, chosen, city_label, state)


def run_places_lookup(name: str, city: str, listing_url: str, *, http=None) -> dict[str, Any]:
    name = (name or "").strip()
    city = (city or "").strip()
    listing_url = (listing_url or "").strip()
    if listing_url and not listing_url.lower().startswith(("http://", "https://")):
        listing_url = "https://" + listing_url
    user = {"name": name, "city": city, "listing_url": listing_url}
    url = listing_url
    if url and _is_short(url):
        url = follow_redirect(url)
        user["listing_url"] = listing_url
    parsed_name = lookup._name_from_maps_url(url) if url else ""
    lat, lon = lookup._coords_from_maps_url(url) if url else (None, None)
    subject_name = name or parsed_name
    text = " ".join(part for part in (subject_name, city) if part)
    if not text:
        return _empty(user, "not_found", "empty_input", "Paste a Google listing URL, or a shop name and city.")
    bias = circle_bias(lat, lon) if lat is not None and lon is not None else None
    key = api_key()
    ids = search_text_ids(text, api_key=key, location_bias=bias, http=http)
    if not ids:
        result = _empty(user, "not_found", "place_not_found", "We couldn't find that listing.")
        return result
    logger.info("places subject id=%s", ids[0])
    return _from_subject_id(ids[0], user, bias=bias, preferred_ids=None, http=http)


def refetch_places(stored: dict, *, http=None) -> dict[str, Any]:
    """Load a saved check from its place ID. Counts against the daily cap. No per-competitor Details."""
    user = stored.get("user_input") or {}
    subject_id = (stored.get("subject_place_id") or "").strip()
    if not subject_id:
        return _empty(
            {
                "name": user.get("name") or "",
                "city": user.get("city") or "",
                "listing_url": user.get("listing_url") or "",
            },
            stored.get("outcome") or "not_found",
            "place_not_found",
            "We couldn't find that listing.",
        )
    url = user.get("listing_url") or ""
    if url and _is_short(url):
        url = follow_redirect(url)
    lat, lon = lookup._coords_from_maps_url(url) if url else (None, None)
    bias = circle_bias(lat, lon) if lat is not None and lon is not None else None
    return _from_subject_id(
        subject_id,
        {
            "name": user.get("name") or "",
            "city": user.get("city") or "",
            "listing_url": url,
        },
        bias=bias,
        preferred_ids=list(stored.get("competitor_place_ids") or []),
        http=http,
    )


def lookup_places(raw: str) -> dict[str, Any]:
    parsed = lookup.parse_input(raw)
    if parsed.get("kind") == "url":
        adapter = run_places_lookup("", parsed.get("city") or "", parsed.get("url") or "")
    elif parsed.get("kind") == "name_city":
        adapter = run_places_lookup(parsed.get("name") or "", parsed.get("city") or "", "")
    else:
        adapter = run_places_lookup(parsed.get("query") or "", "", "")
    return adapter["raw"]
