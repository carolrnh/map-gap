"""Google Places API (New) client.

Pattern A, about $0.055 per check before free usage:
  * subject: Text Search IDs-only (free) + one Place Details Enterprise
  * competitors: one Text Search Enterprise (up to 20 places, top 3 kept)
No Place Details call per competitor. `reviews` is not requested.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from limits import reserve_places_call

logger = logging.getLogger("mapgap.places")

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/"
TIMEOUT = 12
BIAS_RADIUS_M = 25000.0

# Highest SKU on these masks is Enterprise (rating, userRatingCount, website, hours, phone).
SEARCH_IDS_MASK = "places.id"
SEARCH_ENTERPRISE_FIELDS = (
    "places.id",
    "places.displayName",
    "places.rating",
    "places.userRatingCount",
    "places.websiteUri",
    "places.regularOpeningHours",
    "places.photos",
    "places.primaryType",
    "places.primaryTypeDisplayName",
    "places.types",
    "places.nationalPhoneNumber",
    "places.pureServiceAreaBusiness",
    "places.formattedAddress",
    "places.googleMapsUri",
    "places.businessStatus",
    "places.attributions",
)
SEARCH_ENTERPRISE_MASK = ",".join(SEARCH_ENTERPRISE_FIELDS)
DETAILS_FIELD_MASK = ",".join(field.split(".", 1)[1] for field in SEARCH_ENTERPRISE_FIELDS)

# Gap scores are comparable 0–100 numbers. A zero score is not a gap.
RATING_POINTS_PER_STAR = 30
WEBSITE_WEIGHT = 88
HOURS_WEIGHT = 76
PHONE_WEIGHT = 64
CATEGORY_WEIGHT = 52
PHOTO_POINTS = 9
GAP_PRIORITY = {
    "review_count": 0,
    "rating": 1,
    "website": 2,
    "hours": 3,
    "photos": 4,
    "category": 5,
    "phone": 6,
}
GAP_TITLES = {
    "review_count": "Reviews",
    "rating": "Star rating",
    "website": "Website",
    "hours": "Hours",
    "photos": "Photos",
    "category": "Category",
    "phone": "Phone",
}

HttpFn = Callable[[str, str, dict, bytes | None], dict]


class PlacesError(Exception):
    user_message = "Google Places didn't return this check. Please try again in a little while."

    def __init__(self, message: str):
        super().__init__(message)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def google_places_enabled() -> bool:
    flag = (os.environ.get("USE_GOOGLE_PLACES") or "").strip().lower()
    key = (os.environ.get("GOOGLE_PLACES_API_KEY") or "").strip()
    return flag in {"1", "true", "yes", "on"} and bool(key)


def api_key() -> str:
    return (os.environ.get("GOOGLE_PLACES_API_KEY") or "").strip()


def _headers(key: str, field_mask: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": field_mask,
    }


def _raw_http(method: str, url: str, headers: dict, body: bytes | None) -> dict:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            raw = ""
    except Exception as exc:
        logger.warning("places request failed: %s", type(exc).__name__)
        raise PlacesError("Places request failed") from None
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {}
    if status != 200 or not isinstance(payload, dict):
        logger.warning("places http %s", status)
        raise PlacesError(f"Places HTTP {status}")
    return payload


def _call(method: str, url: str, headers: dict, body: bytes | None, http: HttpFn | None) -> dict:
    reserve_places_call()
    send = http or _raw_http
    return send(method, url, headers, body)


def place_id_of(raw: dict) -> str:
    if raw.get("id"):
        return str(raw["id"])
    name = str(raw.get("name") or "")
    if name.startswith("places/"):
        return name.split("/", 1)[1]
    return ""


def photo_label_for(count: int) -> str:
    if count >= 10:
        return "10+"
    return str(max(0, count))


def _text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("text") or "").strip()
    return str(value or "").strip()


def attribution_lines(raw: dict) -> list[str]:
    lines: list[str] = []
    for item in raw.get("attributions") or []:
        if isinstance(item, str) and item.strip():
            lines.append(item.strip())
        elif isinstance(item, dict):
            provider = str(item.get("provider") or "").strip()
            uri = str(item.get("providerUri") or "").strip()
            if provider and uri:
                lines.append(f"{provider} ({uri})")
            elif provider or uri:
                lines.append(provider or uri)
    for photo in raw.get("photos") or []:
        if not isinstance(photo, dict):
            continue
        for author in photo.get("authorAttributions") or []:
            if not isinstance(author, dict):
                continue
            name = str(author.get("displayName") or "").strip()
            uri = str(author.get("uri") or "").strip()
            if name and uri:
                lines.append(f"Photo: {name} ({uri})")
            elif name:
                lines.append(f"Photo: {name}")
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


def normalize_place(raw: dict) -> dict[str, Any]:
    photos = raw.get("photos")
    photo_count = len(photos) if isinstance(photos, list) else 0
    hours = raw.get("regularOpeningHours") if isinstance(raw.get("regularOpeningHours"), dict) else {}
    descriptions = [str(x) for x in (hours.get("weekdayDescriptions") or []) if x]
    periods = hours.get("periods") or []
    rating = raw.get("rating")
    reviews = raw.get("userRatingCount")
    return {
        "place_id": place_id_of(raw),
        "name": _text(raw.get("displayName")),
        "rating": float(rating) if isinstance(rating, (int, float)) else None,
        "review_count": int(reviews) if isinstance(reviews, (int, float)) else None,
        "website": str(raw.get("websiteUri") or "").strip(),
        "hours": "; ".join(descriptions),
        "hours_listed": bool(descriptions or periods),
        "photo_count": photo_count,
        "photo_label": photo_label_for(photo_count),
        "category": _text(raw.get("primaryTypeDisplayName")) or str(raw.get("primaryType") or "").replace("_", " "),
        "primary_type": str(raw.get("primaryType") or ""),
        "types": [str(t) for t in (raw.get("types") or []) if t],
        "phone": str(raw.get("nationalPhoneNumber") or "").strip(),
        "address": str(raw.get("formattedAddress") or "").strip(),
        "pure_service_area": bool(raw.get("pureServiceAreaBusiness")),
        "maps_uri": str(raw.get("googleMapsUri") or "").strip(),
        "business_status": str(raw.get("businessStatus") or ""),
        "attributions": attribution_lines(raw),
    }


def circle_bias(lat: float, lon: float) -> dict[str, Any]:
    return {
        "circle": {
            "center": {"latitude": float(lat), "longitude": float(lon)},
            "radius": BIAS_RADIUS_M,
        }
    }


def search_text_ids(
    text_query: str,
    *,
    api_key: str,
    location_bias: dict | None = None,
    http: HttpFn | None = None,
) -> list[str]:
    body: dict[str, Any] = {
        "textQuery": text_query,
        "pageSize": 1,
        "includePureServiceAreaBusinesses": True,
    }
    if location_bias:
        body["locationBias"] = location_bias
    payload = _call(
        "POST",
        SEARCH_URL,
        _headers(api_key, SEARCH_IDS_MASK),
        json.dumps(body).encode("utf-8"),
        http,
    )
    ids: list[str] = []
    for place in payload.get("places") or []:
        if isinstance(place, dict):
            pid = place_id_of(place)
            if pid:
                ids.append(pid)
    return ids


def search_competitors(
    text_query: str,
    *,
    api_key: str,
    location_bias: dict | None = None,
    http: HttpFn | None = None,
) -> list[dict[str, Any]]:
    body: dict[str, Any] = {
        "textQuery": text_query,
        "pageSize": 20,
        "includePureServiceAreaBusinesses": True,
    }
    if location_bias:
        body["locationBias"] = location_bias
    payload = _call(
        "POST",
        SEARCH_URL,
        _headers(api_key, SEARCH_ENTERPRISE_MASK),
        json.dumps(body).encode("utf-8"),
        http,
    )
    out: list[dict[str, Any]] = []
    for place in payload.get("places") or []:
        if isinstance(place, dict):
            out.append(normalize_place(place))
    return out


def fetch_place(place_id: str, *, api_key: str, http: HttpFn | None = None) -> dict[str, Any]:
    url = DETAILS_URL + urllib.parse.quote(place_id, safe="")
    payload = _call("GET", url, _headers(api_key, DETAILS_FIELD_MASK), None, http)
    place = normalize_place(payload)
    if not place["place_id"]:
        place["place_id"] = place_id
    return place


def trade_term(primary_type: str, types: list[str] | None, name: str) -> str:
    """One search term from the subject's primary type, so a check is a single Text Search."""
    primary = (primary_type or "").lower().replace("_", " ")
    if any(w in primary for w in ("plumb", "drain", "sewer")):
        return "plumber"
    if any(w in primary for w in ("hvac", "heating", "air condition", "furnace", "cooling")):
        return "hvac"
    blob = " ".join(types or []).lower().replace("_", " ") + " " + (name or "").lower()
    if any(w in blob for w in ("plumb", "drain", "sewer")):
        return "plumber"
    return "hvac"


