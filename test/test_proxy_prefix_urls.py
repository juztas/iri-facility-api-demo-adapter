#!/usr/bin/env python3
"""Regression tests for reverse-proxied absolute URL generation."""

import unittest

from fastapi.testclient import TestClient

from app import config
from app.main import APP

_BASE = f"/{config.API_URL}"


class ProxyPrefixUrlTests(unittest.TestCase):
    def test_status_resources_uses_forwarded_prefix_in_absolute_urls(self):
        client = TestClient(APP)

        response = client.get(
            f"{_BASE}/status/resources",
            headers={
                "x-forwarded-host": "localhost.rig.american-science-cloud.org",
                "x-forwarded-proto": "https",
                "x-forwarded-prefix": "/esnet-east",
            },
        )

        self.assertEqual(response.status_code, 200)
        resources = response.json()
        self.assertGreater(len(resources), 0)

        base = f"https://localhost.rig.american-science-cloud.org/esnet-east/{config.API_URL}"
        first = resources[0]
        self.assertTrue(first["self_uri"].startswith(f"{base}/status/resources/"))
        self.assertTrue(first["site_uri"].startswith(f"{base}/facility/sites/"))
        self.assertTrue(
            all(
                capability_uri.startswith(f"{base}/account/capabilities/")
                for capability_uri in first["capability_uris"]
            )
        )


if __name__ == "__main__":
    unittest.main()
