FROM python:3.13

RUN pip install -U pip wheel setuptools && pip install uv

COPY . /app
WORKDIR /app

RUN uv pip install --system .

# Out-of-the-box, every domain is wired to this repo's demo adapter so the
# whole API works immediately. Override one IRI_API_ADAPTER_<domain> line at
# a time to swap in your facility's real implementation -- see the README.
ENV IRI_API_ADAPTER_facility="demo_adapter.facility.adapter.FacilityDemoAdapter"
ENV IRI_API_ADAPTER_status="demo_adapter.status.adapter.StatusDemoAdapter"
ENV IRI_API_ADAPTER_account="demo_adapter.account.adapter.AccountDemoAdapter"
ENV IRI_API_ADAPTER_compute="demo_adapter.compute.adapter.ComputeDemoAdapter"
ENV IRI_API_ADAPTER_filesystem="demo_adapter.filesystem.adapter.FilesystemDemoAdapter"
ENV IRI_API_ADAPTER_storage="demo_adapter.storage.adapter.StorageDemoAdapter"
ENV IRI_API_ADAPTER_task="demo_adapter.task.adapter.TaskDemoAdapter"
# The library ships no built-in idempotency store; wire the demo in-memory one so
# Idempotency-Key requests work out of the box (single-instance; not for production).
ENV IRI_IDEMPOTENCY_STORE="demo_adapter.compute.idempotency.InMemoryIdempotencyStore"
ENV API_URL_ROOT="http://localhost:8000"

CMD ["uvicorn", "app.main:APP", "--host", "0.0.0.0", "--port", "8000"]
