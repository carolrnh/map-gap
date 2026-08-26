"""Build teaser + full report dicts from a lookup. No invented numbers."""

from __future__ import annotations

from lookup import UNKNOWN

PRICE = 197

GBP_FIELDS = [
    ("name", "Business name"),
    ("address", "Address (NAP)"),
    ("phone", "Phone"),
    ("website", "Website"),
    ("hours", "Hours"),
    ("category", "Primary category (as public data labeled it)"),
    ("rating", "Star rating"),
    ("review_count", "Review count"),
]


def _unk(v):
    if v is None or v == "" or v == UNKNOWN:
        return UNKNOWN
    return v


def completeness(listing: dict) -> list[dict]:
    rows = []
    for key, label in GBP_FIELDS:
        val = listing.get(key)
        if val is None or val == "" or val == UNKNOWN:
            state = "unknown"
            shown = UNKNOWN
        else:
            state = "found"
            shown = val
        rows.append({"key": key, "label": label, "state": state, "value": shown})

    # These GBP panel fields are almost never in the public HTML we can fetch.
    for key, label in [
        ("secondaries", "Secondary Google categories"),
        ("photos", "Photo count on the Google listing"),
        ("posts", "Google posts in the last 90 days"),
        ("services", "Google services section"),
        ("review_velocity", "Reviews in last 30 / 60 / 90 days"),
        ("review_replies", "Owner replies to reviews"),
        ("map_pack", "Map-pack position for a keyword"),
    ]:
        rows.append({"key": key, "label": label, "state": "unknown", "value": UNKNOWN})
    return rows


def gaps_from_listing(listing: dict, sources: list[dict]) -> list[dict]:
    """Actions tied to observed facts only. Never 'get more reviews' with a fake quota."""
    gaps = []
    if not listing.get("website"):
        gaps.append(
            {
                "id": "website",
                "severity": "this_week",
                "title": "No website URL in the public records we could read",
                "detail": "OpenStreetMap and schema did not show a site. On Google Business Profile, add the real site if you have one. Do not buy a fake site to look complete.",
            }
        )
    if not listing.get("phone"):
        gaps.append(
            {
                "id": "phone",
                "severity": "this_week",
                "title": "No phone number in the public records we could read",
                "detail": "If customers call from the map, a missing number is a missed job. Confirm the live Google listing shows the number you answer.",
            }
        )
    if not listing.get("hours"):
        gaps.append(
            {
                "id": "hours",
                "severity": "this_week",
                "title": "Hours were not in the public records we could read",
                "detail": "Could be missing on the Google listing, or just missing from OSM/schema. Open the listing and fill hours, including emergency/after-hours if that is real.",
            }
        )
    if not listing.get("address"):
        gaps.append(
            {
                "id": "address",
                "severity": "this_week",
                "title": "No street address in the public records we could read",
                "detail": "Service-area businesses may hide the address. If you have a shop customers visit, the listing should show it. Do not invent an office you do not have — Google suspends that.",
            }
        )

    maps = next((s for s in sources if s["id"] == "google_maps"), None)
    if maps and maps.get("status") in ("blocked", "empty", "error"):
        gaps.append(
            {
                "id": "gbp_panel",
                "severity": "this_week",
                "title": "We could not read your Google listing panel",
                "detail": maps.get("detail")
                or "Google did not include categories, photos, posts, or reviews in the HTML we fetched. The $197 report is a manual public-page pass plus this automated file.",
            }
        )

    if listing.get("review_count") is None:
        gaps.append(
            {
                "id": "reviews_unknown",
                "severity": "this_month",
                "title": "Review count is UNKNOWN — not zero",
                "detail": "We did not observe a review count on a public page. That is not a reason to buy reviews. Reply to real reviews you already have; ask recent customers; never pay for fake ones.",
            }
        )

    # Always include process gaps that do not require a number.
    gaps.append(
        {
            "id": "categories",
            "severity": "this_week",
            "title": "Check primary + secondary categories on the live Google listing",
            "detail": "Automated fetch cannot see Google's secondary categories. HVAC shops often need HVAC contractor plus the repair/install categories they actually offer. Plumbers: Plumber, not generic Contractor. Do not keyword-stuff the business name.",
        }
    )
    gaps.append(
        {
            "id": "posts",
            "severity": "this_month",
            "title": "Google posts expire in 7 days",
            "detail": "Most shops post nothing. If the live listing has no recent posts, start 2–3 honest posts a week (job photos, seasonal service, neighborhoods you actually serve). This is not a ranking promise.",
        }
    )
    gaps.append(
        {
            "id": "services",
            "severity": "this_month",
            "title": "Fill the services section with real work you do",
            "detail": "If drain cleaning, water heaters, furnace install, or IAQ are on your site but not on the Google listing, add them with 2–3 sentence descriptions. Do not list work you do not do.",
        }
    )
    return gaps


def source_summary(sources: list[dict]) -> dict:
    fetched, blocked, empty, errors = [], [], [], []
    for s in sources:
        item = {"id": s["id"], "label": s["label"], "detail": s.get("detail"), "status": s.get("status")}
        st = s.get("status")
        if st == "ok":
            fetched.append(item)
        elif st == "blocked":
            blocked.append(item)
        elif st == "empty":
            empty.append(item)
        elif st == "skipped":
            empty.append(item)
        else:
            errors.append(item)
    return {"fetched": fetched, "blocked": blocked, "empty": empty, "errors": errors}