def competitor_query(term: str, city: str) -> str:
    city = (city or "").strip()
    if city:
        return f"{term} in {city}"
    return term


def pick_competitors(
    results: list[dict[str, Any]],
    subject_id: str,
    preferred_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Top 3 from one Text Search. Prefer stored place IDs when they are still in the results."""
    ranked = []
    for place in results:
        pid = place.get("place_id") or ""
        if not pid or pid == subject_id:
            continue
        if place.get("business_status") == "CLOSED_PERMANENTLY":
            continue
        ranked.append(place)
    preferred = set(preferred_ids or [])
    if preferred:
        matched = [place for place in ranked if place.get("place_id") in preferred]
        if matched:
            return matched[:3]
    return ranked[:3]


def _shop_name(place: dict) -> str:
    return place.get("name") or "A shop this search returned"


def _presence_score(subject_has: bool, competitors: list[dict], predicate, weight: float) -> float:
    if not competitors or subject_has:
        return 0.0
    have = sum(1 for place in competitors if predicate(place))
    if have == 0:
        return 0.0
    return weight * (have / len(competitors))


def select_gaps(subject: dict, competitors: list[dict]) -> list[dict[str, Any]]:
    """Up to 3 largest gaps Places can actually support. Posts and 90-day velocity are not candidates."""
    if not competitors:
        return []
    scored: list[tuple[float, str, str]] = []

    yours = subject.get("review_count")
    review_rows = [c for c in competitors if isinstance(c.get("review_count"), int)]
    if isinstance(yours, int) and review_rows:
        leader = max(review_rows, key=lambda c: c["review_count"])
        leader_n = int(leader["review_count"])
        if leader_n > yours:
            score = min(100.0, (leader_n - yours) / leader_n * 100.0)
            body = (
                f"{_shop_name(leader)} shows {leader_n} Google reviews. "
                f"This listing shows {yours}. "
                "This gap uses the total review count Google Places returns."
            )
            scored.append((score, "review_count", body))

    your_rating = subject.get("rating")
    rating_rows = [c for c in competitors if isinstance(c.get("rating"), (int, float))]
    if isinstance(your_rating, (int, float)) and rating_rows:
        leader = max(rating_rows, key=lambda c: float(c["rating"]))
        leader_r = float(leader["rating"])
        if leader_r > float(your_rating):
            score = min(100.0, (leader_r - float(your_rating)) * RATING_POINTS_PER_STAR)
            body = (
                f"{_shop_name(leader)} is at {leader_r:.1f} stars. "
                f"This listing is at {float(your_rating):.1f} stars. "
                "This is the star rating Google Places returns."
            )
            scored.append((score, "rating", body))

    website_score = _presence_score(bool(subject.get("website")), competitors, lambda c: bool(c.get("website")), WEBSITE_WEIGHT)
    if website_score > 0:
        n = sum(1 for c in competitors if c.get("website"))
        body = (
            f"{n} of {len(competitors)} shops this search returned list a website. "
            "This listing does not."
        )
        scored.append((website_score, "website", body))

    hours_score = _presence_score(
        bool(subject.get("hours_listed")), competitors, lambda c: bool(c.get("hours_listed")), HOURS_WEIGHT
    )
    if hours_score > 0:
        n = sum(1 for c in competitors if c.get("hours_listed"))
        body = (
            f"{n} of {len(competitors)} shops this search returned list opening hours. "
            "This listing does not."
        )
        scored.append((hours_score, "hours", body))

    your_photos = min(int(subject.get("photo_count") or 0), 10)
    photo_rows = [(c, min(int(c.get("photo_count") or 0), 10)) for c in competitors]
    if photo_rows:
        leader, leader_n = max(photo_rows, key=lambda item: item[1])
        if leader_n > your_photos:
            score = min(100.0, (leader_n - your_photos) * PHOTO_POINTS)
            body = (
                "Google Places returns at most 10 photos, so counts are 0–9 or 10+. "
                f"This listing has {photo_label_for(your_photos)}. "
                f"{_shop_name(leader)} has {photo_label_for(leader_n)}."
            )
            scored.append((score, "photos", body))

    theirs = [c for c in competitors if c.get("primary_type")]
    if theirs:
        counts: dict[str, list[dict]] = {}
        for place in theirs:
            counts.setdefault(place["primary_type"], []).append(place)
        common_type, group = max(counts.items(), key=lambda item: len(item[1]))
        yours_type = subject.get("primary_type") or ""
        if yours_type != common_type:
            score = CATEGORY_WEIGHT * (len(group) / len(competitors))
            common_label = group[0].get("category") or common_type.replace("_", " ")
            your_label = subject.get("category") or (yours_type.replace("_", " ") if yours_type else "")
            if your_label:
                body = (
                    f"This listing's primary type is {your_label}. "
                    f"The shops this search returned are mostly {common_label}. "
                    "This comparison is the primary type from Places."
                )
            else:
                body = (
                    "This listing has no primary type in the Places response. "
                    f"The shops this search returned are mostly {common_label}. "
                    "This comparison is the primary type from Places."
                )
            scored.append((score, "category", body))

    phone_score = _presence_score(bool(subject.get("phone")), competitors, lambda c: bool(c.get("phone")), PHONE_WEIGHT)
    if phone_score > 0:
        n = sum(1 for c in competitors if c.get("phone"))
        body = (
            f"{n} of {len(competitors)} shops this search returned list a phone number. "
            "This listing does not."
        )
        scored.append((phone_score, "phone", body))

    scored.sort(key=lambda item: (-item[0], GAP_PRIORITY[item[1]]))
    gaps = []
    for score, kind, body in scored:
        if score <= 0:
            continue
        gaps.append({"kind": kind, "title": GAP_TITLES[kind], "body": body, "score": score})
        if len(gaps) == 3:
            break
    return gaps
