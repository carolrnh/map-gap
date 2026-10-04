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
    COMPETITOR_RADII_M,
    DETAILS_FIELD_MASK,
    SEARCH_ENTERPRISE_MASK,
    SEARCH_IDS_MASK,
    category_label,
    clean_website,
    city_state_from_place,
    google_places_enabled,
    haversine_m,
    normalize_place,
    photo_label_for,
    pick_competitors,
    search_text_ids,
    select_gaps,
    select_local_competitors,
)
from places_lookup import geocode_us_city, persistable_record, refetch_places, run_places_lookup
from result_link import unpack_link

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
        "location": {"latitude": 34.23, "longitude": -119.05},
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
        "location": {"latitude": 34.2164, "longitude": -119.0376},
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
            "places.primaryTypeDisplayName",
            "places.googleMapsTypeLabel",
            "places.nationalPhoneNumber",
        ):
            self.assertIn(field, mask.split(","))
        self.assertNotIn("places.reviews", mask.split(","))
        self.assertNotIn("reviews", DETAILS_FIELD_MASK.split(","))
        body = json.loads(search_call["body"])
        self.assertTrue(body["includePureServiceAreaBusinesses"])
        self.assertEqual(body["pageSize"], 20)
        self.assertEqual(body["textQuery"], "hvac contractor")
        self.assertEqual(body["regionCode"], "US")
        self.assertNotIn("locationBias", body)
        rect = body["locationRestriction"]["rectangle"]
        self.assertAlmostEqual((rect["low"]["latitude"] + rect["high"]["latitude"]) / 2, 34.2164, places=4)
        self.assertAlmostEqual((rect["low"]["longitude"] + rect["high"]["longitude"]) / 2, -119.0376, places=4)
        detail_urls = [c["url"] for c in http.calls if c["method"] == "GET"]
        self.assertEqual(detail_urls, ["https://places.googleapis.com/v1/places/ChIJsubject"])
        self.assertEqual(result["subject_place_id"], "ChIJsubject")
        self.assertEqual(result["competitor_place_ids"], ["ChIJcomp1", "ChIJcomp2", "ChIJcomp3"])
        self.assertTrue(result["listing"]["service_area"])
        self.assertFalse(result["listing"]["address"])
        self.assertNotIn(SECRET_STREET, json.dumps(persistable_record(result)))

    def test_maps_url_uses_location_bias_and_does_not_scrape_preview(self):
        http = FakeHTTP()
        # No Place location on this subject, so the competitor search keeps the URL pin.
        # The city still comes from formattedAddress, without the street.
        http.subject.pop("location", None)
        with patch("lookup._google_enrich", side_effect=AssertionError("preview scrape")):
            run_places_lookup("", "", RODAN_URL, http=http)
        ids_body = json.loads(http.calls[0]["body"])
        self.assertIn("Rodan Heating and Air", ids_body["textQuery"])
        self.assertEqual(ids_body["locationBias"]["circle"]["center"]["latitude"], 34.2087835)
        self.assertTrue(ids_body["includePureServiceAreaBusinesses"])
        self.assertTrue(all("preview" not in c["url"] for c in http.calls))
        search_body = json.loads(http.calls[2]["body"])
        self.assertEqual(search_body["textQuery"], "hvac contractor")
        self.assertNotIn("Ventura", search_body["textQuery"])
        self.assertNotIn("999 Secret", search_body["textQuery"])
        self.assertNotIn("locationBias", search_body)
        rect = search_body["locationRestriction"]["rectangle"]
        self.assertAlmostEqual((rect["low"]["latitude"] + rect["high"]["latitude"]) / 2, 34.2087835, places=4)

    def test_maps_url_without_city_uses_place_city_and_coordinates(self):
        http = FakeHTTP()
        http.subject = _subject()
        http.subject["primaryType"] = "general_contractor"
        http.subject["primaryTypeDisplayName"] = {"text": "General contractor"}
        http.subject["googleMapsTypeLabel"] = {"text": "HVAC contractor"}
        http.subject["types"] = ["general_contractor", "point_of_interest", "establishment"]
        http.subject["formattedAddress"] = ""
        http.subject["addressComponents"] = [
            {"longText": "Camarillo", "shortText": "Camarillo", "types": ["locality", "political"]},
            {"longText": "California", "shortText": "CA", "types": ["administrative_area_level_1", "political"]},
        ]
        http.subject["location"] = {"latitude": 34.2164, "longitude": -119.0376}
        result = run_places_lookup("", "", RODAN_URL, http=http)
        ids_body = json.loads(http.calls[0]["body"])
        search_body = json.loads(http.calls[2]["body"])
        self.assertEqual(ids_body["locationBias"]["circle"]["center"]["latitude"], 34.2087835)
        self.assertEqual(search_body["textQuery"], "hvac contractor")
        self.assertNotIn("locationBias", search_body)
        rect = search_body["locationRestriction"]["rectangle"]
        self.assertAlmostEqual((rect["low"]["latitude"] + rect["high"]["latitude"]) / 2, 34.2164, places=4)
        self.assertAlmostEqual((rect["low"]["longitude"] + rect["high"]["longitude"]) / 2, -119.0376, places=4)
        self.assertEqual(result["listing"]["category"], "HVAC contractor")
        self.assertFalse(result["listing"]["address"])
        self.assertEqual(result["listing"]["city"], "Camarillo CA")
        self.assertEqual(result["raw"]["city_source"], "place")
        details_mask = http.calls[1]["headers"]["X-Goog-FieldMask"].split(",")
        search_mask = http.calls[2]["headers"]["X-Goog-FieldMask"].split(",")
        self.assertIn("addressComponents", details_mask)
        self.assertIn("location", details_mask)
        self.assertIn("googleMapsTypeLabel", details_mask)
        self.assertIn("primaryTypeDisplayName", details_mask)
        self.assertNotIn("addressComponents", search_mask)
        self.assertIn("places.location", search_mask)

    def test_new_fields_stay_inside_the_enterprise_sku(self):
        # Place Data Fields (New), checked 2026-09-24. These raise the call to
        # Enterprise + Atmosphere, which this check does not use.
        atmosphere = {
            "reviews",
            "reviewSummary",
            "editorialSummary",
            "generativeSummary",
            "paymentOptions",
            "parkingOptions",
            "outdoorSeating",
            "servesBeer",
            "allowsDogs",
            "goodForChildren",
            "liveMusic",
            "delivery",
            "dineIn",
            "takeout",
            "reservable",
            "evChargeOptions",
            "fuelOptions",
            "neighborhoodSummary",
            "routingSummaries",
        }
        details = set(DETAILS_FIELD_MASK.split(","))
        search = {field.split(".", 1)[1] for field in SEARCH_ENTERPRISE_MASK.split(",")}
        self.assertFalse(atmosphere & details)
        self.assertFalse(atmosphere & search)
        # Below Enterprise: Pro (googleMapsTypeLabel, primaryTypeDisplayName)
        # and Essentials (addressComponents, location). They do not raise the SKU.
        for field in ("googleMapsTypeLabel", "primaryTypeDisplayName", "primaryType", "addressComponents", "location"):
            self.assertIn(field, details)
        self.assertEqual(SEARCH_IDS_MASK, "places.id")

    def test_one_gap_unlocks_and_zero_gaps_do_not(self):
        http = FakeHTTP()
        http.subject = _subject()
        http.subject["rating"] = 4.8
        http.subject["userRatingCount"] = 400
        one = run_places_lookup("Rodan Heating and Air", "Camarillo", "", http=http)
        self.assertEqual([b["kind"] for b in one["raw"]["bullets"]], ["photos"])
        self.assertTrue(one["raw"]["unlock"])
        self.assertEqual(one["outcome"], "few_gaps")

        quiet = FakeHTTP()
        quiet.subject = _subject()
        quiet.subject["rating"] = 4.8
        quiet.subject["userRatingCount"] = 400
        quiet.subject["photos"] = [{"name": f"places/x/photos/{n}"} for n in range(10)]
        none = run_places_lookup("Rodan Heating and Air", "Camarillo", "", http=quiet)
        self.assertEqual(none["raw"]["bullets"], [])
        self.assertFalse(none["raw"]["unlock"])
        self.assertEqual(none["outcome"], "few_gaps")

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
        self.assertIn("category", gaps[0]["body"].lower())
        self.assertIn("General contractor", gaps[0]["body"])
        self.assertIn("HVAC contractor", gaps[0]["body"])
        self.assertNotIn("Posts", gaps[0]["body"])

    def test_maps_label_replaces_general_contractor(self):
        raw = {
            "primaryType": "general_contractor",
            "primaryTypeDisplayName": {"text": "General contractor"},
            "googleMapsTypeLabel": {"text": "HVAC contractor"},
            "types": ["general_contractor", "point_of_interest", "establishment"],
        }
        self.assertEqual(category_label(raw), "HVAC contractor")
        self.assertEqual(normalize_place(raw)["category"], "HVAC contractor")
        specific = {
            "primaryType": "general_contractor",
            "primaryTypeDisplayName": {"text": "General contractor"},
            "types": ["general_contractor", "hvac_contractor", "point_of_interest"],
        }
        self.assertEqual(category_label(specific), "HVAC contractor")
        named = {
            "primaryType": "hvac_contractor",
            "primaryTypeDisplayName": {"text": "HVAC contractor"},
            "types": ["hvac_contractor", "general_contractor"],
        }
        self.assertEqual(category_label(named), "HVAC contractor")

    def test_same_public_category_is_not_a_gap(self):
        subject = {
            "photo_count": 10,
            "review_count": 5,
            "rating": 5,
            "website": "x",
            "hours_listed": True,
            "phone": "1",
            "primary_type": "general_contractor",
            "category": "HVAC contractor",
        }
        comp = {
            "name": "Other",
            "photo_count": 10,
            "review_count": 5,
            "rating": 5,
            "website": "y",
            "hours_listed": True,
            "phone": "2",
            "primary_type": "hvac_contractor",
            "category": "HVAC contractor",
        }
        self.assertEqual(select_gaps(subject, [comp]), [])

    def test_missing_rating_and_reviews_are_not_gaps(self):
        subject = {
            "name": "Rodan Heating and Air",
            "review_count": None,
            "rating": None,
            "website": "https://a.example",
            "hours_listed": True,
            "photo_count": 1,
            "primary_type": "hvac_contractor",
            "category": "HVAC contractor",
            "phone": "1",
        }
        comp = {
            "name": "Other",
            "review_count": 400,
            "rating": 5.0,
            "website": "https://b.example",
            "hours_listed": True,
            "photo_count": 10,
            "primary_type": "hvac_contractor",
            "category": "HVAC contractor",
            "phone": "2",
        }
        kinds = [g["kind"] for g in select_gaps(subject, [comp, comp, comp])]
        self.assertEqual(kinds, ["photos"])

    def test_zero_reviews_still_count_as_a_gap(self):
        subject = {
            "review_count": 0,
            "rating": 5,
            "website": "a",
            "hours_listed": True,
            "photo_count": 10,
            "phone": "1",
            "category": "HVAC contractor",
            "primary_type": "hvac_contractor",
        }
        comp = {
            "name": "Other",
            "review_count": 10,
            "rating": 5,
            "website": "b",
            "hours_listed": True,
            "photo_count": 10,
            "phone": "2",
            "category": "HVAC contractor",
            "primary_type": "hvac_contractor",
        }
        self.assertEqual([g["kind"] for g in select_gaps(subject, [comp])], ["review_count"])

    def test_city_falls_back_to_formatted_address(self):
        city, state = city_state_from_place(
            {
                "addressComponents": [
                    {"longText": "Camarillo", "shortText": "Camarillo", "types": ["locality", "political"]},
                    {"longText": "California", "shortText": "CA", "types": ["administrative_area_level_1"]},
                ]
            }
        )
        self.assertEqual((city, state), ("Camarillo", "CA"))
        city, state = city_state_from_place({"formattedAddress": "Camarillo, CA 93010, USA"})
        self.assertEqual((city, state), ("Camarillo", "CA"))

    def test_strips_tracking_params_from_websites(self):
        shown = normalize_place(
            {
                "websiteUri": "https://richco.example/book?utm_source=directories&utm_medium=organic&gclid=abc&page=services"
            }
        )["website"]
        self.assertEqual(shown, "https://richco.example/book?page=services")
        self.assertNotIn("utm_", shown)
        self.assertEqual(
            clean_website("https://richco.example/?utm_source=directories&utm_medium=organic"),
            "https://richco.example/",
        )
        self.assertEqual(clean_website("https://example.com/path"), "https://example.com/path")

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


