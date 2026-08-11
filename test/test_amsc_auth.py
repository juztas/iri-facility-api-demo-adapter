#!/usr/bin/env python3
"""End-to-end regression tests for the AmSC Keycard auth path through a real endpoint."""
import os
import tempfile
import time
import unittest
from unittest import mock

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import amsc_auth, config
from app.main import APP

_BASE = f"/{config.API_URL}"

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()

ISSUER = "https://identity.dev.amsc.example.gov/am/oauth2"
AUDIENCE = "https://iri.myfacility.example.gov"

# A dedicated fixture, not ../amsc_project_mapping.yaml -- that file documents
# real huck-sandbox AmSC project names for operators; coupling these tests to
# its exact contents makes them fail every time that example file is edited.


def _make_token(**overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": "auid-8f7b-492a-9c1d",
        "aud": AUDIENCE,
        "exp": now + 3600,
        "iat": now,
        "jti": "550e8400-e29b-41d4-a716-446655440000",
        "amsc_project_context": "foo",
    }
    claims.update(overrides)
    return jwt.encode(claims, _PRIVATE_KEY, algorithm="RS256")


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


class _FakeJWKSClient:
    def get_signing_key_from_jwt(self, token):
        return _FakeSigningKey(_PUBLIC_KEY)


def _amsc_env(mapping_file, **overrides):
    base = {
        "AMSC_TOKEN_ENABLED": "true",
        "AMSC_TOKEN_ISSUER": ISSUER,
        "AMSC_TOKEN_AUDIENCE": AUDIENCE,
        "AMSC_JWKS_URL": "https://example.invalid/jwks.json",
        "AMSC_PROJECT_MAPPING_FILE": mapping_file,
        "AMSC_USERINFO_VALIDATION_ENABLED": "false",
    }
    base.update(overrides)
    return base


class AmscAuthEndToEndTests(unittest.TestCase):
    def setUp(self):
        amsc_auth._jwks_clients.clear()
        amsc_auth._mapping_cache = {}
        amsc_auth._mapping_mtime = 0.0
        mapping = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        # gtorok is the only user common.py's DEMO_USER recognizes -- anything
        # else 403s ("User not found") regardless of AmSC auth having passed.
        mapping.write("project_mapping:\n  foo: gtorok\n")
        mapping.close()
        self._mapping_file = mapping.name
        self.addCleanup(os.unlink, self._mapping_file)

    def _amsc_env(self, **overrides):
        return _amsc_env(self._mapping_file, **overrides)

    def test_amsc_disabled_by_default_demo_key_still_works(self):
        """Regression: AMSC_TOKEN_ENABLED unset (default) must not change existing auth behavior."""
        client = TestClient(APP)
        response = client.get(f"{_BASE}/account/projects", headers={"authorization": "Bearer 12345"})
        self.assertEqual(response.status_code, 200)

    def test_amsc_enabled_valid_token_mapped_project_resolves_demo_user(self):
        client = TestClient(APP)
        with mock.patch.dict(os.environ, self._amsc_env(), clear=False), mock.patch.object(
            amsc_auth, "_jwks_client", return_value=_FakeJWKSClient()
        ):
            response = client.get(
                f"{_BASE}/account/projects",
                headers={"authorization": f"Bearer {_make_token()}"},
            )
        self.assertEqual(response.status_code, 200)

    def test_amsc_enabled_unmapped_project_rejected(self):
        client = TestClient(APP)
        with mock.patch.dict(os.environ, self._amsc_env(), clear=False), mock.patch.object(
            amsc_auth, "_jwks_client", return_value=_FakeJWKSClient()
        ):
            response = client.get(
                f"{_BASE}/account/projects",
                headers={"authorization": f"Bearer {_make_token(amsc_project_context='not-provisioned')}"},
            )
        self.assertEqual(response.status_code, 401)

    def test_amsc_enabled_expired_token_rejected(self):
        client = TestClient(APP)
        with mock.patch.dict(os.environ, self._amsc_env(), clear=False), mock.patch.object(
            amsc_auth, "_jwks_client", return_value=_FakeJWKSClient()
        ):
            expired = _make_token(exp=int(time.time()) - 60, iat=int(time.time()) - 120)
            response = client.get(
                f"{_BASE}/account/projects",
                headers={"authorization": f"Bearer {expired}"},
            )
        self.assertEqual(response.status_code, 401)

    def test_amsc_enabled_falls_through_to_demo_key_on_amsc_failure(self):
        """A caller without an AmSC token (e.g. local dev) still authenticates via the demo adapter's own key."""
        client = TestClient(APP)
        with mock.patch.dict(os.environ, self._amsc_env(), clear=False), mock.patch.object(
            amsc_auth, "_jwks_client", return_value=_FakeJWKSClient()
        ):
            response = client.get(f"{_BASE}/account/projects", headers={"authorization": "Bearer 12345"})
        self.assertEqual(response.status_code, 200)

    def test_amsc_userinfo_check_fail_closed_rejects_request(self):
        import httpx

        class _FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def get(self, _url, headers=None):
                raise httpx.ConnectError("Ping unreachable")

        client = TestClient(APP)
        env = self._amsc_env(AMSC_USERINFO_VALIDATION_ENABLED="true", AMSC_USERINFO_URL="https://example.invalid/userinfo")
        with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(
            amsc_auth, "_jwks_client", return_value=_FakeJWKSClient()
        ), mock.patch.object(amsc_auth.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient()):
            response = client.get(
                f"{_BASE}/account/projects",
                headers={"authorization": f"Bearer {_make_token()}"},
            )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
