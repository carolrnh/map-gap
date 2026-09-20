#!/usr/bin/env python3
"""Map Gap — self-serve teaser + $197 paywall. No fake charges."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, abort, g, redirect, render_template, request, url_for

from lookup import UNKNOWN, run_lookup
from report import PRICE, build_reports

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "mapgap.sqlite"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

app = Flask(
    __name__,
    template_folder=str(ROOT / "templates"),
    static_folder=str(ROOT / "static"),
)
app.config["SECRET_KEY"] = os.environ.get("MAPGAP_SECRET_KEY") or secrets.token_hex(16)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

_db_lock = threading.Lock()


def stripe_url() -> str:
    return (os.environ.get("STRIPE_PAYMENT_LINK_URL") or "").strip()


def operator_key() -> str:
    return (os.environ.get("MAPGAP_OPERATOR_KEY") or "").strip()


def payment_connected() -> bool:
    return bool(stripe_url())


def db() -> sqlite3.Connection:
    conn = getattr(g, "_db", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        g._db = conn
    return conn


@app.teardown_appcontext
def close_db(_exc):
    conn = getattr(g, "_db", None)
    if conn is not None:
        conn.close()


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                input_json TEXT NOT NULL,
                lookup_json TEXT NOT NULL,
                teaser_json TEXT NOT NULL,
                full_json TEXT NOT NULL,
                unlocked INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()


init_db()


def save_report(lookup: dict, built: dict) -> str:
    rid = secrets.token_urlsafe(8).replace("-", "").replace("_", "")[:12]
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO reports (id, created_at, input_json, lookup_json, teaser_json, full_json, unlocked) VALUES (?,?,?,?,?,?,0)",
            (
                rid,
                lookup.get("queried_at") or "",
                json.dumps(lookup.get("input") or {}),
                json.dumps(lookup),
                json.dumps(built["teaser"]),
                json.dumps(built["full"]),
            ),
        )
        conn.commit()
        conn.close()
    return rid


def load_report(rid: str) -> dict | None:
    row = db().execute("SELECT * FROM reports WHERE id = ?", (rid,)).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "input": json.loads(row["input_json"]),
        "lookup": json.loads(row["lookup_json"]),
        "teaser": json.loads(row["teaser_json"]),
        "full": json.loads(row["full_json"]),
        "unlocked": bool(row["unlocked"]),
    }


def seo():
    return {
        "title": "Why isn’t my business showing up on Google Maps?",
        "description": (
            "Live listing but missing from Google Maps? See the public gaps. HVAC and plumbing shops only. "
            "Free teaser. Full report $197. We don’t unsuspend listings and we don’t take over your profile."
        ),
    }


WHAT_IS_FAQS = [
    {
        "q": "What is Map Gap?",
        "a": (
            "Map Gap at map-gap.onrender.com is a one-time Map Pack report for US HVAC and plumbing shops: "
            "free teaser of three public gaps, full report $197. You keep the listing. We do not take ownership, "
            "promise #1, or unsuspend Google listings."
        ),
    },
    {
        "q": "Is Map Gap the same as mapgaps.com?",
        "a": (
            "No. mapgaps.com is a different product. This Map Gap is only local Google Maps gaps "
            "for HVAC and plumbing."
        ),
    },
    {
        "q": "Is this MAPGAPS protein software?",
        "a": (
            "No. Bioinformatics MAPGAPS is a different product. This Map Gap is only local Google Maps gaps "
            "for HVAC and plumbing."
        ),
    },
    {
        "q": "How much?",
        "a": (
            "Free teaser of three public gaps. Full report $197. Optional listing rebuild $397 after you have "
            "the report. No monthly plan on this site."
        ),
    },
    {
        "q": "Do you take over the listing?",
        "a": "No. You keep the listing. We do not take ownership.",
    },
    {
        "q": "Do you guarantee rankings?",
        "a": "No. We do not promise #1 on Google or guarantee the map pack.",
    },
    {
        "q": "Can you unsuspend a Google listing?",
        "a": "No. A suspension is an appeal to Google. Don’t pay $197 for that.",
    },
    {
        "q": "Is this for any local business?",
        "a": "No. HVAC and plumbing only.",
    },
]


def faq_page_json_ld(faqs: list[dict]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": item["q"],
                "acceptedAnswer": {"@type": "Answer", "text": item["a"]},
            }
            for item in faqs
        ],
    }


@app.context_processor
def inject_globals():
    return {
        "price": PRICE,
        "payment_connected": payment_connected(),
        "stripe_rebuild_url": (os.environ.get("STRIPE_REBUILD_PAYMENT_LINK_URL") or "").strip(),
        "seo": seo(),
        "unknown": UNKNOWN,
    }


@app.get("/")
def landing():
    return render_template("landing.html")


@app.get("/google-business-profile-suspended")
def page_suspended():
    return render_template("inbound_suspended.html")


@app.get("/why-did-my-google-business-listing-disappear")
def page_disappear():
    return render_template("inbound_disappear.html")


@app.get("/google-business-hours-wrong")
def page_hours():
    return render_template("inbound_hours.html")


@app.get("/google-business-profile-audit-free")
def page_audit_free():
    return render_template("inbound_audit_free.html")


@app.get("/legal")
def legal():
    return render_template("legal.html")


@app.get("/what-is-map-gap")
def page_what_is():
    return render_template(
        "what_is_map_gap.html",
        faqs=WHAT_IS_FAQS,
        faq_ld=faq_page_json_ld(WHAT_IS_FAQS),
    )


@app.post("/lookup")
def lookup_post():
    name = (request.form.get("name") or "").strip()
    city = (request.form.get("city") or "").strip()
    listing_url = (request.form.get("listing_url") or "").strip()
    q = (request.form.get("q") or "").strip()
    if q:
        ql = q.lower()
        if ql.startswith(("http://", "https://")) or "maps.google." in ql or "goo.gl" in ql or "g.page" in ql:
            listing_url = q if ql.startswith(("http://", "https://")) else "https://" + q.lstrip("/")
        elif "," in q:
            name, city = [part.strip() for part in q.split(",", 1)]
        else:
            name = q
    if listing_url and not listing_url.lower().startswith(("http://", "https://")):
        listing_url = "https://" + listing_url
    if not listing_url and not name:
        return (
            render_template(
                "landing.html",
                form_error="Enter a business name and city, or paste a Google listing URL.",
                form={"q": q, "name": name, "city": city, "listing_url": listing_url},
            ),
            400,
        )
    lookup = run_lookup(name, city, listing_url)
    built = build_reports(lookup)
    rid = save_report(lookup, built)
    return redirect(url_for("teaser", rid=rid))


@app.get("/r/<rid>")
@app.get("/teaser/<rid>")
def teaser(rid: str):
    rec = load_report(rid)
    if not rec:
        abort(404)
    show_full = is_unlocked(rec)
    pay_href = None
    pay_label = "Payment not connected yet"
    if payment_connected():
        base = stripe_url()
        sep = "&" if "?" in base else "?"
        pay_href = f"{base}{sep}{urlencode({'client_reference_id': rec['id']})}"
        pay_label = f"Pay ${PRICE}"
    raw = (rec.get("lookup") or {}).get("raw") or {}
    thin = bool(raw.get("thin"))
    vertical_ok = raw.get("vertical_ok", True)
    if vertical_ok is None:
        vertical_ok = True
    bullets = raw.get("bullets") or []
    # Hide $197 unlock when public data is thin (no competitors / no map presence).
    show_paywall = (not show_full) and (not thin) and bool(raw.get("unlock")) and vertical_ok
    return render_template(
        "teaser_v1b.html",
        rec=rec,
        teaser=rec["teaser"],
        full=rec["full"] if show_full else None,
        show_full=show_full,
        pay_href=pay_href,
        pay_label=pay_label,
        thin=thin,
        thin_reason=raw.get("thin_reason") or "",
        vertical_ok=True if rec["teaser"].get("found") else vertical_ok,
        bullets=bullets,
        show_paywall=show_paywall,
    )


def is_unlocked(rec: dict) -> bool:
    if rec.get("unlocked"):
        return True
    key = operator_key()
    q = (request.args.get("key") or "").strip()
    if key and q and secrets.compare_digest(q, key):
        return True
    return False


@app.get("/pay")
@app.get("/pay/<rid>")
def pay(rid: str | None = None):
    rid = rid or (request.args.get("report") or "").strip()
    rec = load_report(rid) if rid else None
    pay_href = None
    if payment_connected() and rec:
        base = stripe_url()
        sep = "&" if "?" in base else "?"
        pay_href = f"{base}{sep}{urlencode({'client_reference_id': rec['id']})}"
    elif payment_connected():
        pay_href = stripe_url()
    return render_template("pay.html", rec=rec, pay_href=pay_href, data=(rec or {}).get("lookup", {}).get("raw") if rec else None)


@app.get("/thanks")
def thanks():
    rid = (request.args.get("report") or request.args.get("tid") or "").strip()
    return render_template("thanks.html", rid=rid, payment_connected=payment_connected())


@app.get("/health")
def health():
    return {"ok": True, "payment_connected": payment_connected(), "price": PRICE}


@app.get("/robots.txt")
def robots():
    return "User-agent: *\nAllow: /\n", 200, {"Content-Type": "text/plain"}


def main():
    host = os.environ.get("MAPGAP_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT") or os.environ.get("MAPGAP_PORT", "8787"))
    print(f"Map Gap → http://127.0.0.1:{port}/")
    print("Payment:", "connected" if payment_connected() else "not connected (STRIPE_PAYMENT_LINK_URL unset)")
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