RIVERTON = (40.5219, -111.9391)


def _north_of(lat: float, lon: float, meters: float) -> tuple[float, float]:
    return lat + meters / 111_320.0, lon


def _shop(pid: str, name: str, lat: float, lon: float, *, state: str = "UT", city: str = "Riverton"):
    return {
        "id": pid,
        "displayName": {"text": name},
        "primaryType": "plumber",
        "primaryTypeDisplayName": {"text": "Plumber"},
        "types": ["plumber"],
        "nationalPhoneNumber": "(801) 555-0100",
        "websiteUri": "https://shop.example",
        "rating": 4.9,
        "userRatingCount": 400,
        "regularOpeningHours": {"weekdayDescriptions": ["Monday: 8:00 AM – 5:00 PM"]},
        "photos": [{"name": "places/x/photos/a"}, {"name": "places/x/photos/b"}],
        "formattedAddress": f"1 Main St, {city}, {state} 84000, USA",
        "location": {"latitude": lat, "longitude": lon},
        "businessStatus": "OPERATIONAL",
    }


def _riverton_subject():
    subject = _subject()
    subject["displayName"] = {"text": "Andrus Plumbing"}
    subject["primaryType"] = "plumber"
    subject["primaryTypeDisplayName"] = {"text": "Plumber"}
    subject["types"] = ["plumber"]
    subject["pureServiceAreaBusiness"] = True
    subject["formattedAddress"] = "Riverton, UT 84065, USA"
    subject["location"] = {"latitude": RIVERTON[0], "longitude": RIVERTON[1]}
    subject["addressComponents"] = [
        {"longText": "Riverton", "shortText": "Riverton", "types": ["locality", "political"]},
        {"longText": "Utah", "shortText": "UT", "types": ["administrative_area_level_1", "political"]},
    ]
    return subject


