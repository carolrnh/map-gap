"""Places client, gap selection, rate limit, and daily cap. HTTP is mocked."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as appmod
import limits
import lookup
from limits import DAILY_CAP_MESSAGE, DailyCapReached, IpRateLimited
from places import (
    DETAILS_FIELD_MASK,
    SEARCH_ENTERPRISE_MASK,
    SEARCH_IDS_MASK,
    google_places_enabled,
    normalize_place,
    photo_label_for,
    pick_competitors,
    search_text_ids,
    select_gaps,
)
from places_lookup import persistable_record, refetch_places, run_places_lookup

RODAN_URL = (
    "https://www.google.com/maps/place/Rodan+Heating+and+Air/@34.2087835,-118.9084397,10z/data="
    "!3m1!4b1!4m6!3m5!1s0x45efefb853272fd3:0x665e2d2f38edec94"
)
SECRET_SITE = "https://secret-example-places.test/do-not-store"
SECRET_PROVIDER = "DoNotStoreProvider"
SECRET_STREET = "999 Secret Ave, Ventura, CA 93001"
SECRET_REVIEWS = 121212


def _comp(i, reviews=400, photos=10, rating=4.8, primary="hvac_contractor", label="HVAC contractor"):
    return {
        "id": f"ChIJcomp{i}",
        "displayName": {"text": f"Harbor Shop {i}"},
        "primaryType": primary,
        "primaryTypeDisplayName": {"text": label},
        "types": [primary],
        "nationalPhoneNumber": "(805) 555-0199",
        "websiteUri": f"https://comp{i}.example.com",
        "rating": rating,
        "userRatingCount": reviews,
        "regularOpeningHours": {"weekdayDescriptions": ["Monday: 9:00 AM – 5:00 PM"]},
        "photos": [{"name": f"places/x/photos/{i}-{n}"} for n in range(photos)],
        "pureServiceAreaBusiness": False,
        "formattedAddress": "100 Main St, Camarillo, CA 93010",
        "businessStatus": "OPERATIONAL",
    }


def _subject():
    return {
        "id": "ChIJsubject",
        "displayName": {"text": "Rodan Heating and Air"},
        "primaryType": "hvac_contractor",
        "primaryTypeDisplayName": {"text": "HVAC contractor"},
        "types": ["hvac_contractor"],
        "nationalPhoneNumber": "(805) 555-0100",
        "rating": 4.2,
        "userRatingCount": SECRET_REVIEWS,
        "regularOpeningHours": {"weekdayDescriptions": ["Monday: 8:00 AM – 5:00 PM"]},
        "photos": [{"name": "places/x/photos/only"}],
        "pureServiceAreaBusiness": True,
        "formattedAddress": SECRET_STREET,
        "googleMapsUri": "https://maps.google.com/?cid=subject",
        "businessStatus": "OPERATIONAL",
        "websiteUri": SECRET_SITE,
        "attributions": [{"provider": SECRET_PROVIDER, "providerUri": "https://example.com/attr"}],
    }


class FakeHTTP:
    def __init__(self, subject=None, competitors=None, subject_id="ChIJsubject"):
        self.calls = []
        self.subject = subject if subject is not None else _subject()
        self.competitors = competitors if competitors is not None else [_comp(1), _comp(2), _comp(3)]
        self.subject_id = subject_id

    def __call__(self, method, url, headers, body):
        self.calls.append({"method": method, "url": url, "headers": dict(headers), "body": body})
        if "preview/place" in url or "google.com/maps" in url:
            raise AssertionError(f"preview scrape attempted: {url}")
        if "searchText" in url:
            mask = headers.get("X-Goog-FieldMask")
            if mask == SEARCH_IDS_MASK:
                return {"places": [{"id": self.subject_id}]}
            return {"places": self.competitors}
        if method == "GET" and self.subject_id in url:
            return self.subject
        raise AssertionError(f"unexpected places call {method} {url}")


class EnvCase(unittest.TestCase):
    def setUp(self):
        self._env = {
            k: os.environ.get(k)
            for k in (
                "USE_GOOGLE_PLACES",
                "GOOGLE_PLACES_API_KEY",
                "PLACES_DAILY_CAP",
                "PLACES_USAGE_DB",
                "PLACES_IP_LIMIT",
                "PLACES_IP_WINDOW_SECONDS",
            )
        }
        for key in self._env:
            os.environ.pop(key, None)
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["PLACES_USAGE_DB"] = str(Path(self.tmp.name) / "usage.sqlite")
        os.environ["PLACES_DAILY_CAP"] = "30"
        os.environ["GOOGLE_PLACES_API_KEY"] = "test-key-not-real"
        limits.reset_ip_limits()
        appmod.clear_places_cache()

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        limits.reset_ip_limits()
        appmod.clear_places_cache()
        self.tmp.cleanup()


class PlacesClientTests(EnvCase):
    def test_pattern_is_one_id_search_one_details_one_competitor_search(self):
        http = FakeHTTP()
        result = run_places_lookup("Rodan Heating and Air", "Camarillo", "", http=http)
        self.assertEqual(len(http.calls), 3)
        ids_call, details_call, search_call = http.calls
        self.assertEqual(ids_call["method"], "POST")
        self.assertEqual(ids_call["headers"]["X-Goog-FieldMask"], "places.id")
        self.assertEqual(ids_call["headers"]["X-Goog-Api-Key"], "test-key-not-real")
        self.assertNotIn("test-key-not-real", ids_call["url"])
        ids_body = json.loads(ids_call["body"])
        self.assertTrue(ids_body["includePureServiceAreaBusinesses"])
        self.assertEqual(details_call["method"], "GET")
        self.assertIn("/v1/places/ChIJsubject", details_call["url"])
        self.assertEqual(details_call["headers"]["X-Goog-FieldMask"], DETAILS_FIELD_MASK)
        self.assertNotIn("reviews", DETAILS_FIELD_MASK.split(","))
        self.assertEqual(search_call["method"], "POST")
        mask = search_call["headers"]["X-Goog-FieldMask"]
        self.assertEqual(mask, SEARCH_ENTERPRISE_MASK)
        for field in (
            "places.rating",
            "places.userRatingCount",
            "places.websiteUri",
            "places.regularOpeningHours",
            "places.photos",
            "places.primaryType",
            "places.nationalPhoneNumber",
        ):
            self.assertIn(field, mask.split(","))
        self.assertNotIn("places.reviews", mask.split(","))
        body = json.loads(search_call["body"])
        self.assertTrue(body["includePureServiceAreaBusinesses"])
        self.assertEqual(body["pageSize"], 20)
        self.assertEqual(body["textQuery"], "hvac in Camarillo")
        detail_urls = [c["url"] for c in http.calls if c["method"] == "GET"]
        self.assertEqual(detail_urls, ["https://places.googleapis.com/v1/places/ChIJsubject"])
        self.assertEqual(result["subject_place_id"], "ChIJsubject")
        self.assertEqual(result["competitor_place_ids"], ["ChIJcomp1", "ChIJcomp2", "ChIJcomp3"])
        self.assertTrue(result["listing"]["service_area"])
        self.assertFalse(result["listing"]["address"])
        self.assertNotIn(SECRET_STREET, json.dumps(persistable_record(result)))

    def test_maps_url_uses_location_bias_and_does_not_scrape_preview(self):
        http = FakeHTTP()
        with patch("lookup._google_enrich", side_effect=AssertionError("preview scrape")):
            run_places_lookup("", "", RODAN_URL, http=http)
        ids_body = json.loads(http.calls[0]["body"])
        self.assertIn("Rodan Heating and Air", ids_body["textQuery"])
        self.assertEqual(ids_body["locationBias"]["circle"]["center"]["latitude"], 34.2087835)
        self.assertTrue(ids_body["includePureServiceAreaBusinesses"])
        self.assertTrue(all("preview" not in c["url"] for c in http.calls))

    def test_cap_blocks_before_http(self):
        os.environ["PLACES_DAILY_CAP"] = "0"
        http = FakeHTTP()
        with self.assertRaises(DailyCapReached) as caught:
            search_text_ids("hvac in Ventura", api_key="test-key-not-real", http=http)
        self.assertIn("try again tomorrow", str(caught.exception).lower())
        self.assertEqual(http.calls, [])

    def test_refetch_is_details_plus_one_search(self):
        http = FakeHTTP()
        stored = {
            "user_input": {"name": "Rodan Heating and Air", "city": "Camarillo", "listing_url": ""},
            "subject_place_id": "ChIJsubject",
            "competitor_place_ids": ["ChIJcomp2"],
        }
        result = refetch_places(stored, http=http)
        self.assertEqual([c["method"] for c in http.calls], ["GET", "POST"])
        self.assertEqual(result["competitor_place_ids"], ["ChIJcomp2"])
        self.assertEqual(limits.calls_on(), 2)

    def test_flag_off_or_missing_key(self):
        self.assertFalse(google_places_enabled())
        os.environ["USE_GOOGLE_PLACES"] = "true"
        os.environ.pop("GOOGLE_PLACES_API_KEY", None)
        self.assertFalse(google_places_enabled())
        os.environ["GOOGLE_PLACES_API_KEY"] = "test-key-not-real"
        os.environ["USE_GOOGLE_PLACES"] = "false"
        self.assertFalse(google_places_enabled())
        os.environ["USE_GOOGLE_PLACES"] = "true"
        self.assertTrue(google_places_enabled())


class GapTests(unittest.TestCase):
    def test_photo_labels_are_zero_to_nine_or_ten_plus(self):
        self.assertEqual(photo_label_for(0), "0")
        self.assertEqual(photo_label_for(9), "9")
        self.assertEqual(photo_label_for(10), "10+")
        self.assertEqual(normalize_place({"photos": [{}] * 10})["photo_label"], "10+")
        self.assertEqual(normalize_place({"photos": [{}] * 4})["photo_label"], "4")
        self.assertEqual(normalize_place({})["photo_label"], "0")

    def test_picks_three_biggest_and_skips_posts_and_velocity(self):
        subject = {
            "name": "Rodan Heating and Air",
            "review_count": 10,
            "rating": 4.9,
            "website": "",
            "hours_listed": False,
            "photo_count": 1,
            "photo_label": "1",
            "primary_type": "general_contractor",
            "category": "General contractor",
            "phone": "",
        }
        competitors = []
        for i, reviews in enumerate((200, 180, 150), start=1):
            competitors.append(
                {
                    "name": f"Harbor Shop {i}",
                    "review_count": reviews,
                    "rating": 4.2,
                    "website": "https://example.com",
                    "hours_listed": True,
                    "photo_count": 10,
                    "photo_label": "10+",
                    "primary_type": "plumber",
                    "category": "Plumber",
                    "phone": "(805) 555-0199",
                }
            )
        gaps = select_gaps(subject, competitors)
        self.assertEqual([g["kind"] for g in gaps], ["review_count", "website", "photos"])
        self.assertTrue(all(g["kind"] in {
            "review_count", "rating", "website", "hours", "photos", "category", "phone",
        } for g in gaps))
        blob = " ".join(g["title"] + " " + g["body"] for g in gaps)
        self.assertNotIn("Posts", blob)
        self.assertNotIn("velocity", blob.lower())
        self.assertIn("10+", gaps[2]["body"])
        self.assertIn("0–9 or 10+", gaps[2]["body"])
        self.assertIn("200", gaps[0]["body"])

    def test_category_gap_when_it_is_the_only_one(self):
        subject = {
            "name": "Smith Heating",
            "review_count": 80,
            "rating": 4.8,
            "website": "https://smith.example",
            "hours_listed": True,
            "photo_count": 10,
            "primary_type": "general_contractor",
            "category": "General contractor",
            "phone": "(805) 555-0100",
        }
        competitors = [
            {
                "name": "Harbor Shop",
                "review_count": 40,
                "rating": 4.6,
                "website": "https://harbor.example",
                "hours_listed": True,
                "photo_count": 8,
                "primary_type": "hvac_contractor",
                "category": "HVAC contractor",
                "phone": "(805) 555-0199",
            }
        ]
        gaps = select_gaps(subject, competitors)
        self.assertEqual([g["kind"] for g in gaps], ["category"])
        self.assertIn("primary type", gaps[0]["body"].lower())
        self.assertNotIn("Posts", gaps[0]["body"])

    def test_ten_plus_photos_are_not_a_gap_against_ten_plus(self):
        subject = {"photo_count": 10, "review_count": 5, "rating": 5, "website": "x", "hours_listed": True, "phone": "1", "primary_type": "hvac_contractor", "category": "HVAC"}
        comp = {"name": "Other", "photo_count": 10, "review_count": 5, "rating": 5, "website": "y", "hours_listed": True, "phone": "2", "primary_type": "hvac_contractor", "category": "HVAC"}
        self.assertEqual(select_gaps(subject, [comp]), [])

    def test_pick_competitors_skips_subject_and_closed(self):
        rows = [
            {"place_id": "self", "business_status": "OPERATIONAL"},
            {"place_id": "closed", "business_status": "CLOSED_PERMANENTLY"},
            {"place_id": "a", "business_status": "OPERATIONAL"},
            {"place_id": "b", "business_status": "OPERATIONAL"},
        ]
        chosen = pick_competitors(rows, "self", ["b"])
        self.assertEqual([c["place_id"] for c in chosen], ["b"])


class LimitTests(EnvCase):
    def test_ip_limit_is_per_visitor(self):
        os.environ["PLACES_IP_LIMIT"] = "2"
        limits.enforce_lookup_ip("10.0.0.1", now=1000)
        limits.enforce_lookup_ip("10.0.0.1", now=1001)
        with self.assertRaises(IpRateLimited):
            limits.enforce_lookup_ip("10.0.0.1", now=1002)
        limits.enforce_lookup_ip("10.0.0.2", now=1002)
        limits.enforce_lookup_ip("10.0.0.1", now=1000 + 3600)

    def test_daily_cap_and_message(self):
        os.environ["PLACES_DAILY_CAP"] = "2"
        self.assertEqual(limits.reserve_places_call(today="2026-09-29"), 1)
        self.assertEqual(limits.reserve_places_call(today="2026-09-29"), 2)
        with self.assertRaises(DailyCapReached) as caught:
            limits.reserve_places_call(today="2026-09-29")
        self.assertIn("try again tomorrow", str(caught.exception).lower())
        self.assertEqual(str(caught.exception), DAILY_CAP_MESSAGE)
        self.assertEqual(limits.calls_on("2026-09-29"), 2)
        self.assertEqual(limits.reserve_places_call(today="2026-09-30"), 1)
        os.environ.pop("PLACES_DAILY_CAP", None)
        self.assertEqual(limits.places_daily_cap(), 30)

    def test_form_rate_limit_and_flag_off_unchanged(self):
        os.environ["USE_GOOGLE_PLACES"] = "true"
        os.environ["PLACES_IP_LIMIT"] = "1"
        client = appmod.app.test_client()
        calls = {"n": 0}

        def fake(*_a, **_k):
            calls["n"] += 1
            return {
                "queried_at": "Sep 29, 2026, 3:25 PM ET",
                "input": {"name": "Summit Heating", "city": "Columbus", "listing_url": "UNKNOWN"},
                "retry_q": "Summit Heating, Columbus",
                "maps_url": "",
                "found": True,
                "listing": {
                    "name": "Summit Heating",
                    "address": "1 Main",
                    "city": "Columbus",
                    "state": "OH",
                    "phone": None,
                    "website": None,
                    "hours": None,
                    "category": "HVAC",
                    "service_area": False,
                    "rating": None,
                    "review_count": None,
                    "review_source": None,
                },
                "sources": [],
                "nearby": [],
                "raw": {
                    "thin": True,
                    "thin_code": "no_competitors",
                    "vertical_ok": True,
                    "missing_fields": [],
                    "bullets": [],
                    "unlock": False,
                },
            }

        with patch.object(appmod, "run_lookup", side_effect=fake):
            first = client.post("/lookup", data={"q": "Summit Heating, Columbus"})
            second = client.post("/lookup", data={"q": "Summit Heating, Columbus"})
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 429)
        self.assertIn("Too many checks", second.get_data(as_text=True))
        self.assertEqual(calls["n"], 1)

        limits.reset_ip_limits()
        os.environ["USE_GOOGLE_PLACES"] = "false"
        with patch.object(appmod, "run_lookup", side_effect=fake):
            again = client.post("/lookup", data={"q": "Summit Heating, Columbus"})
            more = client.post("/lookup", data={"q": "Summit Heating, Columbus"})
        self.assertEqual(again.status_code, 302)
        self.assertEqual(more.status_code, 302)
        self.assertEqual(calls["n"], 3)

    def test_daily_cap_message_on_the_form(self):
        os.environ["USE_GOOGLE_PLACES"] = "true"
        client = appmod.app.test_client()

        def boom(*_a, **_k):
            raise DailyCapReached()

        with patch.object(appmod, "run_lookup", side_effect=boom):
            res = client.post("/lookup", data={"q": "Summit Heating, Columbus"})
        self.assertEqual(res.status_code, 429)
        self.assertIn("try again tomorrow", res.get_data(as_text=True).lower())


class StorageTests(EnvCase):
    def setUp(self):
        super().setUp()
        self.db = Path(self.tmp.name) / "mapgap.sqlite"
        self._db = patch.object(appmod, "DB_PATH", self.db)
        self._db.start()
        appmod.init_db()
        os.environ["USE_GOOGLE_PLACES"] = "true"
        os.environ["PLACES_DAILY_CAP"] = "3"
        os.environ["PLACES_IP_LIMIT"] = "10"

    def tearDown(self):
        self._db.stop()
        super().tearDown()

    def test_result_link_refetches_and_does_not_store_places_payload(self):
        http = FakeHTTP()
        # Subject website is a sentinel. Drop it so website is a real gap and the
        # stored row can be checked for the provider and the street as well.
        http.subject = _subject()
        client = appmod.app.test_client()
        with patch("places._raw_http", http), patch("lookup._google_enrich", side_effect=AssertionError("scrape")):
            posted = client.post("/lookup", data={"q": "Rodan Heating and Air, Camarillo"})
        self.assertEqual(posted.status_code, 302)
        location = posted.headers["Location"]
        self.assertNotIn(SECRET_SITE, location)
        self.assertNotIn(SECRET_PROVIDER, location)
        self.assertNotIn("userRatingCount", location)
        self.assertRegex(location, r"/(r|teaser)/[A-Za-z0-9_-]+$")
        stored = self.db.read_text(encoding="utf-8", errors="replace")
        self.assertIn("ChIJsubject", stored)
        self.assertNotIn(SECRET_SITE, stored)
        self.assertNotIn(SECRET_PROVIDER, stored)
        self.assertNotIn(SECRET_STREET, stored)
        self.assertNotIn(str(SECRET_REVIEWS), stored)
        self.assertEqual(len(http.calls), 3)

        followed = client.get(location)
        self.assertEqual(followed.status_code, 200)
        html = followed.get_data(as_text=True)
        self.assertIn('translate="no"', html)
        self.assertIn("Google Maps", html)
        self.assertIn(SECRET_PROVIDER, html)
        self.assertIn("10+", html)
        self.assertNotIn(SECRET_STREET, html)
        self.assertEqual(len(http.calls), 3)

        appmod.clear_places_cache()
        blocked = client.get(location)
        self.assertEqual(blocked.status_code, 429)
        blocked_html = blocked.get_data(as_text=True)
        self.assertIn("try again tomorrow", blocked_html.lower())
        self.assertNotIn(SECRET_SITE, blocked_html)
        self.assertNotIn(SECRET_PROVIDER, blocked_html)
        self.assertEqual(len(http.calls), 3)

    def test_flag_off_still_uses_nominatim(self):
        os.environ["USE_GOOGLE_PLACES"] = "false"
        with patch("places._raw_http", side_effect=AssertionError("places called")), patch(
            "lookup._nominatim", return_value=[]
        ), patch(
            "lookup._google_enrich",
            return_value={"fetched": False, "preview": False, "final_url": "https://maps.google.com/not-a-place", "name": None, "note": "blocked", "service_area": None, "review_count_total": None},
        ):
            data = lookup.lookup("https://maps.google.com/not-a-place")
        self.assertEqual(data["thin_code"], "url_unparsed")

    def test_legal_names_google_terms(self):
        html = appmod.app.test_client().get("/legal").get_data(as_text=True)
        self.assertIn("https://cloud.google.com/maps-platform/terms", html)
        self.assertIn("https://policies.google.com/privacy", html)
        self.assertIn("place IDs", html)
        self.assertIn("0–9 or 10+", html)


if __name__ == "__main__":
    unittest.main()
