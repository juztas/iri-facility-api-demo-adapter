# iri-facility-api-demo-adapter

A per-domain, copy-from-here starter kit for facilities onboarding to the [IRI Facility API](https://iri.science/).

[`iri-facility-api-python`](https://github.com/doe-iri/iri-facility-api-python) ships a reference FastAPI implementation of the API plus a single `DemoAdapter` class that fakes all 7 domains (facility, status, account, compute, filesystem, storage, task) at once. That's great for a five-minute demo, but not a great starting point for a real facility: there's nothing to fork per domain, and the domains aren't independently swappable.

This repo is the same demo behavior, split into one module per domain, so you can:

1. Run the whole thing out of the box and get the identical demo experience.
2. Replace **one domain at a time** (most commonly `compute` and `filesystem`, since those are the ones that need real scheduler/filesystem integration) with your facility's real logic, while everything else keeps running off demo data.

This repo does not modify or get depended on by `iri-facility-api-python` — it's a separate, standalone package that depends on it.

## Quickstart (Docker)

```bash
docker build -t iri-demo-adapter .
docker run -p 8000:8000 iri-demo-adapter
```

Visit [http://127.0.0.1:8000/api/v2](http://127.0.0.1:8000/api/v2) for the docs, or call it directly:

```bash
curl -H "Authorization: Bearer 12345" http://127.0.0.1:8000/api/v2/facility
```

(`12345` is the demo adapter's hardcoded API key, resolving to the fake user `gtorok` — see [demo_adapter/common.py](demo_adapter/common.py).)

## The 7 domains

Each domain is independently wired via its own `IRI_API_ADAPTER_<domain>` environment variable (see the [upstream README](https://github.com/doe-iri/iri-facility-api-python#environment-variables) for how that mechanism works). The Dockerfile wires all 7 to this repo's demo classes by default:

| Domain | Env var | Upstream ABC | Demo class |
|---|---|---|---|
| facility | `IRI_API_ADAPTER_facility` | `app.routers.facility.facility_adapter.FacilityAdapter` | [`demo_adapter.facility.adapter.FacilityDemoAdapter`](demo_adapter/facility/adapter.py) |
| status | `IRI_API_ADAPTER_status` | `app.routers.status.facility_adapter.FacilityAdapter` | [`demo_adapter.status.adapter.StatusDemoAdapter`](demo_adapter/status/adapter.py) |
| account | `IRI_API_ADAPTER_account` | `app.routers.account.facility_adapter.FacilityAdapter` | [`demo_adapter.account.adapter.AccountDemoAdapter`](demo_adapter/account/adapter.py) |
| compute | `IRI_API_ADAPTER_compute` | `app.routers.compute.facility_adapter.FacilityAdapter` | [`demo_adapter.compute.adapter.ComputeDemoAdapter`](demo_adapter/compute/adapter.py) |
| filesystem | `IRI_API_ADAPTER_filesystem` | `app.routers.filesystem.facility_adapter.FacilityAdapter` | [`demo_adapter.filesystem.adapter.FilesystemDemoAdapter`](demo_adapter/filesystem/adapter.py) |
| storage | `IRI_API_ADAPTER_storage` | `app.routers.storage.facility_adapter.FacilityAdapter` | [`demo_adapter.storage.adapter.StorageDemoAdapter`](demo_adapter/storage/adapter.py) |
| task | `IRI_API_ADAPTER_task` | `app.routers.task.facility_adapter.FacilityAdapter` | [`demo_adapter.task.adapter.TaskDemoAdapter`](demo_adapter/task/adapter.py) |

A [`demo_adapter.combined.DemoAdapter`](demo_adapter/combined.py) class is also provided, combining all 7 into one -- equivalent to the original monolith, useful if you just want the full demo under one class name.

### Shared demo data and auth

All 7 classes read from one shared, read-only `STATE` object ([demo_adapter/state.py](demo_adapter/state.py)) so the fake world stays consistent across domains (e.g. `status`'s resources reference `facility`'s site ids, `storage`'s locations are keyed by `status`'s resource ids). They also all mix in [`DemoAuthMixin`](demo_adapter/common.py) for the `get_current_user`/`get_current_user_globus`/`get_user` methods every domain's ABC requires -- every demo class resolves auth to the same fake user, `gtorok`.

If you write your own adapter and mix in `DemoAuthMixin` alongside an upstream ABC that extends `AuthenticatedAdapter` (account, compute, filesystem, storage, task all do; facility and status don't), **list the mixin first**: `class MyAdapter(DemoAuthMixin, facility_adapter.FacilityAdapter)`, not the other way around. Python resolves methods left-to-right through the MRO, and `AuthenticatedAdapter` declares those same three methods as abstract -- if it comes first, Python finds the abstract version before it finds your mixin's concrete one, and the class becomes impossible to instantiate.

## Overriding one domain

This is the actual point of the split. Say your facility has a real Slurm-backed `compute` implementation but is happy with demo data everywhere else:

1. Copy `demo_adapter/compute/` into your own package (e.g. `myfacility/compute/`) as a starting point.
2. Implement it against `app.routers.compute.facility_adapter.FacilityAdapter` with your real logic.
3. In your Dockerfile (extending this image, or built fresh), change just one line:

```Dockerfile
FROM iri-demo-adapter
COPY ./myfacility /app/myfacility/
ENV IRI_API_ADAPTER_compute="myfacility.compute.adapter.ComputeAdapter"
```

The other 6 `IRI_API_ADAPTER_*` env vars stay pointed at `demo_adapter.*`, so `facility`, `status`, `account`, `filesystem`, `storage`, and `task` keep working off demo data while only `compute` reflects real behavior. Repeat per domain as you build out real implementations.

## Local development

```bash
make
```

This creates a venv, installs the package (which pulls in `iri-api-python` per its git dependency), and runs `uvicorn app.main:APP --reload` with all 7 `IRI_API_ADAPTER_*` vars pointed at the demo classes -- same as the Dockerfile, but with reload-on-change. Logs go to stdout and `runtime-logs.log` (override with `IRI_LOG_FILE`/`LOG_FILE`). Source a `local.env` file for any local overrides; it's picked up automatically if present.

Equivalent by hand, if you don't have `make`:

```bash
uv sync
uv run uvicorn app.main:APP --reload --port 8000
```

`app.main:APP` resolves because `iri-api-python` is a normal dependency (see `pyproject.toml`) -- there's no local copy of `app/` in this repo.

Other targets: `make redis` (starts a local Redis container for `RedisIdempotencyStore` and prints the env vars to wire it up), `make lint` (ruff + pylint + bandit + pip-audit), `make clean` (removes the venv and the filesystem sandbox).

If `make`/`uv sync` fails trying to build `cryptography` from source (a transitive dependency via `globus-sdk`), that means no prebuilt wheel was available for your exact platform/Python combination -- this is unrelated to this repo's code (the upstream repo pulls in the same dependency). Easiest fix is to just use Docker; alternatively install a matching Rust toolchain (`rustup target add <your-target>`) so the source build succeeds.

AmSC-internal contributors with `iri-facility-api-python` checked out as a sibling directory can iterate against local changes to that repo without pushing first, via a local (uncommitted) `uv.toml`:

```toml
[sources]
iri-api-python = { path = "../iri-facility-api-python", editable = true }
```

The committed default in `pyproject.toml` stays a git dependency, so this repo works standalone for any site that only clones this one.

## Everything else

For anything not specific to this split (OpenTelemetry, the idempotency store, `IRI_SHOW_MISSING_ROUTES`, Globus auth, the `X-IRI-Facility-Project` header), see the [iri-facility-api-python README](https://github.com/doe-iri/iri-facility-api-python#readme) -- none of that changes here. The only addition this repo makes on top is `demo_adapter.compute.idempotency.RedisIdempotencyStore` / `InMemoryIdempotencyStore`, equivalent to the upstream demo's idempotency stores, usable via `IRI_IDEMPOTENCY_STORE=demo_adapter.compute.idempotency.RedisIdempotencyStore`.
