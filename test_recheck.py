"""Site-audit recheck: durable result links, copy, contrast, and chrome."""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import app as appmod
from result_link import pack_link, unpack_link, view_from_lookup

ROOT = Path(__file__).resolve().parent


def _contrast(a: str, b: str) -> float:
    def lin(channel: int) -> float:
        c = channel / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def lum(hex_color: str) -> float:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _fake_lookup():
    return {
        "queried_at": "Sep 29, 2026, 4:10 PM ET",
        "input": {"name": "Summit Heating", "city": "Columbus", "listing_url": "UNKNOWN"},
        "retry_q": "Summit Heating, Columbus",
        "maps_url": "https://maps.google.com/example",
        "found": True,
        "listing": {
            "name": "Summit Heating",
            "address": "10 Main St",
            "city": "Columbus",
            "state": "OH",
            "phone": "(614) 555-0100",
            "website": "https://example.com",
            "hours": "Mon–Fri 8 AM–5 PM",
            "category": "HVAC contractor",
            "rating": None,
            "review_count": None,
            "review_source": None,
            "service_area": False,
        },
        "sources": [],
        "nearby": [],
        "raw": {
            "thin": False,
            "thin_reason": "",
            "vertical_ok": True,
            "missing_fields": [],
            "bullets": [
                {"title": "Categories", "body": "They list a category you do not."},
                {"title": "Reviews", "body": "How fast new reviews come in was not on the page."},
                {"title": "Posts", "body": "No post count was on the page."},
            ],
            "city_source": "input",
            "unlock": True,
        },
    }


