"""Service-area listings: no street address, name + city fallback, empty-state page."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import app as appmod
import lookup
from lookup import parse_input, run_lookup
from report import build_reports

RODAN_URL = (
    "https://www.google.com/maps/place/Rodan+Heating+and+Air/@34.2087835,-118.9084397,10z/data="
    "!3m1!4b1!4m6!3m5!1s0x45efefb853272fd3:0x665e2d2f38edec94!8m2!3d34.2087835!4d-118.9084396"
    "!16s%2Fg%2F11nvvrtkqc"
)

PREVIEW_SAB = [
    [
        [
            "https://www.gstatic.com/images/icons/material/system_gm/2x/storefront_googblue_24dp.png",
            "Rodan Heating and Air",
        ]
    ],
    [
        [
            "https://www.gstatic.com/images/icons/material/system_gm/2x/category_googblue_24dp.png",
            "HVAC contractor",
        ]
    ],
    [
        [
            "https://www.gstatic.com/images/icons/material/system_gm/2x/call_googblue_24dp.png",
            "(805) 910-6968",
        ]
    ],
    [
        [
            "https://www.gstatic.com/images/icons/material/system_gm/2x/public_googblue_24dp.png",
            "https://rodanheatingandair.com/",
        ]
    ],
    ["Tuesday", 2, [2026, 9, 29], [["8 AM–6 PM", [[8], [18]]]]],
    ["Wednesday", 3, [2026, 9, 30], [["8 AM–6 PM", [[8], [18]]]]],
    ["Thursday", 4, [2026, 10, 1], [["8 AM–6 PM", [[8], [18]]]]],
    ["Friday", 5, [2026, 10, 2], [["8 AM–6 PM", [[8], [18]]]]],
    ["Saturday", 6, [2026, 10, 3], [["Closed"]]],
    ["Sunday", 7, [2026, 10, 4], [["Closed"]]],
    ["Monday", 1, [2026, 10, 5], [["8 AM–6 PM", [[8], [18]]]]],
    [None, None, 34.2087835, -118.9084396],
]

WEBSITE_HTML = """
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "HomeAndConstructionBusiness",
  "name": "Rodan Heating and Air Conditioning",
  "telephone": "(805) 383-3588",
  "address": {
    "@type": "PostalAddress",
    "addressLocality": "Camarillo",
    "addressRegion": "CA",
    "addressCountry": "US"
  }
}
</script>
"""


def _osm(name, city, street=False, osm_type="hvac"):
    address = {"city": city, "state": "California", "country_code": "us", "postcode": "93010"}
    if street:
        address["house_number"] = "100"
        address["road"] = "Main Street"
    return {
        "name": name,
        "display_name": f"{name}, {city}, California, United States",
        "type": osm_type,
        "category": "craft",
        "osm_type": "node",
        "osm_id": 1,
        "lat": "34.21",
        "lon": "-119.03",
        "address": address,
        "extratags": {},
    }


class ParseTests(unittest.TestCase):
    def test_place_url_has_name_and_pin_but_no_city(self):
        parsed = parse_input(RODAN_URL)
        self.assertEqual(parsed["name"], "Rodan Heating and Air")
        self.assertEqual(parsed["city"], "")
        self.assertTrue(parsed["lat"].startswith("34.2087835"))
        self.assertTrue(parsed["lon"].startswith("-118.9084396"))

    def test_preview_marks_service_area_when_address_row_missing(self):
        body = ")]}'\n" + json.dumps(PREVIEW_SAB)
        parsed = lookup._parse_preview_place(body)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["name"], "Rodan Heating and Air")
        self.assertEqual(parsed["category"], "HVAC contractor")
        self.assertEqual(parsed["phone"], "(805) 910-6968")
        self.assertTrue(parsed["service_area"])
        self.assertIsNone(parsed["address"])
        self.assertIn("Mon–Fri", parsed["hours"])
        self.assertIn("Closed", parsed["hours"])

    def test_preview_keeps_a_street_when_the_listing_shows_one(self):
        payload = PREVIEW_SAB + [
            [
                [
                    "https://www.gstatic.com/images/icons/material/system_gm/2x/location_on_googblue_24dp.png",
                    "100 Main St, Camarillo, CA 93010",
                ]
            ]
        ]
        parsed = lookup._parse_preview_place(json.dumps(payload))
        self.assertFalse(parsed["service_area"])
        self.assertIn("Main St", parsed["address"])
        city, state = lookup._city_state_from_address(parsed["address"])
        self.assertEqual(city, "Camarillo")
        self.assertEqual(state, "CA")


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.sleep = patch("lookup.time.sleep").start()
        self.addCleanup(patch.stopall)

    def test_url_without_city_falls_back_to_name_and_city(self):
        calls = []

        def nominatim(params):
            q = params.get("q") or ""
            calls.append(q)
            if q.startswith("Rodan Heating and Air Camarillo"):
                return [_osm("Rodan Heating and Air", "Camarillo", street=False)]
            if q.startswith("plumber Camarillo") or q.startswith("hvac Camarillo"):
                return [
                    _osm("Harbor Plumbing", "Camarillo", street=True, osm_type="plumber"),
                    _osm("Conejo Heating", "Camarillo", street=False, osm_type="hvac"),
                    _osm("Ventura Air", "Camarillo", street=True, osm_type="hvac"),
                ]
            return []

        google = {
            "fetched": True,
            "preview": True,
            "final_url": RODAN_URL,
            "name": "Rodan Heating and Air",
            "category": "HVAC contractor",
            "phone": "(805) 910-6968",
            "website": "https://rodanheatingandair.com/",
            "hours": "Mon–Fri 8 AM–6 PM",
            "address": None,
            "service_area": True,
            "lat": 34.2087835,
            "lon": -118.9084396,
            "review_count_total": None,
            "rating": None,
            "note": "preview",
        }
        with patch("lookup._nominatim", side_effect=nominatim), patch(
            "lookup._google_enrich", return_value=google
        ), patch(
            "lookup._website_identity",
            return_value={"ok": True, "name": "Rodan Heating and Air Conditioning", "city": "Camarillo", "state": "CA", "street": "", "phone": "", "review_count": 150},
        ), patch("lookup._get", return_value=(0, "", "")):
            data = lookup.lookup(RODAN_URL)
            built = run_lookup("", "", RODAN_URL)

        self.assertIn("fallback_name_city", data["trace"])
        self.assertEqual(data["city_source"], "website_schema")
        self.assertEqual(data["subject"]["city"], "Camarillo")
        self.assertTrue(data["subject"]["service_area"])
        self.assertFalse(data["subject"]["address"])
        self.assertEqual(data["thin_code"], "ok")
        self.assertTrue(any(c.startswith("Rodan Heating and Air Camarillo") for c in calls))
        self.assertEqual(built["listing"]["name"], "Rodan Heating and Air")
        self.assertEqual(built["listing"]["city"], "Camarillo")
        self.assertIsNone(built["listing"]["address"])
        self.assertTrue(built["listing"]["service_area"])
        self.assertEqual(built["retry_q"], "Rodan Heating and Air, Camarillo")
        self.assertIsNone(built["listing"]["review_count"])
        teaser = build_reports(built)["teaser"]
        self.assertEqual(teaser["display_name"], "Rodan Heating and Air")

    def test_hidden_street_is_not_copied_from_osm(self):
        def nominatim(params):
            q = params.get("q") or ""
            if "Rodan" in q:
                return [_osm("Rodan Heating and Air", "Camarillo", street=True)]
            return []

        google = {
            "fetched": True,
            "preview": True,
            "final_url": RODAN_URL,
            "name": "Rodan Heating and Air",
            "category": "HVAC contractor",
            "phone": None,
            "website": None,
            "hours": None,
            "address": None,
            "service_area": True,
            "review_count_total": None,
            "rating": None,
            "note": "preview",
        }
        with patch("lookup._nominatim", side_effect=nominatim), patch(
            "lookup._google_enrich", return_value=google
        ), patch(
            "lookup._website_identity",
            return_value={"ok": True, "name": "Rodan Heating and Air", "city": "Camarillo", "state": "CA", "street": "9 Hidden Ln", "phone": "", "review_count": None},
        ), patch("lookup._reverse_locality", return_value={"city": "Thousand Oaks", "state": "California", "country_code": "us"}):
            data = lookup.lookup(RODAN_URL)
        self.assertEqual(data["subject"]["address"], "")
        self.assertNotIn("Hidden", json.dumps(data["subject"]))
        self.assertNotIn("Main Street", data["subject"]["address"])

    def test_unreadable_url_keeps_the_parsed_name(self):
        with patch("lookup._nominatim", return_value=[]), patch(
            "lookup._google_enrich",
            return_value={"fetched": False, "preview": False, "final_url": RODAN_URL, "name": None, "note": "blocked", "service_area": None, "review_count_total": None},
        ), patch("lookup._reverse_locality", return_value={"city": "", "state": "", "country_code": ""}):
            built = run_lookup("", "", RODAN_URL)
        self.assertEqual(built["listing"]["name"], "Rodan Heating and Air")
        self.assertEqual(built["raw"]["thin_code"], "no_competitors")
        self.assertIn("review count", built["raw"]["missing_fields"])
        self.assertIn("Rodan Heating and Air", built["retry_q"])

    def test_zip_fills_city_when_the_pin_is_outside_a_city(self):
        def nominatim(params):
            if params.get("postalcode") == "93010":
                return [{
                    "name": "93010",
                    "display_name": "93010, Camarillo, California, United States",
                    "address": {"town": "Camarillo", "state": "California", "country_code": "us", "postcode": "93010"},
                }]
            return []

        google = {
            "fetched": True,
            "preview": True,
            "final_url": RODAN_URL,
            "name": "Rodan Heating and Air",
            "category": "HVAC contractor",
            "phone": "(805) 910-6968",
            "website": None,
            "hours": None,
            "address": None,
            "service_area": True,
            "review_count_total": None,
            "rating": None,
            "note": "preview",
        }
        with patch("lookup._nominatim", side_effect=nominatim), patch(
            "lookup._google_enrich", return_value=google
        ), patch(
            "lookup._reverse_locality",
            return_value={"city": "", "state": "California", "country_code": "us", "postcode": "93010"},
        ):
            data = lookup.lookup(RODAN_URL)
        self.assertEqual(data["city_source"], "postcode")
        self.assertIn("city_from_postcode", data["trace"])
        self.assertEqual(data["subject"]["city"], "Camarillo")
        self.assertEqual(data["subject"]["address"], "")

    def test_gibberish_url_has_no_name(self):
        with patch("lookup._nominatim", return_value=[]), patch(
            "lookup._google_enrich",
            return_value={"fetched": False, "preview": False, "final_url": "https://maps.google.com/not-a-place", "name": None, "note": "blocked", "service_area": None, "review_count_total": None},
        ):
            data = lookup.lookup("https://maps.google.com/not-a-place")
        self.assertIsNone(data["subject"])
        self.assertEqual(data["thin_code"], "url_unparsed")


class PageTests(unittest.TestCase):
    def setUp(self):
        self.client = appmod.app.test_client()

    def test_empty_state_names_the_listing_and_check_again(self):
        captured = {}

        def fake_run(name, city, listing_url):
            captured["args"] = (name, city, listing_url)
            raw = {
                "thin": True,
                "thin_code": "no_competitors",
                "thin_reason": "not enough",
                "vertical_ok": True,
                "missing_fields": ["review count", "other shops to compare"],
                "subject": {"name": "Rodan Heating and Air", "service_area": True, "state": "CA"},
                "bullets": [],
                "input": {"name": "Rodan Heating and Air", "city": "Camarillo"},
            }
            return {
                "queried_at": "Sep 29, 2026, 3:25 PM ET",
                "input": {
                    "name": "Rodan Heating and Air",
                    "city": "Camarillo",
                    "listing_url": RODAN_URL,
                },
                "retry_q": "Rodan Heating and Air, Camarillo",
                "maps_url": RODAN_URL,
                "found": True,
                "listing": {
                    "name": "Rodan Heating and Air",
                    "address": None,
                    "city": "Camarillo",
                    "state": "CA",
                    "postcode": None,
                    "phone": "(805) 910-6968",
                    "website": "https://rodanheatingandair.com/",
                    "hours": "Mon–Fri 8 AM–6 PM",
                    "category": "HVAC contractor",
                    "lat": None,
                    "lon": None,
                    "osm_url": None,
                    "rating": None,
                    "review_count": None,
                    "review_source": None,
                    "same_as": [],
                    "service_area": True,
                    "_origin": {},
                },
                "sources": [],
                "nearby": [],
                "raw": raw,
            }

        with patch.object(appmod, "run_lookup", side_effect=fake_run):
            res = self.client.post("/lookup", data={"q": RODAN_URL}, follow_redirects=True)
        html = res.get_data(as_text=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn("We couldn't read enough of Rodan Heating and Air's public listing", html)
        self.assertNotIn("Three public reasons you lose the map pack", html)
        self.assertIn("Camarillo, CA", html)
        self.assertIn("HVAC contractor", html)
        self.assertIn("review count and other shops to compare", html)
        self.assertIn("Service-area listing, no street address shown", html)
        self.assertIn('value="Rodan Heating and Air, Camarillo"', html)
        self.assertIn("Check again", html)
        self.assertIn("result-lead", html)
        self.assertNotIn('class="card banner unk"', html)
        self.assertIn("No street address on the public listing", html)
        self.assertIn("lookup.js", html)

    def test_not_found_does_not_use_the_three_reasons_headline(self):
        def fake_run(name, city, listing_url):
            return {
                "queried_at": "Sep 29, 2026, 3:25 PM ET",
                "input": {"name": "UNKNOWN", "city": "UNKNOWN", "listing_url": listing_url},
                "retry_q": listing_url,
                "maps_url": listing_url,
                "found": False,
                "listing": {
                    "name": None,
                    "address": None,
                    "city": None,
                    "state": None,
                    "phone": None,
                    "website": None,
                    "hours": None,
                    "category": None,
                    "service_area": False,
                    "rating": None,
                    "review_count": None,
                    "review_source": None,
                },
                "sources": [],
                "nearby": [],
                "raw": {
                    "thin": True,
                    "thin_code": "url_unparsed",
                    "vertical_ok": True,
                    "missing_fields": ["business name"],
                    "subject": None,
                    "bullets": [],
                },
            }

        with patch.object(appmod, "run_lookup", side_effect=fake_run):
            res = self.client.post("/lookup", data={"q": "https://maps.google.com/nope"}, follow_redirects=True)
        html = res.get_data(as_text=True)
        self.assertIn("We couldn't find that listing.", html)
        self.assertNotIn("Three public reasons", html)
        self.assertIn("Check again", html)

    def test_homepage_submit_includes_loading_script(self):
        res = self.client.get("/")
        html = res.get_data(as_text=True)
        self.assertIn("lookup.js", html)
        script = (appmod.ROOT / "static" / "lookup.js").read_text()
        self.assertIn("Checking your public listing…", script)
        self.assertIn("form.dataset.submitted", script)
        css = (appmod.ROOT / "static" / "style.css").read_text()
        self.assertIn(".result-lead", css)
        self.assertIn("font-size: 22px", css)
        self.assertIn("var(--ui)", css.split(".result-lead")[1][:200])


if __name__ == "__main__":
    unittest.main()
