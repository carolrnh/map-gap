"""Durable free-check links for Render's free tier.

The free-tier disk is wiped on every deploy, so a sqlite id 404s after
a redeploy. The public result is compressed into the URL and signed.
Payment unlock is never granted by the token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import zlib

VERSION = 1
_MAX_JSON = 200_000

_LISTING_KEYS = (
    "name",
    "address",
    "city",
    "state",
    "postcode",
    "phone",
    "website",
    "hours",
    "category",
    "rating",
    "review_count",
    "review_source",
    "service_area",
)


def link_key() -> bytes:
    """Stable across redeploys.

    MAPGAP_SECRET_KEY on Render survives deploys. If it is unset, a
    fixed key still lets public checkup links survive a free-tier
    restart. The token does not unlock a paid report.
    """
    secret = (os.environ.get("MAPGAP_SECRET_KEY") or "").strip()
    if not secret:
        secret = "mapgap-public-checkup-link-v1"
    return secret.encode()


def view_from_lookup(lookup: dict, rid: str) -> dict:
    listing = lookup.get("listing") or {}
    raw = lookup.get("raw") or {}
    bullets = []
    for bullet in (raw.get("bullets") or [])[:6]:
        if isinstance(bullet, dict):
            bullets.append(
                {
                    "title": str(bullet.get("title") or ""),
                    "body": str(bullet.get("body") or ""),
                }
            )
    missing = [str(item) for item in (raw.get("missing_fields") or [])[:12]]
    vertical_ok = raw.get("vertical_ok", True)
    if vertical_ok is None:
        vertical_ok = True
    return {
        "v": VERSION,
        "id": rid,
        "queried_at": lookup.get("queried_at") or "",
        "input": lookup.get("input") or {},
        "retry_q": lookup.get("retry_q") or "",
        "maps_url": lookup.get("maps_url") or "",
        "found": bool(lookup.get("found")),
        "listing": {key: listing.get(key) for key in _LISTING_KEYS},
        "raw": {
            "thin": bool(raw.get("thin")),
            "thin_reason": raw.get("thin_reason") or "",
            "vertical_ok": bool(vertical_ok),
            "bullets": bullets,
            "missing_fields": missing,
            "city_source": raw.get("city_source") or "",
            "unlock": bool(raw.get("unlock")),
        },
    }


def lookup_from_view(view: dict) -> dict:
    return {
        "queried_at": view.get("queried_at") or "",
        "input": view.get("input") or {},
        "retry_q": view.get("retry_q") or "",
        "maps_url": view.get("maps_url") or "",
        "found": bool(view.get("found")),
        "listing": view.get("listing") or {},
        "sources": [],
        "nearby": [],
        "raw": view.get("raw") or {},
    }


def pack_link(view: dict) -> str:
    raw = json.dumps(view, separators=(",", ":"), ensure_ascii=False).encode()
    body = base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(
        hmac.new(link_key(), body.encode(), hashlib.sha256).digest()[:12]
    ).decode().rstrip("=")
    return f"v1.{body}.{sig}"


def unpack_link(token: str) -> dict | None:
    if not token or not token.startswith("v1."):
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    _, body, sig = parts
    if not body or not sig:
        return None
    try:
        got = _b64(sig)
        expect = hmac.new(link_key(), body.encode(), hashlib.sha256).digest()[:12]
        if not hmac.compare_digest(got, expect):
            return None
        raw = _inflate(_b64(body))
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("v") != VERSION:
        return None
    if not isinstance(data.get("listing"), dict) or not isinstance(data.get("raw"), dict):
        return None
    return data


def _inflate(blob: bytes) -> bytes:
    decomp = zlib.decompressobj()
    out = decomp.decompress(blob, _MAX_JSON + 1)
    if len(out) > _MAX_JSON or decomp.unconsumed_tail:
        raise ValueError("result link is too large")
    return out


def _b64(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)