class DurableLinkTests(unittest.TestCase):
    def setUp(self):
        self.client = appmod.app.test_client()

    def test_signed_link_roundtrip_and_survives_sqlite_wipe(self):
        lookup = _fake_lookup()
        with patch.object(appmod, "run_lookup", return_value=lookup):
            res = self.client.post("/lookup", data={"q": "Summit Heating, Columbus"}, follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        loc = res.headers["Location"]
        token = loc.rstrip("/").split("/")[-1]
        self.assertLess(len(token), 7000)
        view = unpack_link(token)
        self.assertIsNotNone(view)
        self.assertEqual(view["retry_q"], "Summit Heating, Columbus")
        self.assertTrue(view["raw"]["unlock"])

        with sqlite3.connect(appmod.DB_PATH) as conn:
            conn.execute("DELETE FROM reports")
            conn.commit()

        page = self.client.get(loc)
        html = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn("Summit Heating", html)
        self.assertIn("Columbus", html)
        self.assertIn("Competitor report — $195", html)
        self.assertNotIn("schema.org", html)
        self.assertEqual(html.count("You keep the listing. No ranking is guaranteed."), 1)

        thin = _fake_lookup()
        thin["raw"]["thin"] = True
        thin["raw"]["unlock"] = False
        thin["listing"]["service_area"] = True
        thin["listing"]["address"] = None
        with patch.object(appmod, "run_lookup", return_value=thin):
            again = self.client.post("/lookup", data={"q": "Summit Heating, Columbus"}, follow_redirects=False)
        with sqlite3.connect(appmod.DB_PATH) as conn:
            conn.execute("DELETE FROM reports")
            conn.commit()
        thin_page = self.client.get(again.headers["Location"])
        thin_html = thin_page.get_data(as_text=True)
        self.assertEqual(thin_page.status_code, 200)
        self.assertIn('value="Summit Heating, Columbus"', thin_html)
        self.assertIn("Service-area listing, no street address shown", thin_html)
        self.assertIn("No street address on the public listing", thin_html)

    def test_missing_and_tampered_links_are_a_friendly_page(self):
        missing = self.client.get("/teaser/doesnotexist")
        html = missing.get_data(as_text=True)
        self.assertEqual(missing.status_code, 404)
        self.assertIn("This check expired. Run it again (free, about a minute).", html)
        self.assertIn("Name, City or Maps link", html)

        prefilled = self.client.get("/teaser/doesnotexist?q=Summit+Heating%2C+Columbus")
        self.assertIn('value="Summit Heating, Columbus"', prefilled.get_data(as_text=True))

        token = pack_link(view_from_lookup(_fake_lookup(), "abc123"))
        body, sig = token.split(".")[1:]
        flipped = ("A" if body[0] != "A" else "B") + body[1:]
        bad = self.client.get(f"/teaser/v1.{flipped}.{sig}")
        self.assertEqual(bad.status_code, 404)
        self.assertIn("This check expired. Run it again (free, about a minute).", bad.get_data(as_text=True))

    def test_pay_page_names_the_paid_tier(self):
        res = self.client.get("/pay")
        html = res.get_data(as_text=True)
        self.assertIn("Competitor report — $195", html)
        self.assertNotIn("Full check", html)
        self.assertIn(
            "If the report doesn't find anything useful, reply to your receipt email for a full refund.",
            html,
        )
        self.assertNotIn("chat support", html.lower())
        self.assertNotIn("phone support", html.lower())
        self.assertEqual(html.count("You keep the listing. No ranking is guaranteed."), 1)


class ChromeTests(unittest.TestCase):
    def setUp(self):
        self.client = appmod.app.test_client()

    def test_favicon_and_open_graph(self):
        home = self.client.get("/")
        html = home.get_data(as_text=True)
        self.assertIn('rel="icon"', html)
        self.assertIn("og:image", html)
        self.assertIn("og:title", html)
        self.assertIn("og:description", html)
        self.assertIn("favicon.svg", html)
        self.assertEqual(self.client.get("/favicon.ico").status_code, 200)
        self.assertEqual(self.client.get("/static/og.png").status_code, 200)
        self.assertGreater(ROOT.joinpath("static/og.png").stat().st_size, 1000)

    def test_contrast_timing_and_brand_chip(self):
        css = (ROOT / "static/style.css").read_text(encoding="utf-8")
        self.assertIn("--gap: #be5925;", css)
        self.assertIn("#6f675a", css)
        self.assertGreaterEqual(_contrast("#6f675a", "#ffffff"), 4.5)
        self.assertIn("#5c5348", css)
        self.assertGreaterEqual(_contrast("#5c5348", "#ffffff"), 3.0)
        gap_rule = css.split(".brand-gap")[1].split("}")[0]
        self.assertIn("#d7b15e", gap_rule)
        self.assertNotIn("#be5925", gap_rule)
        self.assertNotIn("var(--gap)", gap_rule)
        self.assertIn("min-height: 44px", css)
        script = (ROOT / "static/lookup.js").read_text(encoding="utf-8")
        self.assertIn("usually under a minute", script)
        self.assertNotIn("5–20", script)
        home = self.client.get("/").get_data(as_text=True)
        self.assertIn("Usually under a minute", home)
        self.assertNotIn("In about a minute", home)

    def test_subpages_say_checkup_and_trust_line_once(self):
        for path in (
            "/what-is-map-gap",
            "/legal",
            "/pay",
            "/google-business-profile-audit-free",
            "/google-business-profile-suspended",
            "/why-did-my-google-business-listing-disappear",
            "/google-business-hours-wrong",
        ):
            html = self.client.get(path).get_data(as_text=True)
            self.assertEqual(html.count("You keep the listing. No ranking is guaranteed."), 1, path)
            self.assertNotIn("Full check", html, path)
            self.assertNotIn(">audit<", html.lower(), path)
        checkup = self.client.get("/google-business-profile-audit-free").get_data(as_text=True)
        self.assertIn("Free Google Business Profile checkup", checkup)
        self.assertNotIn("gbpcentral", checkup)
        self.assertNotIn("Scout", checkup)


if __name__ == "__main__":
    unittest.main()
