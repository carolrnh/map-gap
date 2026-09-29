"""Public-data teaser lookup for Map Gap.

Sources: OpenStreetMap Nominatim (identity + nearby HVAC/plumbing), and
a best-effort fetch of a public Google listing URL the buyer pasted.

Never invent review counts, post counts, ratings, or rankings.
Unobserved fields stay None / UNKNOWN. Thin data hides the $195 unlock.

Service-area listings often have no street address. A Maps place URL still
carries the business name and a pin. The pin is not a storefront: reverse
geocoding it can land on a neighboring street, so that street is never saved
as the business address. When the URL or address parse does not yield a
place, lookup falls back to business name + city (from the form, from the
business website's public schema, or from the pin's city only).
"""

from __future__ import annotations

import json
import logging
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("mapgap.lookup")

UA = "MapGap/1.0 (self-serve HVAC plumbing teaser; public data only)"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"
TIMEOUT = 12
CTX = ssl.create_default_context()

HVAC_PLUMBING = (
    "hvac",
    "heating",
    "cooling",
    "air conditioning",
    "air-conditioning",
    "airconditioning",
    "furnace",
    "heat pump",
    "heatpump",
    "a/c",
    "ac repair",
    "boiler",
    "ventilation",
    "refrigeration",
    "plumber",
    "plumbing",
    "drain",
    "sewer",
    "pipe",
    "water heater",
    "hydronic",
)
OSM_OK = {
    "hvac",
    "plumber",
    "heating",
    "air_conditioning",
    "air-conditioning",
    "ventilation",
    "refrigeration",
}
NOT_OURS = (
    "dentist",
    "salon",
    "pizza",
    "restaurant",
    "attorney",
    "lawyer",
    "chiropractic",
    "spa",
    "nail",
    "barber",
    "coffee",
    "bakery",
    "hotel",
    "florist",
    "tattoo",
    "gym",
    "yoga",
)


