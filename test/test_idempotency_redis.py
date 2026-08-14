"""Redis-backed idempotency integration tests.

Skipped automatically if Redis is not reachable at REDIS_URL (default: redis://localhost:6379).

Run standalone:
    REDIS_URL=redis://localhost:6379 .venv/bin/python -m pytest test/test_idempotency_redis.py -v

What these tests cover beyond test_idempotency.py:
  - Real Redis I/O (network round-trips, actual TTL, persistence across clients)
  - WATCH/MULTI/EXEC conditional-write guards (store_result and release_lock)
  - Concurrent requests: asyncio.gather with N parallel submissions
"""

import asyncio
import json
import os
import uuid
import unittest

import redis as redis_sync
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app import config
from app.idempotency import build_cache_key
from app.main import APP

from demo_adapter.compute.idempotency import RedisIdempotencyStore

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
_BASE = f"/{config.API_URL}"

_HEADERS = {
    "authorization": "Bearer 12345",
    "x-iri-facility-project": "proj123",
}
_BODY = {"executable": "/bin/echo", "arguments": ["hello"]}


def _check_redis():
    try:
        r = redis_sync.Redis.from_url(_REDIS_URL)
        r.ping()
        r.close()
    except Exception as exc:
        raise unittest.SkipTest(f"Redis not reachable at {_REDIS_URL}: {exc}") from exc


def _resource_id() -> str:
    client = TestClient(APP)
    resp = client.get(f"{_BASE}/status/resources")
    assert resp.status_code == 200
    return resp.json()[0]["id"]


class TestRedisStore(unittest.TestCase):
    """Store-level correctness tests against a real Redis instance.

    Uses a single event loop for the whole class so aioredis connection
    pool and all coroutines share the same loop.
    """

    @classmethod
    def setUpClass(cls):
        _check_redis()
        cls._loop = asyncio.new_event_loop()

    @classmethod
    def tearDownClass(cls):
        cls._loop.close()

    def setUp(self):
        self.store = RedisIdempotencyStore(_REDIS_URL, ttl=60)

    def tearDown(self):
        self._loop.run_until_complete(self.store.close())

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    def _k(self) -> str:
        return str(uuid.uuid4())

    # ------------------------------------------------------------------ #
    # Basic flow                                                           #
    # ------------------------------------------------------------------ #

    def test_first_request_proceeds(self):
        action, body, status = self._run(self.store.check_and_lock(self._k(), "h1"))
        self.assertEqual(action, "proceed")
        self.assertIsNone(body)
        self.assertIsNone(status)

    def test_in_flight_returns_conflict(self):
        k = self._k()
        self._run(self.store.check_and_lock(k, "h1"))
        action, _, _ = self._run(self.store.check_and_lock(k, "h1"))
        self.assertEqual(action, "conflict")

    def test_cached_result_returns_hit(self):
        k = self._k()
        self._run(self.store.check_and_lock(k, "h1"))
        self._run(self.store.store_result(k, "h1", {"id": "job-1"}, 200))
        action, body, status = self._run(self.store.check_and_lock(k, "h1"))
        self.assertEqual(action, "hit")
        self.assertEqual(body, {"id": "job-1"})
        self.assertEqual(status, 200)

    def test_fingerprint_mismatch(self):
        k = self._k()
        self._run(self.store.check_and_lock(k, "h1"))
        self._run(self.store.store_result(k, "h1", {"id": "job-1"}, 200))
        action, _, _ = self._run(self.store.check_and_lock(k, "h_different"))
        self.assertEqual(action, "fingerprint_mismatch")

    def test_delete_lock_allows_retry(self):
        k = self._k()
        self._run(self.store.check_and_lock(k, "h1"))
        self._run(self.store.delete_lock(k))
        action, _, _ = self._run(self.store.check_and_lock(k, "h1"))
        self.assertEqual(action, "proceed")

    # ------------------------------------------------------------------ #
    # Conditional-write guards (what WATCH/MULTI/EXEC protects)           #
    # ------------------------------------------------------------------ #

    def test_delete_lock_is_noop_when_key_is_done(self):
        """delete_lock must not delete a completed (DONE) entry."""
        k = self._k()
        self._run(self.store.check_and_lock(k, "h1"))
        self._run(self.store.store_result(k, "h1", {"id": "job-1"}, 200))
        self._run(self.store.delete_lock(k))  # key is DONE -- should skip
        action, body, _ = self._run(self.store.check_and_lock(k, "h1"))
        self.assertEqual(action, "hit")
        self.assertEqual(body, {"id": "job-1"})

    def test_store_result_is_noop_when_lock_has_changed(self):
        """store_result must not overwrite when our lock value no longer matches.

        Simulates: lock expired, second request re-acquired with a different body_hash.
        The first request's delayed store_result must be a no-op.
        """
        k = self._k()
        self._run(self.store.check_and_lock(k, "h_first"))
        # Directly overwrite the key to simulate re-acquisition by a second request
        rkey = self.store._rkey(k)
        new_lock = json.dumps({"state": "LOCKED", "body_hash": "h_second"})
        self._run(self.store._client.set(rkey, new_lock, ex=60))
        # First request's store_result with the old hash must be skipped
        self._run(self.store.store_result(k, "h_first", {"id": "job-first"}, 200))
        val = self._run(self.store._client.get(rkey))
        self.assertEqual(val, new_lock, "store_result overwrote a lock it no longer owned")

    def test_store_result_is_noop_when_key_is_already_done(self):
        """store_result must not overwrite an existing DONE result."""
        k = self._k()
        self._run(self.store.check_and_lock(k, "h1"))
        self._run(self.store.store_result(k, "h1", {"id": "job-1"}, 200))
        # Second call with same hash must not change anything
        self._run(self.store.store_result(k, "h1", {"id": "job-overwrite"}, 200))
        action, body, _ = self._run(self.store.check_and_lock(k, "h1"))
        self.assertEqual(action, "hit")
        self.assertEqual(body["id"], "job-1", "store_result overwrote an existing DONE result")

    def test_different_users_keys_do_not_collide(self):
        """Two users using the same idempotency string get independent slots."""
        shared_key = str(uuid.uuid4())  # unique per run so TTL stale keys don't interfere
        k_alice = build_cache_key("alice", shared_key, "submit_job")
        k_bob = build_cache_key("bob", shared_key, "submit_job")
        self.assertNotEqual(k_alice, k_bob)

        self._run(self.store.check_and_lock(k_alice, "h1"))
        self._run(self.store.store_result(k_alice, "h1", {"id": "alice-job"}, 200))

        # Bob's slot is independent -- should proceed, not hit Alice's result
        action, _, _ = self._run(self.store.check_and_lock(k_bob, "h1"))
        self.assertEqual(action, "proceed")