def build_reports(lookup: dict) -> dict:
    listing = lookup.get("listing") or {}
    sources = lookup.get("sources") or []
    nearby = lookup.get("nearby") or []
    # Exclude self from nearby by name
    self_name = listing.get("name") or lookup.get("input", {}).get("name")
    others = []
    for n in nearby:
        if name_close(self_name, n.get("name")):
            continue
        others.append(
            {
                "name": n.get("name") or UNKNOWN,
                "address": n.get("address") or UNKNOWN,
                "phone": n.get("phone") or UNKNOWN,
                "website": n.get("website") or UNKNOWN,
                "category": n.get("category") or UNKNOWN,
                "osm_url": n.get("osm_url") or UNKNOWN,
                "note": "OpenStreetMap listing — not a Google map-pack rank",
            }
        )

    gaps = gaps_from_listing(listing, sources)
    rows = completeness(listing)
    summary = source_summary(sources)

    display_name = listing.get("name") or lookup.get("input", {}).get("name") or UNKNOWN
    city = listing.get("city") or lookup.get("input", {}).get("city") or UNKNOWN

    teaser = {
        "kind": "teaser",
        "price": PRICE,
        "display_name": display_name,
        "city": city,
        "found": bool(lookup.get("found")),
        "queried_at": lookup.get("queried_at"),
        "nap": {
            "name": _unk(listing.get("name")),
            "address": _unk(listing.get("address")),
            "phone": _unk(listing.get("phone")),
            "website": _unk(listing.get("website")),
            "hours": _unk(listing.get("hours")),
            "category": _unk(listing.get("category")),
        },
        "rating": listing.get("rating"),  # number or None
        "review_count": listing.get("review_count"),  # number or None
        "review_source": listing.get("review_source"),
        "review_unknown_reason": None
        if listing.get("review_count") is not None
        else "No public page we fetched included a schema.org reviewCount for this business. UNKNOWN is not zero.",
        "completeness": rows,
        "gaps_preview": [g for g in gaps if g["severity"] == "this_week"][:4],
        "sources": summary,
        "locked": [
            "You vs up to 3 nearby trade listings (OSM, labeled — not map-pack rank)",
            "Full source log (what loaded, what Google blocked)",
            "This-week / this-month / later actions tied to observed gaps",
            "48-hour operator pass on the live Google listing: secondary categories, review velocity if dates are visible, posts, services",
        ],
    }

    full = {
        "kind": "full",
        "price": PRICE,
        "display_name": display_name,
        "city": city,
        "found": bool(lookup.get("found")),
        "queried_at": lookup.get("queried_at"),
        "nap": teaser["nap"],
        "rating": teaser["rating"],
        "review_count": teaser["review_count"],
        "review_source": teaser["review_source"],
        "review_unknown_reason": teaser["review_unknown_reason"],
        "completeness": rows,
        "sources_full": sources_public(sources),
        "sources": summary,
        "nearby": others[:6],
        "gaps": gaps,
        "this_week": [g for g in gaps if g["severity"] == "this_week"],
        "this_month": [g for g in gaps if g["severity"] == "this_month"],
        "later": [
            {
                "id": "rebuild",
                "title": "Listing rebuild is a separate $397 one-time job (thank-you page only)",
                "detail": "Not included in this $197 report: category list to add yourself, services copy, 8-week post calendar, review-reply templates. Offered after this report is paid. Not a monthly plan.",
            },
        ],
        "legal": (
            "This is research and copy for you to apply on your own Google Business Profile. "
            "You keep ownership. No ranking is guaranteed. We do not write fake reviews or change your legal business name."
        ),
        "operator_note": (
            "Google’s listing panel (secondary categories, review dates, posts, photos) is usually "
            "not in the HTML an automated fetch can read. After payment, the 48-hour fulfillment "
            "re-reads the public listing in a browser and fills UNKNOWN fields that are actually visible — "
            "still UNKNOWN if they are not."
        ),
    }
    return {"teaser": teaser, "full": full}


def sources_public(sources: list[dict]) -> list[dict]:
    out = []
    for s in sources:
        facts = dict(s.get("facts") or {})
        facts.pop("candidates", None)
        # Do not dump huge HTML or OSM internals
        listings = facts.get("listings")
        if listings:
            facts["listings"] = [
                {k: x.get(k) for k in ("name", "address", "phone", "website", "category", "osm_url")}
                for x in listings[:8]
            ]
        results = facts.get("results")
        if results:
            facts["results"] = results[:6]
        out.append(
            {
                "id": s.get("id"),
                "label": s.get("label"),
                "status": s.get("status"),
                "detail": s.get("detail"),
                "facts": {k: v for k, v in facts.items() if k not in ("match_score",)},
            }
        )
    return out


def name_close(a, b) -> bool:
    from lookup import name_score

    return name_score(str(a or ""), str(b or "")) >= 0.7
