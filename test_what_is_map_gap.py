"""Name-ownership page: URL, copy, pricing, and FAQPage JSON-LD."""

from __future__ import annotations

import json
import re
import unittest

from app import app


class WhatIsMapGapTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_page_exists_with_approved_copy(self):
        res = self.client.get("/what-is-map-gap")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn(
            "Map Gap — Google Maps audit for HVAC and plumbing (not mapgaps.com)",
            html,
        )
        self.assertIn(
            "Map Gap at map-gap.onrender.com is an HVAC and plumbing Google Maps audit — not mapgaps.com.",
            html,
        )
        self.assertIn("free teaser of three public gaps, full report $197", html)
        self.assertIn("You keep the listing", html)
        self.assertIn("mapgaps.com or bioinformatics MAPGAPS", html)
        self.assertIn("What Map Gap is", html)
        self.assertIn("Who it’s for / not for", html)
        self.assertIn("Not the other MapGaps", html)
        self.assertIn("Optional Listing Rebuild: $397", html)
        self.assertIn("No monthly plan on this site", html)
        self.assertIn("Run free teaser on homepage", html)
        self.assertIn('href="/#lookup"', html)
        self.assertNotIn("/pricing", html)
        self.assertNotRegex(html, r"guarantee(?:s|d)? (?:you )?#1")

    def test_faqpage_json_ld(self):
        res = self.client.get("/what-is-map-gap")
        html = res.get_data(as_text=True)
        match = re.search(
            r'<script type="application/ld\+json">(.*?)</script>',
            html,
            re.S,
        )
        self.assertIsNotNone(match)
        data = json.loads(match.group(1))
        self.assertEqual(data["@type"], "FAQPage")
        names = [item["name"] for item in data["mainEntity"]]
        self.assertEqual(
            names,
            [
                "What is Map Gap?",
                "Is Map Gap the same as mapgaps.com?",
                "Is this MAPGAPS protein software?",
                "How much?",
                "Do you take over the listing?",
                "Do you guarantee rankings?",
                "Can you unsuspend a Google listing?",
                "Is this for any local business?",
            ],
        )
        answers = " ".join(item["acceptedAnswer"]["text"] for item in data["mainEntity"])
        self.assertIn("No. mapgaps.com is a different product", answers)
        self.assertIn("No. Bioinformatics MAPGAPS is a different product", answers)
        self.assertIn("$197", answers)
        self.assertIn("$397", answers)
        self.assertIn("HVAC and plumbing only", answers)

    def test_homepage_cross_links(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Why isn’t my business showing up on Google Maps?", html)
        self.assertIn(
            "Map Gap (map-gap.onrender.com) — HVAC &amp; plumbing Google Maps audit. Not mapgaps.com.",
            html,
        )
        self.assertIn("Is Map Gap the same as mapgaps.com?", html)
        self.assertIn('href="/what-is-map-gap"', html)
        self.assertIn("Show me why I’m not showing", html)

    def test_no_pricing_route(self):
        self.assertEqual(self.client.get("/pricing").status_code, 404)


if __name__ == "__main__":
    unittest.main()