class TestRedisHTTP(unittest.TestCase):
    """HTTP integration tests with real Redis backing the store.

    All tests use AsyncClient inside asyncio.run() so the Redis store
    and the HTTP client share the same event loop. TestClient spins up
    its own anyio event loop per-request, which breaks aioredis connections
    created outside that loop.
    """

    @classmethod
    def setUpClass(cls):
        _check_redis()

        async def get_resource_id():
            async with AsyncClient(transport=ASGITransport(app=APP), base_url="http://test") as client:
                resp = await client.get(f"{_BASE}/status/resources")
                assert resp.status_code == 200
                return resp.json()[0]["id"]

        cls.resource_id = asyncio.run(get_resource_id())

    def _run(self, coro_fn):
        """Run coro_fn(client) inside a single event loop with a fresh Redis store."""
        async def run():
            store = RedisIdempotencyStore(_REDIS_URL, ttl=60)
            APP.state.idempotency_store = store
            try:
                async with AsyncClient(transport=ASGITransport(app=APP), base_url="http://test") as client:
                    return await coro_fn(client)
            finally:
                await store.close()
        return asyncio.run(run())

    def test_first_submit_is_miss(self):
        async def t(client):
            resp = await client.post(
                f"{_BASE}/compute/job/{self.resource_id}",
                headers={**_HEADERS, "Idempotency-Key": str(uuid.uuid4())},
                json=_BODY,
            )
            assert resp.status_code == 200
            assert resp.headers.get("Idempotency-Key-Reply") == "miss"
        self._run(t)

    def test_ten_sequential_retries_all_return_same_job_id(self):
        """10 retries must all return hit with the same body as the first response."""
        async def t(client):
            key = str(uuid.uuid4())
            url = f"{_BASE}/compute/job/{self.resource_id}"
            headers = {**_HEADERS, "Idempotency-Key": key}

            first = await client.post(url, headers=headers, json=_BODY)
            assert first.status_code == 200
            job_id = first.json()["id"]

            for i in range(10):
                resp = await client.post(url, headers=headers, json=_BODY)
                assert resp.status_code == 200, f"retry {i} not 200"
                assert resp.headers.get("Idempotency-Key-Reply") == "hit", f"retry {i} not hit"
                assert resp.json()["id"] == job_id, f"retry {i} returned different job ID"
        self._run(t)

    def test_five_independent_keys_each_go_to_adapter(self):
        """5 different idempotency keys each produce a miss (each reaches the adapter)."""
        async def t(client):
            url = f"{_BASE}/compute/job/{self.resource_id}"
            for _ in range(5):
                resp = await client.post(url, headers={**_HEADERS, "Idempotency-Key": str(uuid.uuid4())}, json=_BODY)
                assert resp.status_code == 200
                assert resp.headers.get("Idempotency-Key-Reply") == "miss"
        self._run(t)

    def test_fingerprint_mismatch_returns_422(self):
        async def t(client):
            key = str(uuid.uuid4())
            url = f"{_BASE}/compute/job/{self.resource_id}"
            await client.post(url, headers={**_HEADERS, "Idempotency-Key": key}, json=_BODY)
            resp = await client.post(url, headers={**_HEADERS, "Idempotency-Key": key}, json={**_BODY, "arguments": ["different"]})
            assert resp.status_code == 422
        self._run(t)

    def test_no_key_always_reaches_adapter(self):
        """Without a key every call goes to the adapter -- response has no cache header."""
        async def t(client):
            url = f"{_BASE}/compute/job/{self.resource_id}"
            for _ in range(3):
                resp = await client.post(url, headers=_HEADERS, json=_BODY)
                assert resp.status_code == 200
                assert "Idempotency-Key-Reply" not in resp.headers
        self._run(t)

    def test_update_job_retry_returns_cached_response(self):
        """update_job retries cache correctly."""
        async def t(client):
            submit = await client.post(f"{_BASE}/compute/job/{self.resource_id}", headers=_HEADERS, json=_BODY)
            job_id = submit.json()["id"]

            key = str(uuid.uuid4())
            url = f"{_BASE}/compute/job/{self.resource_id}/{job_id}"
            headers = {**_HEADERS, "Idempotency-Key": key}

            first = await client.put(url, headers=headers, json=_BODY)
            second = await client.put(url, headers=headers, json=_BODY)

            assert first.status_code == 200
            assert second.headers.get("Idempotency-Key-Reply") == "hit"
            assert first.json()["id"] == second.json()["id"]
        self._run(t)


