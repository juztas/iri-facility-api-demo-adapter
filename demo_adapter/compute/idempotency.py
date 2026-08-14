"""Idempotency stores for compute submit_job/update_job, pluggable via IRI_IDEMPOTENCY_STORE.

These aren't part of the FacilityAdapter pattern -- they implement
app.idempotency.IdempotencyStore and are wired independently via the
IRI_IDEMPOTENCY_STORE env var (see app/idempotency.py upstream, which
already defaults to an in-memory store with no configuration needed).
They only matter for compute's submit/update idempotency caching, so they
live alongside the compute adapter.
"""
import json
import os
import time

import redis.asyncio as aioredis
from redis.exceptions import WatchError

from app.idempotency import IdempotencyStore

_LOCK_PREFIX = "LOCKED:"
_DONE_PREFIX = "DONE:"
_LOCK_TTL_SECONDS = int(os.environ.get("LOCK_TTL_SECONDS", 60))


class InMemoryIdempotencyStore(IdempotencyStore):
    """In-process dict store. NOT FOR PROD USE. Enable with:
      IRI_IDEMPOTENCY_STORE=demo_adapter.compute.idempotency.InMemoryIdempotencyStore
    """

    def __init__(self, ttl: int | None = None):
        self._ttl = ttl if ttl is not None else int(os.environ.get("IDEMPOTENCY_TTL_SECONDS", "86400"))
        self._data: dict[str, tuple[str, float]] = {}

    def _get(self, key: str) -> str | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del self._data[key]
            return None
        return value

    def _set(self, key: str, value: str, ttl: int) -> None:
        self._data[key] = (value, time.monotonic() + ttl)

    def _delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def check_and_lock(self, cache_key: str, body_hash: str) -> tuple[str, dict | None, int | None]:
        value = self._get(cache_key)

        if value is None:
            self._set(cache_key, f"{_LOCK_PREFIX}{body_hash}", _LOCK_TTL_SECONDS)
            return ("proceed", None, None)

        if value.startswith(_LOCK_PREFIX):
            return ("conflict", None, None)

        if value.startswith(_DONE_PREFIX):
            data = json.loads(value[len(_DONE_PREFIX):])
            if data["body_hash"] != body_hash:
                return ("fingerprint_mismatch", None, None)
            return ("hit", data["response_body"], data["response_status"])

        return ("conflict", None, None)

    async def store_result(self, cache_key: str, body_hash: str, response_body: dict, response_status: int) -> None:
        value = self._get(cache_key)
        if value != f"{_LOCK_PREFIX}{body_hash}":
            return
        data = {"body_hash": body_hash, "response_body": response_body, "response_status": response_status}
        self._set(cache_key, f"{_DONE_PREFIX}{json.dumps(data)}", self._ttl)

    async def delete_lock(self, cache_key: str) -> None:
        value = self._get(cache_key)
        if value and value.startswith(_LOCK_PREFIX):
            self._delete(cache_key)

    async def close(self) -> None:
        pass


class RedisIdempotencyStore(IdempotencyStore):
    """Redis-backed store. Enable with:
      IRI_IDEMPOTENCY_STORE=demo_adapter.compute.idempotency.RedisIdempotencyStore
    Requires: REDIS installed, REDIS_URL env var
    """

    def __init__(self, redis_url: str | None = None, ttl: int | None = None):
        _url = redis_url if redis_url is not None else os.environ.get("REDIS_URL", "")
        if not _url:
            raise ValueError("REDIS_URL must be set to use RedisIdempotencyStore")
        self._client = aioredis.from_url(_url, decode_responses=True)
        self._ttl = ttl if ttl is not None else int(os.environ.get("IDEMPOTENCY_TTL_SECONDS", "86400"))

    def _rkey(self, cache_key: str) -> str:
        return f"iri:idem:{cache_key}"

    async def check_and_lock(self, cache_key: str, body_hash: str) -> tuple[str, dict | None, int | None]:
        rkey = self._rkey(cache_key)
        lock_value = f"{_LOCK_PREFIX}{body_hash}"

        is_new = await self._client.set(rkey, lock_value, nx=True, ex=_LOCK_TTL_SECONDS)
        if is_new:
            return ("proceed", None, None)

        value = await self._client.get(rkey)
        if value is None:
            # Key expired between our SET NX and GET; try once more.
            is_new2 = await self._client.set(rkey, lock_value, nx=True, ex=_LOCK_TTL_SECONDS)
            if is_new2:
                return ("proceed", None, None)
            return ("conflict", None, None)

        if value.startswith(_LOCK_PREFIX):
            return ("conflict", None, None)

        if value.startswith(_DONE_PREFIX):
            data = json.loads(value[len(_DONE_PREFIX):])
            if data["body_hash"] != body_hash:
                return ("fingerprint_mismatch", None, None)
            return ("hit", data["response_body"], data["response_status"])

        return ("conflict", None, None)

    async def store_result(self, cache_key: str, body_hash: str, response_body: dict, response_status: int) -> None:
        """Write DONE only if we still own the lock, using WATCH/MULTI/EXEC optimistic locking."""
        rkey = self._rkey(cache_key)
        expected_lock = f"{_LOCK_PREFIX}{body_hash}"
        data = {"body_hash": body_hash, "response_body": response_body, "response_status": response_status}
        done_value = f"{_DONE_PREFIX}{json.dumps(data)}"

        async with self._client.pipeline() as pipe:
            try:
                await pipe.watch(rkey)
                if await pipe.get(rkey) != expected_lock:
                    await pipe.reset()
                    return
                pipe.multi()
                pipe.set(rkey, done_value, ex=self._ttl)
                await pipe.execute()
            except WatchError:
                pass  # key changed between watch and execute; another request owns it now

    async def delete_lock(self, cache_key: str) -> None:
        """Delete the lock only if it still holds a LOCKED: value, using WATCH/MULTI/EXEC."""
        rkey = self._rkey(cache_key)

        async with self._client.pipeline() as pipe:
            try:
                await pipe.watch(rkey)
                current = await pipe.get(rkey)
                if not (current and current.startswith(_LOCK_PREFIX)):
                    await pipe.reset()
                    return
                pipe.multi()
                pipe.delete(rkey)
                await pipe.execute()
            except WatchError:
                pass  # key changed between watch and execute; leave it alone

    async def close(self) -> None:
        await self._client.aclose()
