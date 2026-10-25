"""CANONICAL_HOST 301: off by default, on when set, /health exempt."""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

from app import app, canonical_host


class CanonicalHostTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self._saved = os.environ.get("CANONICAL_HOST")
        os.environ.pop("CANONICAL_HOST", None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("CANONICAL_HOST", None)
        else:
            os.environ["CANONICAL_HOST"] = self._saved

    def test_unset_does_not_redirect(self):
        self.assertEqual(canonical_host(), "")
        res = self.client.get("/legal", base_url="http://map-gap.onrender.com")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("Location", res.headers)

    def test_blank_is_off(self):
        os.environ["CANONICAL_HOST"] = "   "
        self.assertEqual(canonical_host(), "")
        res = self.client.get("/", base_url="http://example.test")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("Location", res.headers)

    def test_other_host_redirects_with_path_and_query(self):
        os.environ["CANONICAL_HOST"] = "shopvsshop.com"
        res = self.client.get(
            "/what-is-shop-vs-shop?ref=ad&x=1",
            base_url="http://map-gap.onrender.com",
        )
        self.assertEqual(res.status_code, 301)
        self.assertEqual(
            res.headers["Location"],
            "https://shopvsshop.com/what-is-shop-vs-shop?ref=ad&x=1",
        )

    def test_scheme_and_slash_in_env_are_stripped(self):
        os.environ["CANONICAL_HOST"] = "https://shopvsshop.com/"
        self.assertEqual(canonical_host(), "shopvsshop.com")
        res = self.client.get("/pay", base_url="http://map-gap.onrender.com")
        self.assertEqual(res.status_code, 301)
        self.assertEqual(res.headers["Location"], "https://shopvsshop.com/pay")

    def test_same_host_is_not_redirected(self):
        os.environ["CANONICAL_HOST"] = "shopvsshop.com"
        res = self.client.get("/legal", base_url="http://shopvsshop.com")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("Location", res.headers)
        with_port = self.client.get("/", base_url="http://shopvsshop.com:443")
        self.assertEqual(with_port.status_code, 200)

    def test_health_is_exempt_on_any_host(self):
        os.environ["CANONICAL_HOST"] = "shopvsshop.com"
        res = self.client.get("/health", base_url="http://map-gap.onrender.com")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("Location", res.headers)
        body = res.get_json()
        self.assertTrue(body["ok"])

    def test_old_what_is_path_on_other_host_keeps_that_path(self):
        os.environ["CANONICAL_HOST"] = "shopvsshop.com"
        res = self.client.get("/what-is-map-gap?from=old", base_url="https://map-gap.onrender.com")
        self.assertEqual(res.status_code, 301)
        self.assertEqual(
            res.headers["Location"],
            "https://shopvsshop.com/what-is-map-gap?from=old",
        )

    def test_post_is_redirected(self):
        os.environ["CANONICAL_HOST"] = "shopvsshop.com"
        res = self.client.post("/lookup", data={"q": "ignored"}, base_url="http://other.example")
        self.assertEqual(res.status_code, 301)
        self.assertEqual(res.headers["Location"], "https://shopvsshop.com/lookup")

    def test_render_blueprint_leaves_canonical_host_unset(self):
        text = Path("render.yaml").read_text(encoding="utf-8")
        self.assertIn("name: map-gap", text)
        self.assertIn("MAPGAP_HOST", text)
        self.assertIn("healthCheckPath: /health", text)
        self.assertNotRegex(text, r"(?m)^\s*- key: CANONICAL_HOST\s*$")
        self.assertNotIn("mapgap.app", text)

    def test_sitemap_uses_new_path_only(self):
        xml = self.client.get("/sitemap.xml").get_data(as_text=True)
        self.assertIn("http://localhost/what-is-shop-vs-shop", xml)
        self.assertNotIn("what-is-map-gap", xml)
        self.assertIsNone(re.search(r"map-gap\.onrender\.com", xml))


if __name__ == "__main__":
    unittest.main()
