"""Tests for Idempotency-Key support on submit_job and update_job."""

import unittest

from app import config
from app.main import APP
from app.idempotency import build_cache_key
from fastapi.testclient import TestClient

from demo_adapter.compute.idempotency import InMemoryIdempotencyStore

_BASE = f"/{config.API_URL}"

_SUBMIT_HEADERS = {
    "authorization": "Bearer 12345",
    "x-iri-facility-project": "proj123",
}
_SUBMIT_BODY = {"executable": "/bin/echo", "arguments": ["hello"]}


def _resource_id(client: TestClient) -> str:
    resp = client.get(f"{_BASE}/status/resources")
    assert resp.status_code == 200
    return resp.json()[0]["id"]


class TestInMemoryStore(unittest.TestCase):
    """Unit tests for the store itself -- no HTTP stack needed."""

    def setUp(self):
        self.store = InMemoryIdempotencyStore(ttl=60)

    def _run(self, coro):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_first_request_proceeds(self):
        action, body, status = self._run(self.store.check_and_lock("k1", "h1"))
        self.assertEqual(action, "proceed")
        self.assertIsNone(body)
        self.assertIsNone(status)

    def test_in_flight_returns_conflict(self):
        self._run(self.store.check_and_lock("k2", "h1"))
        action, _, _ = self._run(self.store.check_and_lock("k2", "h1"))
        self.assertEqual(action, "conflict")

    def test_cached_result_returns_hit(self):
        self._run(self.store.check_and_lock("k3", "h1"))
        self._run(self.store.store_result("k3", "h1", {"id": "job-1"}, 200))
        action, body, status = self._run(self.store.check_and_lock("k3", "h1"))
        self.assertEqual(action, "hit")
        self.assertEqual(body, {"id": "job-1"})
        self.assertEqual(status, 200)

    def test_fingerprint_mismatch_detected(self):
        self._run(self.store.check_and_lock("k4", "h1"))
        self._run(self.store.store_result("k4", "h1", {"id": "job-1"}, 200))
        action, _, _ = self._run(self.store.check_and_lock("k4", "h_different"))
        self.assertEqual(action, "fingerprint_mismatch")

    def test_delete_lock_allows_retry(self):
        self._run(self.store.check_and_lock("k5", "h1"))
        self._run(self.store.delete_lock("k5"))
        action, _, _ = self._run(self.store.check_and_lock("k5", "h1"))
        self.assertEqual(action, "proceed")

    def test_delete_lock_does_not_delete_done_entry(self):
        self._run(self.store.check_and_lock("k6", "h1"))
        self._run(self.store.store_result("k6", "h1", {"id": "job-1"}, 200))
        self._run(self.store.delete_lock("k6"))  # should be a no-op
        action, _, _ = self._run(self.store.check_and_lock("k6", "h1"))
        self.assertEqual(action, "hit")

    def test_different_users_do_not_collide(self):
        k_alice = build_cache_key("alice", "same-key", "submit_job")
        k_bob = build_cache_key("bob", "same-key", "submit_job")
        self.assertNotEqual(k_alice, k_bob)


class TestIdempotencyHTTP(unittest.TestCase):
    """Integration tests through the FastAPI stack using the in-memory store."""

    def setUp(self):
        self.client = TestClient(APP)
        # Replace the store with a fresh one before each test.
        APP.state.idempotency_store = InMemoryIdempotencyStore(ttl=60)
        self.resource_id = _resource_id(self.client)

    def test_submit_without_idempotency_key_works_normally(self):
        resp = self.client.post(
            f"{_BASE}/compute/job/{self.resource_id}",
            headers=_SUBMIT_HEADERS,
            json=_SUBMIT_BODY,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("Idempotency-Key-Reply", resp.headers)

    def test_first_submit_is_miss(self):
        resp = self.client.post(
            f"{_BASE}/compute/job/{self.resource_id}",
            headers={**_SUBMIT_HEADERS, "Idempotency-Key": "uuid-submit-1"},
            json=_SUBMIT_BODY,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Idempotency-Key-Reply"), "miss")

    def test_retry_returns_cached_response(self):
        headers = {**_SUBMIT_HEADERS, "Idempotency-Key": "uuid-submit-2"}
        first = self.client.post(f"{_BASE}/compute/job/{self.resource_id}", headers=headers, json=_SUBMIT_BODY)
        second = self.client.post(f"{_BASE}/compute/job/{self.resource_id}", headers=headers, json=_SUBMIT_BODY)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.headers.get("Idempotency-Key-Reply"), "hit")
        self.assertEqual(first.json()["id"], second.json()["id"])

    def test_same_key_different_body_returns_422(self):
        headers = {**_SUBMIT_HEADERS, "Idempotency-Key": "uuid-submit-3"}
        self.client.post(f"{_BASE}/compute/job/{self.resource_id}", headers=headers, json=_SUBMIT_BODY)

        different_body = {**_SUBMIT_BODY, "arguments": ["world"]}
        resp = self.client.post(f"{_BASE}/compute/job/{self.resource_id}", headers=headers, json=different_body)
        self.assertEqual(resp.status_code, 422)
        self.assertIn("different request body", resp.json()["detail"])

    def test_two_different_keys_are_independent(self):
        h1 = {**_SUBMIT_HEADERS, "Idempotency-Key": "uuid-a"}
        h2 = {**_SUBMIT_HEADERS, "Idempotency-Key": "uuid-b"}
        r1 = self.client.post(f"{_BASE}/compute/job/{self.resource_id}", headers=h1, json=_SUBMIT_BODY)
        r2 = self.client.post(f"{_BASE}/compute/job/{self.resource_id}", headers=h2, json=_SUBMIT_BODY)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        # Both are misses (independent keys)
        self.assertEqual(r1.headers.get("Idempotency-Key-Reply"), "miss")
        self.assertEqual(r2.headers.get("Idempotency-Key-Reply"), "miss")

    def test_update_job_first_call_is_miss(self):
        submit_resp = self.client.post(
            f"{_BASE}/compute/job/{self.resource_id}",
            headers=_SUBMIT_HEADERS,
            json=_SUBMIT_BODY,
        )
        self.assertEqual(submit_resp.status_code, 200)
        job_id = submit_resp.json()["id"]

        resp = self.client.put(
            f"{_BASE}/compute/job/{self.resource_id}/{job_id}",
            headers={**_SUBMIT_HEADERS, "Idempotency-Key": "uuid-update-1"},
            json=_SUBMIT_BODY,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Idempotency-Key-Reply"), "miss")

    def test_update_job_retry_returns_hit(self):
        submit_resp = self.client.post(
            f"{_BASE}/compute/job/{self.resource_id}",
            headers=_SUBMIT_HEADERS,
            json=_SUBMIT_BODY,
        )
        job_id = submit_resp.json()["id"]
        headers = {**_SUBMIT_HEADERS, "Idempotency-Key": "uuid-update-2"}
        url = f"{_BASE}/compute/job/{self.resource_id}/{job_id}"

        first = self.client.put(url, headers=headers, json=_SUBMIT_BODY)
        second = self.client.put(url, headers=headers, json=_SUBMIT_BODY)

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.headers.get("Idempotency-Key-Reply"), "hit")
        self.assertEqual(first.json()["id"], second.json()["id"])


if __name__ == "__main__":
    unittest.main()