def _get(url: str, accept: str = "application/json") -> tuple[int, str, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, body, resp.geturl()
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, body, url
    except Exception as e:
        return 0, str(e), url


def looks_like_url(raw: str) -> bool:
    s = raw.strip().lower()
    return s.startswith("http://") or s.startswith("https://") or s.startswith("www.")


def parse_input(raw: str) -> dict[str, str]:
    raw = (raw or "").strip()
    out = {"raw": raw, "kind": "", "url": "", "name": "", "city": "", "query": raw}
    if not raw:
        return out
    if looks_like_url(raw):
        url = raw if raw.lower().startswith("http") else "https://" + raw
        out["kind"] = "url"
        out["url"] = url
        out["name"] = _name_from_maps_url(url)
        out["city"] = _city_from_maps_url(url)
        lat, lon = _coords_from_maps_url(url)
        if lat is not None and lon is not None:
            out["lat"] = str(lat)
            out["lon"] = str(lon)
        return out
    if "," in raw:
        name, city = raw.rsplit(",", 1)
        out["kind"] = "name_city"
        out["name"] = name.strip()
        out["city"] = city.strip()
        out["query"] = f"{out['name']} {out['city']}"
        return out
    # "Summit Heating Columbus" — last 1–2 tokens as city guess only for search,
    # not as a confirmed city until Nominatim returns one.
    out["kind"] = "free"
    out["query"] = raw
    return out


def _name_from_maps_url(url: str) -> str:
    try:
        u = urllib.parse.urlparse(url)
        m = re.search(r"/place/([^/@]+)", u.path)
        if m:
            return urllib.parse.unquote_plus(m.group(1)).strip()
        qs = urllib.parse.parse_qs(u.query)
        for key in ("q", "query", "daddr"):
            if qs.get(key):
                return qs[key][0].strip()
    except Exception:
        return ""
    return ""


def _city_from_maps_url(url: str) -> str:
    # Place URLs rarely include a city. Name + pin are parsed instead.
    return ""


def _coords_from_maps_url(url: str) -> tuple[float | None, float | None]:
    """Place pin from !3d/!4d, else the map-center @lat,lon."""
    try:
        u = urllib.parse.urlparse(url)
        text = urllib.parse.unquote(u.path + "?" + u.query)
    except Exception:
        return None, None
    m = re.search(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)", text)
    if not m:
        m = re.search(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", text)
    if not m:
        return None, None
    try:
        lat, lon = float(m.group(1)), float(m.group(2))
    except ValueError:
        return None, None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None
    return lat, lon


def _preview_place_path(html: str) -> str:
    m = re.search(r'href="(/maps/preview/place\?[^"]+)"', html or "")
    if not m:
        return ""
    return m.group(1).replace("&amp;", "&")


def _walk(node: Any):
    if isinstance(node, list):
        yield node
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        for item in node.values():
            yield from _walk(item)


_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _hours_from_preview(data: Any) -> str:
    by_day: dict[str, str] = {}
    for node in _walk(data):
        if not node or not isinstance(node[0], str) or node[0] not in _WEEKDAYS or len(node) < 4:
            continue
        slot = node[3]
        label = ""
        if isinstance(slot, list) and slot:
            first = slot[0]
            if isinstance(first, list) and first and isinstance(first[0], str):
                label = first[0]
            elif isinstance(first, str):
                label = first
        label = label.replace("\u202f", " ").strip()
        if label and node[0] not in by_day:
            by_day[node[0]] = label
    if len(by_day) < 5:
        return ""
    ordered = [(day, by_day[day]) for day in _WEEKDAYS if day in by_day]
    chunks: list[str] = []
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        start, label = ordered[i]
        end = ordered[j][0]
        span = start[:3] if start == end else f"{start[:3]}–{end[:3]}"
        chunks.append(f"{span} {label}")
        i = j + 1
    return "; ".join(chunks)


def _parse_preview_place(body: str) -> dict[str, Any] | None:
    """Pull only fields that are actually present in a public Maps preview."""
    raw = (body or "").strip()
    if raw.startswith(")]}'"):
        raw = raw.split("\n", 1)[-1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    fields: dict[str, Any] = {
        "name": None,
        "category": None,
        "categories": [],
        "phone": None,
        "website": None,
        "hours": None,
        "address": None,
        "lat": None,
        "lon": None,
        "service_area": None,
        "posts_seen": None,
    }
    categories: list[str] = []
    for node in _walk(data):
        if (
            len(node) == 2
            and isinstance(node[0], str)
            and isinstance(node[1], str)
            and "gstatic.com/images/icons" in node[0]
        ):
            icon = node[0].rsplit("/", 1)[-1]
            label = node[1].strip()
            if not label:
                continue
            if icon.startswith("storefront_") and not fields["name"]:
                fields["name"] = label
            elif icon.startswith("category_"):
                if label not in categories:
                    categories.append(label)
            elif icon.startswith("call_") and not fields["phone"]:
                fields["phone"] = label
            elif icon.startswith("public_") and label.startswith("http") and not fields["website"]:
                fields["website"] = label.split("?", 1)[0]
            elif icon.startswith("location_on_") and not fields["address"]:
                fields["address"] = label
            elif icon.startswith("schedule_") and not fields["hours"]:
                fields["hours"] = label.replace("\u202f", " ")
        if (
            len(node) == 4
            and node[0] is None
            and node[1] is None
            and isinstance(node[2], (int, float))
            and isinstance(node[3], (int, float))
            and fields["lat"] is None
            and 24 <= float(node[2]) <= 50
            and -125 <= float(node[3]) <= -66
        ):
            fields["lat"] = float(node[2])
            fields["lon"] = float(node[3])
    if categories:
        fields["categories"] = categories
        fields["category"] = categories[0]
    weekly = _hours_from_preview(data)
    if weekly:
        fields["hours"] = weekly
    post_ids = set(re.findall(r"localPosts(?:%2F|/)(\d+)", raw))
    if post_ids:
        fields["posts_seen"] = len(post_ids)
    if not any(fields.get(k) for k in ("name", "category", "phone", "website", "address")):
        return None
    fields["service_area"] = bool(fields["name"]) and not fields["address"]
    return fields


def _city_state_from_address(address: str) -> tuple[str, str]:
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    if len(parts) < 2:
        return "", ""
    state = ""
    m = re.match(r"([A-Z]{2})\b", parts[-1])
    if m:
        state = m.group(1)
    city = parts[-2]
    if any(ch.isdigit() for ch in city):
        return "", state
    return city, state


def _website_identity(url: str) -> dict[str, Any]:
    """City and name from public schema.org. A missing street is kept missing."""
    out: dict[str, Any] = {
        "ok": False,
        "name": "",
        "city": "",
        "state": "",
        "street": "",
        "phone": "",
        "review_count": None,
    }
    if not url:
        return out
    status, body, _final = _get(url, accept="text/html,application/xhtml+xml")
    if status != 200 or not body:
        return out
    out["ok"] = True
    re_script = re.compile(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.I | re.S,
    )
    best: dict[str, Any] | None = None
    best_score = -1
    for m in re_script.finditer(body):
        try:
            data = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        nodes: list[Any] = []

        def walk(n: Any) -> None:
            if isinstance(n, list):
                for x in n:
                    walk(x)
            elif isinstance(n, dict):
                nodes.append(n)
                if "@graph" in n:
                    walk(n["@graph"])

        walk(data)
        for n in nodes:
            addr = n.get("address") if isinstance(n.get("address"), dict) else {}
            locality = str(addr.get("addressLocality") or "").strip()
            if not locality and not n.get("name"):
                continue
            score = (3 if locality else 0) + (2 if addr.get("streetAddress") else 0) + (1 if n.get("name") else 0)
            if score > best_score:
                best_score = score
                best = n
    if not best:
        return out
    addr = best.get("address") if isinstance(best.get("address"), dict) else {}
    out["name"] = str(best.get("name") or "").strip()
    out["city"] = str(addr.get("addressLocality") or "").strip()
    out["state"] = str(addr.get("addressRegion") or "").strip()
    out["street"] = str(addr.get("streetAddress") or "").strip()
    out["phone"] = str(best.get("telephone") or "").strip()
    ar = best.get("aggregateRating") if isinstance(best.get("aggregateRating"), dict) else None
    if ar and ar.get("reviewCount") not in (None, ""):
        try:
            out["review_count"] = int(str(ar["reviewCount"]).replace(",", ""))
        except ValueError:
            pass
    return out


def _reverse_locality(lat: float, lon: float) -> dict[str, str]:
    """City only. The street under a service-area pin is not the business address."""
    url = NOMINATIM_REVERSE + "?" + urllib.parse.urlencode(
        {"lat": str(lat), "lon": str(lon), "format": "jsonv2", "addressdetails": "1"}
    )
    status, body, _ = _get(url)
    time.sleep(1.05)
    out = {"city": "", "state": "", "country_code": "", "postcode": ""}
    if status != 200 or not body:
        return out
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return out
    if not isinstance(data, dict):
        return out
    addr = data.get("address") or {}
    out["country_code"] = str(addr.get("country_code") or "").lower()
    out["state"] = str(addr.get("state") or "")
    out["postcode"] = str(addr.get("postcode") or "")
    out["city"] = _locality_name(addr)
    return out


def _locality_name(addr: dict[str, Any]) -> str:
    for key in ("city", "town", "village", "hamlet", "municipality"):
        if addr.get(key):
            return str(addr[key])
    return ""


def _city_from_postcode(postcode: str) -> dict[str, str]:
    """A service-area pin often lands outside a city polygon but inside a ZIP."""
    hits = _nominatim({"postalcode": postcode, "limit": "1"})
    time.sleep(1.05)
    if not hits:
        return {"city": "", "state": ""}
    hit = hits[0]
    addr = hit.get("address") or {}
    return {"city": _locality_name(addr), "state": str(addr.get("state") or "")}


def _hit_has_street(hit: dict[str, Any]) -> bool:
    addr = hit.get("address") or {}
    return bool(addr.get("house_number") or addr.get("road") or addr.get("street"))


def _subject_from_observed(
    name: str,
    city: str,
    state: str,
    google: dict[str, Any] | None,
    site: dict[str, Any] | None,
) -> dict[str, Any]:
    g = google or {}
    s = site or {}
    category = g.get("category") or ""
    fake = {
        "name": name,
        "type": "",
        "display_name": name,
        "category": category,
        "extratags": {},
        "address": {},
    }
    vert = _is_hvac_plumbing(fake, f"{name} {category} {city}")
    address = g.get("address") or ""
    if g.get("service_area"):
        address = ""
    return {
        "name": name,
        "display_name": name,
        "address": address,
        "city": city,
        "state": state or "",
        "postcode": "",
        "phone": g.get("phone") or s.get("phone") or "",
        "website": g.get("website") or "",
        "hours": g.get("hours") or "",
        "lat": g.get("lat"),
        "lon": g.get("lon"),
        "osm_type": None,
        "osm_category": None,
        "osm_id": None,
        "osm_kind": None,
        "tags": [],
        "country_code": "us",
        "source": "public_listing",
        "vertical": vert,
        "google_category": category or None,
        "service_area": bool(g.get("service_area")),
        "review_count_total": g.get("review_count_total"),
        "review_count_source": "public Maps preview" if g.get("review_count_total") is not None else "",
        "rating": g.get("rating"),
    }


def _missing_fields(result: dict[str, Any]) -> list[str]:
    subject = result.get("subject") or {}
    google = result.get("google") or {}
    missing: list[str] = []
    category = subject.get("google_category") or subject.get("osm_type") or subject.get("tags")
    if not category:
        missing.append("primary category")
    if google.get("review_count_total") is None and subject.get("review_count_total") is None:
        missing.append("review count")
    if not (subject.get("city") or (result.get("input") or {}).get("city")):
        missing.append("city")
    if not result.get("competitors"):
        missing.append("other shops to compare")
    if subject.get("service_area"):
        return missing
    if subject and not subject.get("address") and not subject.get("service_area"):
        missing.append("street address")
    return missing


def _finish(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("missing_fields"):
        result["missing_fields"] = _missing_fields(result) if result.get("thin") else []
    subject = result.get("subject") or {}
    parsed = result.get("input") or {}
    logger.warning(
        "lookup thin_code=%s name=%r city=%r city_source=%s service_area=%s trace=%s",
        result.get("thin_code") or ("ok" if result.get("ok") else "unk"),
        subject.get("name") or parsed.get("name") or "",
        subject.get("city") or parsed.get("city") or "",
        result.get("city_source") or "",
        subject.get("service_area"),
        ",".join(result.get("trace") or []),
    )
    return result


def _nominatim(params: dict[str, str]) -> list[dict[str, Any]]:
    q = dict(params)
    q.setdefault("format", "jsonv2")
    q.setdefault("addressdetails", "1")
    q.setdefault("extratags", "1")
    q.setdefault("namedetails", "0")
    q.setdefault("countrycodes", "us")
    url = NOMINATIM + "?" + urllib.parse.urlencode(q)
    status, body, _ = _get(url)
    if status != 200:
        return []
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _blob(hit: dict[str, Any]) -> str:
    extra = hit.get("extratags") or {}
    addr = hit.get("address") or {}
    parts = [
        hit.get("name") or "",
        hit.get("display_name") or "",
        hit.get("type") or "",
        hit.get("category") or "",
        hit.get("addresstype") or "",
        extra.get("craft") or "",
        extra.get("shop") or "",
        extra.get("trade") or "",
        extra.get("office") or "",
        extra.get("description") or "",
        addr.get("craft") or "",
        addr.get("shop") or "",
    ]
    return " ".join(str(p) for p in parts).lower()


def _is_hvac_plumbing(hit: dict[str, Any], extra_text: str = "") -> str:
    blob = _blob(hit) + " " + (extra_text or "").lower()
    osm_type = (hit.get("type") or "").lower()
    if osm_type in OSM_OK:
        return "hvac_plumbing"
    if any(w in blob for w in HVAC_PLUMBING):
        return "hvac_plumbing"
    if any(w in blob for w in NOT_OURS):
        return "other"
    return "unknown"


def _city_of(hit: dict[str, Any]) -> str:
    addr = hit.get("address") or {}
    for k in ("city", "town", "village", "municipality", "county"):
        if addr.get(k):
            return str(addr[k])
    return ""


def _state_of(hit: dict[str, Any]) -> str:
    addr = hit.get("address") or {}
    return str(addr.get("state") or "")


def _pretty_tag(val: str) -> str:
    v = (val or "").strip()
    key = v.lower().replace(" ", "_")
    pretty = {
        "hvac": "HVAC",
        "plumber": "plumber",
        "heating": "heating",
        "air_conditioning": "air conditioning",
        "air-conditioning": "air conditioning",
        "ventilation": "ventilation",
        "refrigeration": "refrigeration",
        "electrician": "electrician",
    }
    return pretty.get(key, v)


def _tags(hit: dict[str, Any]) -> list[str]:
    extra = hit.get("extratags") or {}
    name = (hit.get("name") or "").strip().lower()
    tags: list[str] = []

    def add(val: str, prefix: str = "") -> None:
        val = str(val or "").strip()
        if not val:
            return
        if val.lower() == name:
            return
        # Nominatim often stuffs the business name into address.craft
        if " " in val and val.lower() not in OSM_OK and val.lower().replace(" ", "_") not in OSM_OK:
            return
        label = f"{prefix}={val}" if prefix else val
        if label not in tags:
            tags.append(label)

    t = hit.get("type")
    c = hit.get("category")
    if t:
        add(str(t), str(c or "type"))
    for k in ("craft", "shop", "trade", "office", "amenity"):
        v = extra.get(k)
        if v:
            add(str(v), k)
    return tags


def _address_line(hit: dict[str, Any]) -> str:
    addr = hit.get("address") or {}
    street = " ".join(p for p in [addr.get("house_number"), addr.get("road") or addr.get("street")] if p)
    city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("hamlet")
    state = addr.get("state")
    postcode = addr.get("postcode")
    return ", ".join(p for p in [street, city, state, postcode] if p)


def _place(hit: dict[str, Any], source: str) -> dict[str, Any]:
    extra = hit.get("extratags") or {}
    return {
        "name": hit.get("name") or "",
        "display_name": hit.get("display_name") or "",
        "address": _address_line(hit),
        "city": _city_of(hit),
        "state": _state_of(hit),
        "postcode": (hit.get("address") or {}).get("postcode") or "",
        "phone": extra.get("phone") or extra.get("contact:phone") or extra.get("telephone") or "",
        "website": extra.get("website") or extra.get("contact:website") or extra.get("url") or "",
        "hours": extra.get("opening_hours") or "",
        "lat": hit.get("lat"),
        "lon": hit.get("lon"),
        "osm_type": hit.get("type"),
        "osm_category": hit.get("category"),
        "osm_id": hit.get("osm_id"),
        "osm_kind": hit.get("osm_type"),
        "tags": _tags(hit),
        "country_code": ((hit.get("address") or {}).get("country_code") or "").lower(),
        "source": source,
        "vertical": _is_hvac_plumbing(hit),
    }


def _google_enrich(url: str) -> dict[str, Any]:
    """Best-effort public page parse. Missing fields stay None. Never guess counts.

    Maps HTML is a script shell with no JSON-LD. The page links a public preview
    payload that does include the name, category, phone, website, and hours.
    "Enable JavaScript" in that shell is the normal noscript line, not a block,
    so it does not by itself discard the preview.
    """
    out: dict[str, Any] = {
        "fetched": False,
        "preview": False,
        "final_url": url,
        "name": None,
        "category": None,
        "categories": [],
        "phone": None,
        "website": None,
        "hours": None,
        "address": None,
        "service_area": None,
        "lat": None,
        "lon": None,
        "posts_seen": None,
        "review_count_total": None,
        "rating": None,
        "review_dates_90d": None,
        "posts_90d": None,
        "note": None,
    }
    if not url:
        return out
    status, body, final = _get(url, accept="text/html,application/xhtml+xml")
    out["final_url"] = final
    if status == 0 or status >= 400 or not body:
        out["note"] = f"Public Google page not readable (HTTP {status})."
        return out
    low = body[:24000].lower()
    blocked = any(
        s in low
        for s in (
            "before you continue",
            "unusual traffic",
            "consent.google",
            "detected unusual traffic",
        )
    )
    preview_path = _preview_place_path(body)
    if preview_path and not blocked:
        pstatus, pbody, _pfinal = _get(
            "https://www.google.com" + preview_path,
            accept="application/json,text/plain,*/*",
        )
        parsed = _parse_preview_place(pbody) if pstatus == 200 else None
        if parsed:
            out.update(parsed)
            out["fetched"] = True
            out["preview"] = True
            out["final_url"] = final
            bits = [k for k in ("name", "category", "phone", "website", "hours", "address") if parsed.get(k)]
            if parsed.get("service_area"):
                bits.append("no street address (service-area listing)")
            if parsed.get("review_count_total") is None:
                out["note"] = (
                    "Public Maps preview had "
                    + (", ".join(bits) if bits else "no listing fields")
                    + ". Review count was not in that response, so it is not shown."
                )
            else:
                out["note"] = "Public Maps preview. Only fields present in that response are shown."
            return out
    if blocked or "enable javascript" in low and not preview_path:
        out["note"] = "Public Google page returned a consent or block screen. Fields not observed."
        return out
    out["fetched"] = True
    ld = _pick_ld(body)
    if ld:
        if ld.get("name"):
            out["name"] = str(ld["name"])
        ar = ld.get("aggregateRating")
        if isinstance(ar, dict):
            if ar.get("reviewCount") not in (None, ""):
                try:
                    out["review_count_total"] = int(str(ar["reviewCount"]).replace(",", ""))
                except ValueError:
                    pass
            if ar.get("ratingValue") not in (None, ""):
                out["rating"] = str(ar["ratingValue"])
        if ld.get("@type"):
            t = ld["@type"]
            out["category"] = t if isinstance(t, str) else ", ".join(str(x) for x in t)
    # 90-day velocity and posts are not reliable in static HTML. Leave None.
    if out["review_count_total"] is None and out["name"] is None:
        out["note"] = "Fetched a public page but no listing JSON-LD was present."
    else:
        out["note"] = "JSON-LD from the public page only. 90-day review velocity and posts were not on the page we could read."
    return out


def _pick_ld(html: str) -> dict[str, Any] | None:
    re_script = re.compile(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.I | re.S,
    )
    want = re.compile(
        r"LocalBusiness|HVACBusiness|Plumber|Electrician|HomeAndConstructionBusiness|ProfessionalService",
        re.I,
    )
    for m in re_script.finditer(html):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        nodes: list[Any] = []

        def walk(n: Any) -> None:
            if n is None:
                return
            if isinstance(n, list):
                for x in n:
                    walk(x)
                return
            if isinstance(n, dict):
                nodes.append(n)
                if "@graph" in n:
                    walk(n["@graph"])

        walk(data)
        for n in nodes:
            t = n.get("@type")
            types = t if isinstance(t, list) else [t]
            if any(want.search(str(x or "")) for x in types):
                return n
    return None



def _best_hit(hits, name, city):
    """Pick a US hit whose name actually overlaps the query. Else None (thin)."""
    us = []
    for h in hits:
        cc = ((h.get("address") or {}).get("country_code") or "").lower()
        if cc in ("us", ""):
            us.append(h)
    pool = us or list(hits)
    if not pool:
        return None
    if not name:
        return pool[0]
    name_l = name.lower()
    city_l = (city or "").lower()
    best = None
    best_score = -1
    for h in pool:
        n = (h.get("name") or "").lower()
        d = (h.get("display_name") or "").lower()
        score = 0
        if name_l and name_l in n:
            score += 20
        elif name_l and name_l in d:
            score += 10
        for tok in name_l.split():
            if len(tok) > 2 and tok in n:
                score += 3
        if city_l and city_l in d:
            score += 4
        if score > best_score:
            best_score = score
            best = h
    if name and best_score < 3:
        return None
    return best


def lookup(raw: str) -> dict[str, Any]:
    parsed = parse_input(raw)
    city_from_input = (parsed.get("city") or "").strip()
    result: dict[str, Any] = {
        "ok": False,
        "thin": True,
        "thin_code": "",
        "thin_reason": "",
        "vertical_ok": True,
        "input": parsed,
        "subject": None,
        "competitors": [],
        "google": None,
        "sources": [],
        "bullets": [],
        "trace": [],
        "city_source": "input" if city_from_input else "",
        "missing_fields": [],
        "service_phrase": "HVAC / plumbing",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "unlock": False,
        "maps_url": parsed.get("url") or "",
    }
    if not parsed["raw"]:
        result["thin_code"] = "empty_input"
        result["thin_reason"] = "Paste a Google listing URL, or a shop name and city."
        result["bullets"] = []
        return _finish(result)

    google = None
    site: dict[str, Any] | None = None
    if parsed["url"]:
        google = _google_enrich(parsed["url"])
        result["google"] = google
        result["sources"].append("pasted public listing URL")
        result["trace"].append("google_preview" if google.get("preview") else "google_page")
        final = google.get("final_url") or ""
        if final and final != parsed["url"] and not parsed["name"]:
            parsed["name"] = _name_from_maps_url(final)
            if parsed["name"]:
                result["trace"].append("name_from_redirect")
            if not parsed.get("lat"):
                lat, lon = _coords_from_maps_url(final)
                if lat is not None and lon is not None:
                    parsed["lat"] = str(lat)
                    parsed["lon"] = str(lon)
        if google.get("name") and not parsed["name"]:
            parsed["name"] = google["name"]
            result["trace"].append("name_from_preview")
        if google.get("lat") and not parsed.get("lat"):
            parsed["lat"] = str(google["lat"])
            parsed["lon"] = str(google["lon"])
        if not google.get("fetched") and not google.get("name"):
            result["trace"].append("google_unreadable")
        result["input"] = parsed

    name = (parsed.get("name") or "").strip()
    city = city_from_input
    state = ""
    if not city and google and google.get("website"):
        site = _website_identity(google["website"])
        result["trace"].append("website_fetched" if site.get("ok") else "website_unreadable")
        site_name = site.get("name") or ""
        gname = google.get("name") or name
        if site.get("city") and (
            not site_name or name_score(gname, site_name) >= 0.5 or name_score(name, site_name) >= 0.5
        ):
            city = site["city"]
            state = site.get("state") or ""
            result["city_source"] = "website_schema"
            result["trace"].append("city_from_website")
        elif site.get("city"):
            result["trace"].append("website_city_name_mismatch")
    if not city and parsed.get("lat") and parsed.get("lon"):
        try:
            rev = _reverse_locality(float(parsed["lat"]), float(parsed["lon"]))
        except ValueError:
            rev = {"city": ""}
        if rev.get("city"):
            city = rev["city"]
            state = rev.get("state") or state
            result["city_source"] = "map_pin"
            result["trace"].append("city_from_map_pin")
        elif rev.get("postcode"):
            z = _city_from_postcode(rev["postcode"])
            if z.get("city"):
                city = z["city"]
                state = z.get("state") or rev.get("state") or state
                result["city_source"] = "postcode"
                result["trace"].append("city_from_postcode")
            else:
                result["trace"].append("postcode_city_missing")
        else:
            result["trace"].append("map_pin_city_missing")
    if city:
        parsed["city"] = city
        result["input"] = parsed

    # Name + city is the fallback when the URL had no city or no street address.
    subject_hit = None
    if name and city:
        if not city_from_input:
            result["trace"].append("fallback_name_city")
        hits = _nominatim({"q": f"{name} {city} United States", "limit": "8"})
        result["sources"].append("openstreetmap nominatim")
        time.sleep(1.05)
        subject_hit = _best_hit(hits, name, city)
        result["trace"].append("nominatim_name_city_hit" if subject_hit else "nominatim_name_city_miss")
    elif name or parsed.get("query"):
        q = f"{name} United States" if name else parsed["query"]
        hits = _nominatim({"q": q, "limit": "8"})
        result["sources"].append("openstreetmap nominatim")
        time.sleep(1.05)
        subject_hit = _best_hit(hits, name, "")
        result["trace"].append("nominatim_name_only_hit" if subject_hit else "nominatim_name_only_miss")

    gname = ((google or {}).get("name") or "").strip()
    if not subject_hit and gname and city and gname.lower() != name.lower():
        hits = _nominatim({"q": f"{gname} {city} United States", "limit": "8"})
        time.sleep(1.05)
        subject_hit = _best_hit(hits, gname, city)
        result["trace"].append("nominatim_preview_name_city_hit" if subject_hit else "nominatim_preview_name_city_miss")
        if not name:
            name = gname
            parsed["name"] = gname
            result["input"] = parsed

    if not subject_hit and not (name or gname):
        result["thin_code"] = "url_unparsed" if parsed.get("url") else "place_not_found"
        result["thin_reason"] = "We couldn't find that listing."
        result["missing_fields"] = ["business name", "primary category", "review count", "city"]
        return _finish(result)

    if subject_hit:
        subject = _place(subject_hit, "nominatim")
        if not _hit_has_street(subject_hit):
            # No street on the public map record. Do not invent one.
            subject["address"] = ""
        result["trace"].append("subject_from_osm")
    else:
        subject = _subject_from_observed(name or gname, city, state, google, site if isinstance(site, dict) else None)
        result["trace"].append("subject_from_public_listing")

    if parsed["name"] and not subject["name"]:
        subject["name"] = parsed["name"]
    if google and google.get("name") and not subject["name"]:
        subject["name"] = google["name"]
    if google and google.get("category"):
        subject["google_category"] = google["category"]
    if google and google.get("phone") and not subject.get("phone"):
        subject["phone"] = google["phone"]
    if google and google.get("website") and not subject.get("website"):
        subject["website"] = google["website"]
    if google and google.get("hours") and not subject.get("hours"):
        subject["hours"] = google["hours"]
    if google and google.get("review_count_total") is not None:
        subject["review_count_total"] = google["review_count_total"]
        subject["review_count_source"] = (
            "public Maps preview" if google.get("preview") else "public listing JSON-LD (total, not 90-day)"
        )
    if google and google.get("rating"):
        subject["rating"] = google["rating"]
    if google and google.get("service_area"):
        # The public listing hides the street. Do not fill it from OSM or the pin.
        subject["address"] = ""
        subject["service_area"] = True
        result["trace"].append("service_area_no_street")
    elif google and google.get("address"):
        subject["address"] = google["address"]
        subject["service_area"] = False
        addr_city, addr_state = _city_state_from_address(google["address"])
        if addr_city and not subject.get("city"):
            subject["city"] = addr_city
        if addr_state and not subject.get("state"):
            subject["state"] = addr_state
    elif site and site.get("street") and not subject.get("address") and not subject.get("service_area"):
        subject["address"] = ", ".join(p for p in (site.get("street"), site.get("city"), site.get("state")) if p)

    if result["city_source"] == "input" and city:
        subject["city"] = city
    elif city and not subject.get("city"):
        subject["city"] = city
    if state and not subject.get("state"):
        subject["state"] = state

    if subject.get("country_code") and subject["country_code"] != "us":
        result["thin_code"] = "not_us"
        result["thin_reason"] = "US HVAC and plumbing shops only."
        result["vertical_ok"] = False
        result["subject"] = subject
        return _finish(result)

    city = subject.get("city") or city
    result["subject"] = subject

    vert = subject["vertical"]
    extra_name = f"{parsed.get('name') or ''} {parsed.get('query') or ''} {(google or {}).get('category') or ''}"
    if vert == "unknown":
        if subject_hit:
            vert = _is_hvac_plumbing(subject_hit, extra_name)
        else:
            vert = _is_hvac_plumbing(
                {
                    "name": subject.get("name") or "",
                    "type": "",
                    "display_name": subject.get("name") or "",
                    "extratags": {},
                    "address": {},
                },
                extra_name,
            )
        subject["vertical"] = vert
    if vert == "other":
        result["vertical_ok"] = False
        result["thin"] = True
        result["thin_code"] = "wrong_vertical"
        result["thin_reason"] = (
            "This page is HVAC and plumbing only. Public map data does not show this listing as either."
        )
        return _finish(result)

    blob = (_blob(subject_hit) if subject_hit else "") + " " + extra_name.lower()
    if "plumb" in blob or "drain" in blob or "sewer" in blob:
        result["service_phrase"] = "emergency plumber"
    elif any(w in blob for w in ("hvac", "heating", "cooling", "furnace", "air condition")):
        result["service_phrase"] = "AC repair"

    # 2) Nearby public HVAC / plumbing listings in the same city (not invented).
    competitors: list[dict[str, Any]] = []
    if city:
        seen_names = {subject["name"].lower()}
        for term in ("plumber", "hvac"):
            more = _nominatim({"q": f"{term} {city} United States", "limit": "10"})
            time.sleep(1.05)
            for h in more:
                p = _place(h, "nominatim")
                if not p["name"] or p["name"].lower() in seen_names:
                    continue
                if p["vertical"] == "other":
                    continue
                # Prefer same-ish city
                if p["city"] and city and p["city"].lower() != city.lower():
                    # keep if display_name contains the city
                    if city.lower() not in (p["display_name"] or "").lower():
                        continue
                if p["vertical"] != "hvac_plumbing" and p["osm_type"] not in OSM_OK:
                    # only keep if name clearly HVAC/plumbing
                    if not any(w in p["name"].lower() for w in HVAC_PLUMBING):
                        continue
                seen_names.add(p["name"].lower())
                competitors.append(p)
                if len(competitors) >= 3:
                    break
            if len(competitors) >= 3:
                break
    result["competitors"] = competitors[:3]

    if not competitors:
        result["thin"] = True
        result["unlock"] = False
        result["thin_code"] = "no_competitors"
        result["thin_reason"] = (
            "Not enough other public shops to compare. The full check stays hidden until 3 real gaps are visible."
        )
        result["bullets"] = _bullets(result)
        result["missing_fields"] = _missing_fields(result)
        return _finish(result)

    result["thin"] = False
    result["thin_code"] = "ok"
    result["thin_reason"] = ""
    result["ok"] = True
    result["unlock"] = True
    result["bullets"] = _bullets(result)
    result["missing_fields"] = []
    return _finish(result)


def _bullets(result: dict[str, Any]) -> list[dict[str, str]]:
    subject = result.get("subject") or {}
    comps = result.get("competitors") or []
    city = subject.get("city") or result.get("input", {}).get("city") or "your city"
    service = result.get("service_phrase") or "HVAC / plumbing"
    google = result.get("google") or {}

    # Categories — only name tags we actually saw.
    sub_tags = [t.split("=", 1)[-1] for t in (subject.get("tags") or []) if t]
    sub_set = {t.lower() for t in sub_tags}
    missing = []
    who = None
    for c in comps:
        for t in c.get("tags") or []:
            val = t.split("=", 1)[-1]
            if val.lower() not in sub_set and val.lower() not in {m.lower() for m in missing}:
                missing.append(val)
                who = c.get("name")
                break
        if missing:
            break
    gcat = subject.get("google_category")
    if missing:
        gap = _pretty_tag(missing[0])
        cat_body = (
            f'Competitors ranking for “{service} in {city}” list {gap}'
            + (f" ({who})" if who else "")
            + ". You don’t — at least not on the public map tags we could read."
        )
    elif gcat:
        cat_body = (
            f"Your public listing type reads as {gcat}. "
            f"We could not compare secondary Google categories against the shops Google shows first in {city}."
        )
    elif sub_tags:
        cat_body = (
            f"Your public map tags: {', '.join(sub_tags)}. "
            f"We did not observe a competitor category you are missing. Missing is not guessed."
        )
    else:
        cat_body = (
            f"We could not read Google categories for “{service} in {city}” on a public page. "
            "No missing category is invented."
        )

    # Reviews — never invent a 90-day number.
    total = subject.get("review_count_total")
    if google.get("review_dates_90d") is not None and comps:
        n_you = google["review_dates_90d"]
        rev_body = (
            f"{comps[0].get('name', 'A competitor')} — 90-day public review dates were readable. "
            f"You picked up {n_you} in that public snippet. Star rating is not the gap. Velocity is."
        )
    elif total is not None:
        source = subject.get("review_count_source") or "A public page"
        rev_body = (
            f"{source} shows {total} reviews total for you. "
            "A 90-day velocity was not on the page we could read, so it is not shown. "
            "Star rating is not the gap. Velocity is. We will not guess the 90-day count."
        )
    elif comps:
        cname = comps[0]["name"]
        rev_body = (
            f"{cname} — public pages we could read did not include 90-day review dates for you or them. "
            "Star rating is not the gap. Velocity is. We will not invent a review count."
        )
    else:
        rev_body = (
            "Public pages we could read did not include a review count or 90-day review dates. "
            "We will not invent a review count."
        )

    # Posts — never invent.
    if google.get("posts_90d") is not None:
        posts_body = (
            f"Your listing has {google['posts_90d']} posts in 90 days on the public page we read. "
            "Posts expire in 7 days. A quiet profile looks closed."
        )
    else:
        posts_body = (
            "Your listing’s public page did not include a 90-day Google post count we could read. "
            "Posts expire in 7 days. A quiet profile looks closed. We will not invent a post count."
        )

    return [
        {"title": "Categories", "body": cat_body},
        {"title": "Reviews", "body": rev_body},
        {"title": "Posts", "body": posts_body},
    ]


def this_week_later(result: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Actions only from observed gaps. No ranking promise."""
    this_week: list[str] = []
    later: list[str] = []
    subject = result.get("subject") or {}
    comps = result.get("competitors") or []
    sub_tags = {t.split("=", 1)[-1].lower() for t in (subject.get("tags") or [])}
    missing = []
    for c in comps:
        for t in c.get("tags") or []:
            val = t.split("=", 1)[-1]
            if val.lower() not in sub_tags and val not in missing:
                missing.append(val)
    if missing:
        this_week.append(
            f"Open your Google Business Profile categories. Public map tags on competitors included {missing[0]}. "
            "Add a category only if you actually offer that work. Do not keyword-stuff the business name."
        )
    else:
        later.append(
            "Re-check categories on the live Google listing (primary + secondaries) against the three shops Google shows first. "
            "Public pages this session did not show a missing Google category string."
        )
    this_week.append(
        "If you have not posted this week: write one Google post (offer, job photo, or neighborhood you actually served). Posts expire in 7 days."
    )
    later.append(
        "Count your last 90 days of reviews inside the listing (dated reviews only). Do not buy reviews. Reply to every review you already have."
    )
    later.append(
        "Fill the Services section with 2–3 honest sentences each for work you actually do. Leave blank services blank — do not invent them."
    )
    if not this_week:
        this_week.append("No this-week action from what we could read on the public listing this session.")
    return this_week, later

UNKNOWN = "UNKNOWN"


def name_score(a: str, b: str) -> float:
    a = (a or "").lower().strip()
    b = (b or "").lower().strip()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85
    at, bt = set(a.split()), set(b.split())
    if not at or not bt:
        return 0.0
    return len(at & bt) / len(at | bt)



def run_lookup(name: str, city: str, listing_url: str) -> dict[str, Any]:
    """Adapter used by app.py / report.py. Does not invent review counts."""
    name = (name or "").strip()
    city = (city or "").strip()
    listing_url = (listing_url or "").strip()
    if listing_url:
        raw = listing_url
    elif name and city:
        raw = f"{name}, {city.replace(',', ' ')}"
    else:
        raw = name or city

    data = lookup(raw)
    subject = data.get("subject") or {}
    google = data.get("google") or {}
    comps = data.get("competitors") or []
    parsed = data.get("input") or {}
    resolved_name = (subject.get("name") or parsed.get("name") or name or "").strip()
    resolved_city = (subject.get("city") or parsed.get("city") or city or "").strip()
    resolved_url = listing_url or parsed.get("url") or ""

    rating = google.get("rating") if google else subject.get("rating")
    try:
        rating_n = float(str(rating).replace(",", "")) if rating not in (None, "") else None
    except ValueError:
        rating_n = None
    rc = None
    if google and google.get("review_count_total") is not None:
        rc = google["review_count_total"]
    elif subject.get("review_count_total") is not None:
        rc = subject["review_count_total"]
    try:
        rc = int(rc) if rc is not None else None
    except (TypeError, ValueError):
        rc = None

    tags = subject.get("tags") or []
    category = subject.get("osm_type") or subject.get("google_category")
    if not category and tags:
        category = tags[0]

    listing = {
        "name": resolved_name or None,
        "address": subject.get("address") or None,
        "city": resolved_city or None,
        "state": subject.get("state") or None,
        "service_area": bool(subject.get("service_area")),
        "postcode": subject.get("postcode") or None,
        "phone": subject.get("phone") or None,
        "website": subject.get("website") or None,
        "hours": subject.get("hours") or None,
        "category": category or None,
        "lat": subject.get("lat"),
        "lon": subject.get("lon"),
        "osm_url": None,
        "rating": rating_n,
        "review_count": rc,
        "review_source": subject.get("review_count_source")
        or ("public listing JSON-LD" if rc is not None else None),
        "same_as": [],
        "_origin": {},
    }
    if subject.get("osm_id") and subject.get("osm_kind"):
        listing["osm_url"] = f"https://www.openstreetmap.org/{subject['osm_kind']}/{subject['osm_id']}"

    sources: list[dict[str, Any]] = []
    if subject:
        sources.append({
            "id": "nominatim",
            "label": "OpenStreetMap Nominatim",
            "status": "ok",
            "detail": f"Matched {subject.get('name')!r} in OSM. Nearby shops are OSM places, not a Google ranking.",
            "facts": {k: listing.get(k) for k in ("name", "address", "phone", "website", "hours", "category")},
        })
    else:
        sources.append({
            "id": "nominatim",
            "label": "OpenStreetMap Nominatim",
            "status": "empty",
            "detail": data.get("thin_reason") or "No OSM match.",
            "facts": {},
        })

    if listing_url:
        gstatus = "ok" if google and google.get("fetched") and (google.get("review_count_total") is not None or google.get("name")) else (
            "blocked" if google and google.get("note") and "not readable" in (google.get("note") or "").lower()
            else "empty"
        )
        sources.append({
            "id": "google_maps",
            "label": "Google Maps public page",
            "status": gstatus,
            "detail": (google or {}).get("note") or "No Google URL fetch.",
            "facts": {
                k: google.get(k)
                for k in ("name", "category", "rating", "review_count_total", "final_url")
                if google
            },
        })
    else:
        sources.append({
            "id": "google_maps",
            "label": "Google Maps public page",
            "status": "skipped",
            "detail": "No Google listing URL pasted. We did not guess a Maps URL.",
            "facts": {},
        })

    nearby = []
    for c in comps:
        nearby.append({
            "name": c.get("name"),
            "address": c.get("address") or c.get("display_name"),
            "phone": c.get("phone") or None,
            "website": c.get("website") or None,
            "category": c.get("osm_type") or (c.get("tags") or [None])[0],
            "osm_url": None,
        })
    if nearby:
        sources.append({
            "id": "osm_nearby",
            "label": "OpenStreetMap nearby HVAC/plumbing",
            "status": "ok",
            "detail": f"{len(nearby)} other OSM trade listing(s). Not a Google ranking.",
            "facts": {"listings": nearby},
        })
    else:
        sources.append({
            "id": "osm_nearby",
            "label": "OpenStreetMap nearby HVAC/plumbing",
            "status": "empty",
            "detail": "No other HVAC/plumbing OSM listings returned for this city.",
            "facts": {},
        })

    # Website schema if OSM had a URL — best-effort, never invent reviews.
    site_url = listing.get("website")
    if site_url:
        try:
            status, body, final = _get(site_url, accept="text/html,application/xhtml+xml")
        except Exception as e:
            status, body, final = 0, str(e), site_url
        if status == 200 and body:
            ld = _pick_ld(body)
            facts = {"final_url": final}
            if ld:
                if ld.get("telephone") and not listing.get("phone"):
                    listing["phone"] = str(ld["telephone"])
                    facts["phone"] = listing["phone"]
                if ld.get("url") and not listing.get("website"):
                    listing["website"] = str(ld["url"])
                ar = ld.get("aggregateRating") if isinstance(ld.get("aggregateRating"), dict) else None
                if ar and ar.get("reviewCount") not in (None, ""):
                    # The site's own AggregateRating is not a Google review count.
                    facts["website_review_count_not_used"] = str(ar.get("reviewCount"))
            if facts.get("website_review_count_not_used"):
                website_detail = (
                    f"Fetched {final}. The site published reviewCount "
                    f"{facts['website_review_count_not_used']}, which is not a Google review count, so it is not used."
                )
            else:
                website_detail = f"Fetched {final}. No Google review count in schema."
            sources.append({
                "id": "website",
                "label": "Business website (schema.org)",
                "status": "ok" if ld else "empty",
                "detail": website_detail,
                "facts": facts,
            })
        else:
            sources.append({
                "id": "website",
                "label": "Business website (schema.org)",
                "status": "blocked" if status in (401, 403, 429) else "error",
                "detail": f"HTTP {status} fetching {site_url}",
                "facts": {},
            })
    else:
        sources.append({
            "id": "website",
            "label": "Business website (schema.org)",
            "status": "skipped",
            "detail": "No website URL in public records.",
            "facts": {},
        })

    found = bool(listing.get("name") or listing.get("address") or listing.get("phone") or listing.get("website"))
    if resolved_name and resolved_city:
        retry_q = f"{resolved_name}, {resolved_city}"
    elif resolved_name:
        retry_q = resolved_name
    else:
        retry_q = resolved_url
    return {
        "queried_at": datetime.now().astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).strftime("%b %-d, %Y, %-I:%M %p ET"),
        "input": {
            "name": resolved_name or UNKNOWN,
            "city": resolved_city or UNKNOWN,
            "listing_url": resolved_url or UNKNOWN,
        },
        "retry_q": retry_q,
        "maps_url": data.get("maps_url") or resolved_url or "",
        "found": found,
        "listing": listing,
        "sources": sources,
        "nearby": nearby,
        "raw": data,
    }