class LocalCompetitorTests(EnvCase):
    def test_distant_shops_are_not_comparisons_even_when_places_returns_them(self):
        """Tulsa, Baltimore, and a far same-state shop must not beat shops near the pin."""
        tulsa = _shop("tulsa", "Tulsa Plumbing Co", 36.1540, -95.9928, state="OK", city="Tulsa")
        baltimore = _shop("baltimore", "Baltimore Plumbing Co", 39.2904, -76.6122, state="MD", city="Baltimore")
        st_george = _shop("stgeorge", "St George Plumbing", 37.0965, -113.5684, state="UT", city="St George")
        near = []
        for i, meters in enumerate((3000, 8000, 12000), start=1):
            lat, lon = _north_of(*RIVERTON, meters)
            near.append(_shop(f"local{i}", f"Local Plumbing {i}", lat, lon))
        # Far shops first, so a "first 3" pick without a distance check fails this test.
        http = FakeHTTP(subject=_riverton_subject(), competitors=[tulsa, baltimore, st_george, *near])
        result = run_places_lookup("Andrus Plumbing", "Riverton, UT", "", http=http)
        self.assertEqual(result["competitor_place_ids"], ["local1", "local2", "local3"])
        self.assertEqual(result["listing"]["city"], "Riverton, UT")
        for row in result["nearby"]:
            self.assertLess(row["distance_m"], 25000)
            self.assertEqual(row["state"], "UT")
        search_calls = [c for c in http.calls if c["method"] == "POST" and "searchText" in c["url"]]
        # One id search plus one competitor search. The 25 km ring already has 3 shops.
        self.assertEqual(len(search_calls), 2)
        body = json.loads(search_calls[-1]["body"])
        self.assertEqual(body["textQuery"], "plumber")
        self.assertNotIn("Riverton", body["textQuery"])
        self.assertNotIn("locationBias", body)
        rect = body["locationRestriction"]["rectangle"]
        self.assertAlmostEqual((rect["low"]["latitude"] + rect["high"]["latitude"]) / 2, RIVERTON[0], places=3)
        self.assertGreater(haversine_m(*RIVERTON, 36.1540, -95.9928), 500_000)
        self.assertGreater(haversine_m(*RIVERTON, 37.0965, -113.5684), 200_000)

    def test_rural_search_widens_and_still_drops_distant_shops(self):
        tulsa = _shop("tulsa", "Tulsa Plumbing Co", 36.1540, -95.9928, state="OK", city="Tulsa")
        far_locals = []
        for i, meters in enumerate((40000, 42000, 45000), start=1):
            lat, lon = _north_of(*RIVERTON, meters)
            far_locals.append(_shop(f"wide{i}", f"County Plumbing {i}", lat, lon, city="Herriman"))

        class ByRadius(FakeHTTP):
            def __call__(self, method, url, headers, body):
                self.calls.append({"method": method, "url": url, "headers": dict(headers), "body": body})
                if "searchText" in url:
                    mask = headers.get("X-Goog-FieldMask")
                    if mask == SEARCH_IDS_MASK:
                        return {"places": [{"id": self.subject_id}]}
                    payload = json.loads(body)
                    rect = payload["locationRestriction"]["rectangle"]
                    radius = (rect["high"]["latitude"] - rect["low"]["latitude"]) / 2 * 111_320.0
                    if radius < 30_000:
                        return {"places": [tulsa]}
                    return {"places": [*far_locals, tulsa]}
                if method == "GET" and self.subject_id in url:
                    return self.subject
                raise AssertionError(f"unexpected places call {method} {url}")

        http = ByRadius(subject=_riverton_subject(), competitors=[])
        result = run_places_lookup("Pinon Plumbing", "Westcliffe, CO", "", http=http)
        self.assertEqual(result["competitor_place_ids"], ["wide1", "wide2", "wide3"])
        self.assertNotIn("tulsa", result["competitor_place_ids"])
        for row in result["nearby"]:
            self.assertGreater(row["distance_m"], 25_000)
            self.assertLess(row["distance_m"], 50_000)
        radii = []
        for call in http.calls:
            if call["method"] != "POST" or "searchText" not in call["url"]:
                continue
            if call["headers"].get("X-Goog-FieldMask") == SEARCH_IDS_MASK:
                continue
            rect = json.loads(call["body"])["locationRestriction"]["rectangle"]
            radii.append((rect["high"]["latitude"] - rect["low"]["latitude"]) / 2 * 111_320.0)
        self.assertEqual(len(radii), 2)
        self.assertAlmostEqual(radii[0], COMPETITOR_RADII_M[0], delta=500)
        self.assertAlmostEqual(radii[1], COMPETITOR_RADII_M[1], delta=500)

    def test_wider_ring_keeps_shops_already_found_nearby(self):
        close = []
        for i, meters in enumerate((2000, 6000), start=1):
            lat, lon = _north_of(*RIVERTON, meters)
            close.append(_shop(f"close{i}", f"Close Plumbing {i}", lat, lon))
        wide = []
        for i, meters in enumerate((40000, 42000, 44000), start=1):
            lat, lon = _north_of(*RIVERTON, meters)
            wide.append(_shop(f"wide{i}", f"Farther Plumbing {i}", lat, lon, city="Herriman"))

        class ByRadius(FakeHTTP):
            def __call__(self, method, url, headers, body):
                self.calls.append({"method": method, "url": url, "headers": dict(headers), "body": body})
                if "searchText" in url:
                    if headers.get("X-Goog-FieldMask") == SEARCH_IDS_MASK:
                        return {"places": [{"id": self.subject_id}]}
                    rect = json.loads(body)["locationRestriction"]["rectangle"]
                    radius = (rect["high"]["latitude"] - rect["low"]["latitude"]) / 2 * 111_320.0
                    if radius < 30_000:
                        return {"places": close}
                    return {"places": wide}
                if method == "GET" and self.subject_id in url:
                    return self.subject
                raise AssertionError(f"unexpected places call {method} {url}")

        http = ByRadius(subject=_riverton_subject(), competitors=[])
        result = run_places_lookup("Andrus Plumbing", "Riverton, UT", "", http=http)
        self.assertEqual(result["competitor_place_ids"], ["close1", "close2", "wide1"])

    def test_stored_distant_ids_are_not_kept_on_refetch(self):
        tulsa = _shop("tulsa", "Tulsa Plumbing Co", 36.1540, -95.9928, state="OK", city="Tulsa")
        local = _shop("local1", "Local Plumbing", *_north_of(*RIVERTON, 4000))
        http = FakeHTTP(subject=_riverton_subject(), competitors=[tulsa, local])
        result = refetch_places(
            {
                "user_input": {"name": "Andrus Plumbing", "city": "Riverton, UT", "listing_url": ""},
                "subject_place_id": "ChIJsubject",
                "competitor_place_ids": ["tulsa"],
            },
            http=http,
        )
        self.assertEqual(result["competitor_place_ids"], ["local1"])

    def test_no_anchor_does_not_fall_back_to_a_national_search(self):
        http = FakeHTTP()
        http.subject.pop("location", None)
        with patch("places_lookup.geocode_us_city", return_value=None):
            result = run_places_lookup("Andrus Plumbing", "", "", http=http)
        self.assertEqual(result["outcome"], "no_competitors")
        self.assertEqual(result["competitor_place_ids"], [])
        self.assertEqual(len(http.calls), 2)

    def test_service_area_without_a_pin_uses_the_city_centroid(self):
        http = FakeHTTP(subject=_riverton_subject(), competitors=[])
        http.subject.pop("location", None)
        lat, lon = _north_of(*RIVERTON, 5000)
        http.competitors = [
            _shop("tulsa", "Tulsa Plumbing Co", 36.1540, -95.9928, state="OK", city="Tulsa"),
            _shop("local1", "Local Plumbing", lat, lon),
        ]
        with patch("places_lookup.geocode_us_city", return_value=RIVERTON) as geo:
            result = run_places_lookup("Andrus Plumbing", "Riverton, UT", "", http=http)
        geo.assert_called_once_with("Riverton, UT")
        self.assertEqual(result["competitor_place_ids"], ["local1"])
        self.assertLess(result["nearby"][0]["distance_m"], 25_000)

    def test_select_local_rejects_far_same_state_and_keeps_a_local_service_area_shop(self):
        anchor = RIVERTON
        far = normalize_place(_shop("stgeorge", "St George Plumbing", 37.0965, -113.5684, state="UT", city="St George"))
        sab_here = normalize_place(
            {
                "id": "sab-local",
                "displayName": {"text": "Valley Plumbing"},
                "primaryType": "plumber",
                "types": ["plumber"],
                "formattedAddress": "Riverton, UT, USA",
                "businessStatus": "OPERATIONAL",
            }
        )
        sab_away = normalize_place(
            {
                "id": "sab-tulsa",
                "displayName": {"text": "Tulsa Plumbing Co"},
                "primaryType": "plumber",
                "types": ["plumber"],
                "formattedAddress": "Tulsa, OK, USA",
                "businessStatus": "OPERATIONAL",
            }
        )
        kept = select_local_competitors(
            [far, sab_away, sab_here],
            "subject",
            anchor=anchor,
            radius_m=25_000,
            term="plumber",
            subject_state="UT",
        )
        self.assertEqual([row["place_id"] for row in kept], ["sab-local"])
        self.assertGreater(haversine_m(*anchor, far["lat"], far["lon"]), 25_000)

    def test_geocode_asks_nominatim_for_a_us_city(self):
        with patch("lookup._nominatim", return_value=[{"lat": "40.52", "lon": "-111.94"}]) as nom:
            point = geocode_us_city("Riverton, UT")
        self.assertEqual(point, (40.52, -111.94))
        query = nom.call_args[0][0]["q"]
        self.assertIn("Riverton", query)
        self.assertIn("USA", query)


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
        self.assertEqual(limits.places_daily_cap(), 150)

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
        token = location.rstrip("/").split("/")[-1]
        view = unpack_link(token)
        self.assertIsNotNone(view)
        self.assertTrue(view.get("places_mode"))
        packed = json.dumps(view)
        self.assertNotIn(SECRET_SITE, packed)
        self.assertNotIn(SECRET_PROVIDER, packed)
        self.assertNotIn(SECRET_STREET, packed)
        self.assertNotIn(str(SECRET_REVIEWS), packed)
        self.assertEqual(view.get("listing"), {})
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

    def test_one_gap_still_shows_the_paid_offer(self):
        http = FakeHTTP()
        http.subject = _subject()
        http.subject["rating"] = 4.8
        http.subject["userRatingCount"] = 400
        http.subject["photos"] = [{"name": "places/x/photos/only"}]
        client = appmod.app.test_client()
        with patch("places._raw_http", http):
            posted = client.post("/lookup", data={"q": "Rodan Heating and Air, Camarillo"})
        self.assertEqual(posted.status_code, 302)
        html = client.get(posted.headers["Location"]).get_data(as_text=True)
        self.assertIn("You're close. Here's what still separates you from the top 3", html)
        self.assertIn("Competitor report — $195", html)
        self.assertIn("Payment not connected yet", html)
        self.assertNotIn("stays off", html)
        self.assertNotIn("1 thing the shops above you have", html)
        self.assertIn("Photos", html)

    def test_no_gaps_hides_the_paid_offer(self):
        http = FakeHTTP()
        http.subject = _subject()
        http.subject["rating"] = 4.8
        http.subject["userRatingCount"] = 400
        http.subject["photos"] = [{"name": f"places/x/photos/{n}"} for n in range(10)]
        client = appmod.app.test_client()
        with patch("places._raw_http", http):
            posted = client.post("/lookup", data={"q": "Rodan Heating and Air, Camarillo"})
        html = client.get(posted.headers["Location"]).get_data(as_text=True)
        self.assertIn("No gap on the fields Places returns", html)
        self.assertNotIn("<h2>Competitor report — $195</h2>", html)
        self.assertNotIn('href="#pay"', html)
        self.assertNotIn("You're close", html)
        self.assertIn("stays off when these fields show no gap", html)

    def test_missing_rating_and_reviews_say_not_listed(self):
        http = FakeHTTP()
        http.subject = _subject()
        http.subject.pop("rating")
        http.subject.pop("userRatingCount")
        http.subject["websiteUri"] = "https://richco.example/book?utm_source=directories&utm_medium=organic"
        client = appmod.app.test_client()
        with patch("places._raw_http", http):
            posted = client.post("/lookup", data={"q": "Rodan Heating and Air, Camarillo"})
        html = client.get(posted.headers["Location"]).get_data(as_text=True)
        self.assertIn("not listed", html)
        self.assertNotIn("UNKNOWN", html)
        self.assertNotIn("utm_", html)
        self.assertIn("https://richco.example/book", html)
        self.assertIn("Photos", html)
        self.assertNotIn(">Reviews<", html)

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
