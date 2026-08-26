"""Public-data teaser lookup for Map Gap.

Sources: OpenStreetMap Nominatim (identity + nearby HVAC/plumbing), and
a best-effort fetch of a public Google listing URL the buyer pasted.

Never invent review counts, post counts, ratings, or rankings.
Unobserved fields stay None / UNKNOWN. Thin data hides the $197 unlock.
"""

from __future__ import annotations

import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

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
    # Rarely present as a clean field. Leave empty; Nominatim fills it.
    return ""


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
    """Best-effort public page parse. Missing fields stay None. Never guess counts."""
    out: dict[str, Any] = {
        "fetched": False,
        "final_url": url,
        "name": None,
        "category": None,
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
    if any(
        s in low
        for s in (
            "before you continue",
            "unusual traffic",
            "enable javascript",
            "consent.google",
            "detected unusual traffic",
        )
    ):
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
    result: dict[str, Any] = {
        "ok": False,
        "thin": True,
        "thin_reason": "",
        "vertical_ok": True,
        "input": parsed,
        "subject": None,
        "competitors": [],
        "google": None,
        "sources": [],
        "bullets": [],
        "service_phrase": "HVAC / plumbing",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "unlock": False,
    }
    if not parsed["raw"]:
        result["thin_reason"] = "Paste a Google listing URL, or a shop name and city."
        result["bullets"] = []
        return result

    # 1) Identity via Nominatim
    q = parsed["query"] or parsed["raw"]
    if parsed["name"] and parsed["city"]:
        q = f"{parsed['name']} {parsed['city']} United States"
    elif parsed["name"]:
        q = f"{parsed['name']} United States"
    hits = _nominatim({"q": q, "limit": "8"})
    result["sources"].append("openstreetmap nominatim")
    time.sleep(1.05)

    subject_hit = _best_hit(hits, parsed.get("name") or "", parsed.get("city") or "")

    # If they pasted a Maps URL, try to enrich from that public page (and follow short links).
    google = None
    if parsed["url"]:
        google = _google_enrich(parsed["url"])
        result["google"] = google
        result["sources"].append("pasted public listing URL")
        if google.get("name") and not parsed["name"]:
            parsed["name"] = google["name"]
            result["input"] = parsed

    if not subject_hit:
        result["thin_reason"] = (
            "Not enough public map-pack data to tease. Don’t pay $197 for a guess."
        )
        return result

    subject = _place(subject_hit, "nominatim")
    if parsed["name"] and not subject["name"]:
        subject["name"] = parsed["name"]
    if google and google.get("name") and not subject["name"]:
        subject["name"] = google["name"]
    if google and google.get("category"):
        subject["google_category"] = google["category"]
    if google and google.get("review_count_total") is not None:
        subject["review_count_total"] = google["review_count_total"]
        subject["review_count_source"] = "public listing JSON-LD (total, not 90-day)"
    if google and google.get("rating"):
        subject["rating"] = google["rating"]

    if subject["country_code"] and subject["country_code"] != "us":
        result["thin_reason"] = "US HVAC and plumbing shops only."
        result["vertical_ok"] = False
        result["subject"] = subject
        return result

    city = parsed["city"] or subject["city"]
    subject["city"] = city
    result["subject"] = subject

    vert = subject["vertical"]
    extra_name = f"{parsed['name']} {parsed['query']} {google.get('category') if google else ''}"
    if vert == "unknown":
        vert = _is_hvac_plumbing(subject_hit, extra_name)
        subject["vertical"] = vert
    if vert == "other":
        result["vertical_ok"] = False
        result["thin"] = True
        result["thin_reason"] = (
            "This page is HVAC and plumbing only. Public map data does not show this listing as either."
        )
        return result

    blob = _blob(subject_hit) + extra_name.lower()
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
        result["thin_reason"] = (
            "Not enough public map-pack data to tease. Don’t pay $197 for a guess."
        )
        result["bullets"] = _bullets(result)
        return result

    result["thin"] = False
    result["thin_reason"] = ""
    result["ok"] = True
    result["unlock"] = True
    result["bullets"] = _bullets(result)
    return result


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
            f"We could not compare secondary Google categories against a public map pack in {city}."
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
        rev_body = (
            f"Public listing JSON-LD shows {total} reviews total for you. "
            "A 90-day velocity was not on the page we could read, so it is not shown. "
            "Star rating is not the gap. Velocity is. We will not guess the 90-day count."
        )
    else:
        cname = comps[0]["name"] if comps else "A competitor"
        rev_body = (
            f"{cname} — public pages we could read did not include 90-day review dates for you or them. "
            "Star rating is not the gap. Velocity is. We will not invent a review count."
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
            "Re-check categories on the live Google listing (primary + secondaries) against the three map-pack shops. "
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
        this_week.append("No this-week action from observed public gaps this session.")
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
        "name": subject.get("name") or name or None,
        "address": subject.get("address") or None,
        "city": subject.get("city") or city or None,
        "state": subject.get("state") or None,
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
            "detail": f"Matched {subject.get('name')!r} in OSM. Nearby shops are OSM places, not Google map-pack ranks.",
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
            "detail": f"{len(nearby)} other OSM trade listing(s). Not a Google map-pack rank.",
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
                if ar:
                    if listing["review_count"] is None and ar.get("reviewCount") not in (None, ""):
                        try:
                            listing["review_count"] = int(str(ar["reviewCount"]).replace(",", ""))
                            listing["review_source"] = "website schema.org AggregateRating"
                            facts["review_count"] = listing["review_count"]
                        except ValueError:
                            pass
                    if listing["rating"] is None and ar.get("ratingValue") not in (None, ""):
                        try:
                            listing["rating"] = float(str(ar["ratingValue"]).replace(",", ""))
                            facts["rating"] = listing["rating"]
                        except ValueError:
                            pass
            sources.append({
                "id": "website",
                "label": "Business website (schema.org)",
                "status": "ok" if facts.get("review_count") is not None or ld else "empty",
                "detail": f"Fetched {final}. "
                + ("schema reviewCount observed" if facts.get("review_count") is not None else "no AggregateRating.reviewCount in schema"),
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
    return {
        "queried_at": datetime.now().astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).strftime("%b %-d, %Y, %-I:%M %p ET"),
        "input": {"name": name or UNKNOWN, "city": city or UNKNOWN, "listing_url": listing_url or UNKNOWN},
        "found": found,
        "listing": listing,
        "sources": sources,
        "nearby": nearby,
        "raw": data,
    }
