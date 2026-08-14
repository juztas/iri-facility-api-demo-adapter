"""Shared test wiring for the demo adapter suite.

Set every IRI_API_ADAPTER_<domain> to the combined demo adapter and configure the
in-memory idempotency store *before* any test imports app.main, so IriRouter loads
real adapters at construction time (the library no longer ships a demo fallback).
"""
import os

_COMBINED = "demo_adapter.combined.DemoAdapter"
for _domain in ("facility", "status", "account", "compute", "filesystem", "storage", "task"):
    os.environ.setdefault(f"IRI_API_ADAPTER_{_domain}", _COMBINED)

os.environ.setdefault("IRI_IDEMPOTENCY_STORE", "demo_adapter.compute.idempotency.InMemoryIdempotencyStore")