class TestConcurrent(unittest.TestCase):
    """Concurrent requests via asyncio.gather + httpx.AsyncClient.

    Each test creates its own event loop (asyncio.run) and a fresh Redis
    store inside that loop so aioredis connections are loop-consistent.
    """

    @classmethod
    def setUpClass(cls):
        _check_redis()
        cls.resource_id = _resource_id()

    async def _submit_n_same_key(self, key: str, n: int):
        store = RedisIdempotencyStore(_REDIS_URL, ttl=60)
        APP.state.idempotency_store = store
        url = f"{_BASE}/compute/job/{self.resource_id}"
        headers = {**_HEADERS, "Idempotency-Key": key}
        try:
            async with AsyncClient(transport=ASGITransport(app=APP), base_url="http://test") as client:
                tasks = [client.post(url, headers=headers, json=_BODY) for _ in range(n)]
                return await asyncio.gather(*tasks)
        finally:
            await store.close()

    def test_concurrent_same_key_exactly_one_miss(self):
        """N concurrent requests with the same key: exactly 1 miss, rest conflict or hit."""
        key = str(uuid.uuid4())
        responses = asyncio.run(self._submit_n_same_key(key, n=8))

        misses = [r for r in responses if r.headers.get("Idempotency-Key-Reply") == "miss"]
        hits = [r for r in responses if r.headers.get("Idempotency-Key-Reply") == "hit"]
        conflicts = [r for r in responses if r.status_code == 409]

        self.assertEqual(len(misses), 1, f"Expected 1 miss, got {len(misses)}: {[r.headers.get('Idempotency-Key-Reply') for r in responses]}")
        self.assertEqual(len(misses) + len(hits) + len(conflicts), 8)

        # Every 200 response must carry the same job ID
        job_ids = {r.json()["id"] for r in responses if r.status_code == 200}
        self.assertEqual(len(job_ids), 1, f"Concurrent submissions produced multiple job IDs: {job_ids}")

    def test_concurrent_different_keys_all_miss(self):
        """N concurrent requests with distinct keys: all independent misses."""
        async def run():
            store = RedisIdempotencyStore(_REDIS_URL, ttl=60)
            APP.state.idempotency_store = store
            try:
                async with AsyncClient(transport=ASGITransport(app=APP), base_url="http://test") as client:
                    url = f"{_BASE}/compute/job/{self.resource_id}"
                    tasks = [
                        client.post(url, headers={**_HEADERS, "Idempotency-Key": str(uuid.uuid4())}, json=_BODY)
                        for _ in range(6)
                    ]
                    return await asyncio.gather(*tasks)
            finally:
                await store.close()

        responses = asyncio.run(run())
        self.assertTrue(all(r.status_code == 200 for r in responses))
        # Every unique key must have reached the adapter (miss, not hit)
        self.assertTrue(all(r.headers.get("Idempotency-Key-Reply") == "miss" for r in responses))

    def test_concurrent_burst_then_sequential_retries_all_hit(self):
        """After a concurrent burst, all sequential retries return the same cached response."""
        key = str(uuid.uuid4())

        # First: 4 concurrent requests
        first_batch = asyncio.run(self._submit_n_same_key(key, n=4))
        ok_responses = [r for r in first_batch if r.status_code == 200]
        self.assertGreaterEqual(len(ok_responses), 1)
        expected_job_id = ok_responses[0].json()["id"]

        # Second: 5 sequential retries in a fresh event loop with a fresh store.
        # Must all be hits returning the same cached response.
        async def retries():
            store = RedisIdempotencyStore(_REDIS_URL, ttl=60)
            APP.state.idempotency_store = store
            try:
                async with AsyncClient(transport=ASGITransport(app=APP), base_url="http://test") as client:
                    url = f"{_BASE}/compute/job/{self.resource_id}"
                    headers = {**_HEADERS, "Idempotency-Key": key}
                    for i in range(5):
                        resp = await client.post(url, headers=headers, json=_BODY)
                        assert resp.status_code == 200, f"sequential retry {i}"
                        assert resp.headers.get("Idempotency-Key-Reply") == "hit", f"sequential retry {i} not hit"
                        assert resp.json()["id"] == expected_job_id, f"sequential retry {i} wrong job ID"
            finally:
                await store.close()

        asyncio.run(retries())

    def test_concurrent_same_key_all_200s_agree_on_job_id(self):
        """Any request that gets a 200 (miss or hit) must carry the same job ID.

        Verifies the 'exactly once' semantic end-to-end: even under concurrency
        the adapter is called only once, and all retries see that one result.
        """
        key = str(uuid.uuid4())
        # Two separate concurrent bursts to also exercise the 'already DONE' path
        first_batch = asyncio.run(self._submit_n_same_key(key, n=5))
        second_batch = asyncio.run(self._submit_n_same_key(key, n=5))

        all_responses = first_batch + second_batch
        all_200s = [r for r in all_responses if r.status_code == 200]
        job_ids = {r.json()["id"] for r in all_200s}
        self.assertEqual(len(job_ids), 1, f"All 200 responses must agree on one job ID, got: {job_ids}")

        # First batch must have exactly one miss
        misses = [r for r in first_batch if r.headers.get("Idempotency-Key-Reply") == "miss"]
        self.assertEqual(len(misses), 1)
        # Second batch must be all hits (key is already DONE)
        second_hits = [r for r in second_batch if r.headers.get("Idempotency-Key-Reply") == "hit"]
        self.assertEqual(len(second_hits), 5)


if __name__ == "__main__":
    unittest.main()
