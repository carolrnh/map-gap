"""Name-ownership page and homepage copy: URL, pricing, and FAQPage JSON-LD."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from app import app


class WhatIsMapGapTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_page_exists_with_approved_copy(self):
        res = self.client.get("/what-is-map-gap")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn(
            "Map Gap — Google Maps checkup for HVAC and plumbing (not mapgaps.com)",
            html,
        )
        self.assertIn(
            "Map Gap at map-gap.onrender.com is an HVAC and plumbing Google Maps checkup — not mapgaps.com.",
            html,
        )
        self.assertIn("a free check of 3 things the shops above you have, and a $195 competitor report", html)
        self.assertNotIn("audit", html.lower())
        self.assertIn("You keep the listing", html)
        self.assertIn("mapgaps.com or bioinformatics MAPGAPS", html)
        self.assertIn("What Map Gap is", html)
        self.assertIn("Who it’s for / not for", html)
        self.assertIn("Not the other MapGaps", html)
        self.assertIn("Listing rebuild — $397", html)
        self.assertIn("There is no monthly plan on this site.", html)
        self.assertIn("Show my 3 free gaps", html)
        self.assertIn('href="/#lookup"', html)
        self.assertNotIn("/pricing", html)
        self.assertNotIn("$197", html)
        self.assertNotRegex(html, r"guarantee(?:s|d)? (?:you )?#1")
        source = Path("templates/what_is_map_gap.html").read_text(encoding="utf-8")
        self.assertIn("TODO: Carol will add a sample report", source)

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
        self.assertIn("mapgaps.com is a different product", answers)
        self.assertIn("Bioinformatics MAPGAPS is a different product", answers)
        self.assertIn("$195", answers)
        self.assertIn("$397", answers)
        self.assertNotIn("$197", answers)
        self.assertIn("HVAC and plumbing", answers)

    def test_homepage_cross_links(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Why isn’t my HVAC or plumbing shop showing up on Google Maps?", html)
        self.assertIn("Google Maps checkup for HVAC &amp; plumbing shops", html)
        self.assertNotIn("Not mapgaps.com", html)
        self.assertNotIn("mapgaps.com", html)
        self.assertIn('href="/what-is-map-gap"', html)
        self.assertIn("Show my 3 free gaps", html)
        self.assertIn("Free check", html)
        self.assertIn("Competitor report — $195", html)
        self.assertNotIn("Full check", html)
        self.assertIn("Listing rebuild — $397", html)
        self.assertIn("In under a minute you’ll see", html)
        self.assertEqual(
            html.count("If the report doesn’t find anything useful, reply to your receipt email for a full refund."),
            1,
        )
        self.assertIn("Name, City or Maps link", html)
        self.assertIn(
            "If the report doesn’t find anything useful, reply to your receipt email for a full refund.",
            html,
        )
        self.assertEqual(html.count("You keep the listing. No ranking is guaranteed."), 1)
        self.assertNotIn("$197", html)
        self.assertNotIn("Don’t pay", html)
        self.assertNotIn("teaser", html.lower())
        self.assertNotIn("map pack", html.lower())
        self.assertNotIn("public gaps", html.lower())
        self.assertIn("You keep the listing. No ranking is guaranteed.", html)
        self.assertNotIn("For HVAC and plumbing shops only.", html)
        landing = Path("templates/landing.html").read_text(encoding="utf-8")
        self.assertIn("TODO: Carol will add a sample report", landing)
        self.assertIn(">Sample<", html)
        self.assertIn("Example Heating &amp; Air", html)
        self.assertIn("Fictional shop. A free check reads like this.", html)
        self.assertLess(html.find("Suspension is Google’s appeal"), html.find(">Sample<"))
        self.assertLess(html.find(">Sample<"), html.find('id="pricing"'))
        self.assertEqual(html.count('class="card offer"'), 2)
        self.assertEqual(html.count('class="btn"'), 1)
        self.assertIn('class="btn" type="submit" id="go">Show my 3 free gaps', html)
        self.assertEqual(html.count('class="offer-link"'), 2)
        self.assertNotIn("offer-link btn", html)
        self.assertNotIn('class="btn offer', html)
        from places import select_gaps

        gaps = select_gaps(
            {
                "name": "Example Heating & Air",
                "review_count": 41,
                "rating": 4.2,
                "website": "https://example.test",
                "hours_listed": True,
                "photo_count": 2,
                "category": "General contractor",
                "primary_type": "general_contractor",
                "phone": "(555) 010-0140",
            },
            [
                {
                    "name": "Sample Comfort Co",
                    "review_count": 186,
                    "rating": 4.8,
                    "website": "https://example.com",
                    "hours_listed": True,
                    "photo_count": 10,
                    "category": "HVAC contractor",
                    "primary_type": "hvac_contractor",
                    "phone": "(555) 010-0199",
                },
                {
                    "name": "Sample Plumbing Co",
                    "review_count": 140,
                    "rating": 4.7,
                    "website": "https://example.com",
                    "hours_listed": True,
                    "photo_count": 10,
                    "category": "HVAC contractor",
                    "primary_type": "hvac_contractor",
                    "phone": "(555) 010-0188",
                },
                {
                    "name": "Sample Heating Co",
                    "review_count": 97,
                    "rating": 4.6,
                    "website": "https://example.com",
                    "hours_listed": True,
                    "photo_count": 8,
                    "category": "HVAC contractor",
                    "primary_type": "hvac_contractor",
                    "phone": "(555) 010-0177",
                },
            ],
        )
        self.assertEqual([gap["title"] for gap in gaps], ["Reviews", "Photos", "Category"])
        for gap in gaps:
            self.assertIn(f"<h2>{gap['title']}</h2>", html)
            self.assertIn(gap["body"], html)

    def test_legal_price_and_plain_checkout_sentence(self):
        res = self.client.get("/legal")
        html = res.get_data(as_text=True)
        self.assertIn("$195", html)
        self.assertIn("$397", html)
        self.assertNotIn("$197", html)
        self.assertNotIn("STRIPE_PAYMENT_LINK_URL", html)
        self.assertIn("Payment not connected yet", html)
        self.assertNotIn("on the machine that runs this app", html)
        self.assertIn("The link for your check contains the public result", html)
        self.assertIn(
            "If the report doesn’t find anything useful, reply to your receipt email for a full refund.",
            html,
        )

    def test_cta_orange_meets_contrast_target(self):
        css = Path("static/style.css").read_text(encoding="utf-8")
        self.assertIn("--gap: #be5925;", css)
        self.assertNotIn("#c45c26", css)

    def test_no_pricing_route(self):
        self.assertEqual(self.client.get("/pricing").status_code, 404)


if __name__ == "__main__":
    unittest.main()
