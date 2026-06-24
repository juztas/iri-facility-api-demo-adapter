PYTHON      := python3.13
VENV        := .venv
BIN         := $(VENV)/bin
UV          := uv
LOG_FILE    := runtime-logs.log
IRI_LOG_FILE ?= $(LOG_FILE)
LOG_ROTATION_DAYS := 5
IRI_LOG_ROTATION_DAYS ?= $(LOG_ROTATION_DAYS)

STAMP_VENV  := $(VENV)/.created
STAMP_DEPS  := $(VENV)/.deps

.DEFAULT_GOAL := dev

.PHONY: deps dev test redis redis-stop redis-clean clean format ruff pylint audit bandit lint

$(STAMP_VENV):
	$(UV) venv $(VENV)
	touch $(STAMP_VENV)

.venv: $(STAMP_VENV)

$(STAMP_DEPS): $(STAMP_VENV) pyproject.toml
	$(UV) pip install --python $(BIN)/python -e .
	$(UV) pip install --python $(BIN)/python \
		ruff \
		pylint \
		bandit \
		pytest
	touch $(STAMP_DEPS)

deps: $(STAMP_DEPS)

dev: deps
	@source $(BIN)/activate && \
	[ -f local.env ] && source local.env || true && \
	IRI_API_ADAPTER_facility=demo_adapter.facility.adapter.FacilityDemoAdapter \
	IRI_API_ADAPTER_status=demo_adapter.status.adapter.StatusDemoAdapter \
	IRI_API_ADAPTER_account=demo_adapter.account.adapter.AccountDemoAdapter \
	IRI_API_ADAPTER_compute=demo_adapter.compute.adapter.ComputeDemoAdapter \
	IRI_API_ADAPTER_filesystem=demo_adapter.filesystem.adapter.FilesystemDemoAdapter \
	IRI_API_ADAPTER_storage=demo_adapter.storage.adapter.StorageDemoAdapter \
	IRI_API_ADAPTER_task=demo_adapter.task.adapter.TaskDemoAdapter \
	IRI_LOG_FILE="$${IRI_LOG_FILE:-$${LOG_FILE:-$(IRI_LOG_FILE)}}" \
	IRI_LOG_ROTATION_DAYS="$${IRI_LOG_ROTATION_DAYS:-$${LOG_ROTATION_DAYS:-$(IRI_LOG_ROTATION_DAYS)}}" \
	IRI_IDEMPOTENCY_STORE=demo_adapter.compute.idempotency.InMemoryIdempotencyStore \
	DEMO_QUEUE_UPDATE_SECS=2 \
	OPENTELEMETRY_ENABLED=true \
	API_URL_ROOT='http://localhost:8000' uvicorn app.main:APP --reload --port 8000

test: deps ## Run unit tests (test_filesystem.py is a live script, excluded via pyproject)
	$(BIN)/python -m pytest test/ -v

REDIS_PORT      ?= 6379
REDIS_CONTAINER := iri-demo-adapter-redis

redis: ## Start a local Redis container for idempotency (dev only)
	docker run -d --name $(REDIS_CONTAINER) -p $(REDIS_PORT):6379 redis:7-alpine 2>/dev/null || \
		docker start $(REDIS_CONTAINER) 2>/dev/null || true
	@echo "Redis running on localhost:$(REDIS_PORT)"
	@echo "Add to local.env:"
	@echo "  export REDIS_URL=redis://localhost:$(REDIS_PORT)"
	@echo "  export IRI_IDEMPOTENCY_STORE=demo_adapter.compute.idempotency.RedisIdempotencyStore"
	@echo "  export IDEMPOTENCY_TTL_SECONDS=86400  # cache TTL (default: 24h)"
	@echo "  export LOCK_TTL_SECONDS=60            # in-flight lock TTL (default: 60s)"

redis-stop: ## Stop the local Redis container
	docker stop $(REDIS_CONTAINER) 2>/dev/null || true

redis-clean: ## Stop and remove the local Redis container
	docker rm -f $(REDIS_CONTAINER) 2>/dev/null || true

clean:
	rm -rf iri_sandbox
	rm -rf .venv

# Format and lint
format: deps
	$(BIN)/ruff format --line-length 200 .

ruff: deps
	$(BIN)/ruff check . --fix || true

pylint: deps
	find . -path ./$(VENV) -prune -o -type f -name "*.py" -print0 | while IFS= read -r -d '' f; do \
		echo "Pylint $$f"; \
		$(BIN)/pylint $$f || true; \
	done

# Security
audit: deps
	uv pip compile pyproject.toml -o requirements.txt
	uv pip sync requirements.txt
	uv pip install pip-audit
	$(BIN)/pip-audit || true
	rm -f requirements.txt

bandit: deps
	$(BIN)/bandit -r demo_adapter || true

# Full validation bundle
lint: clean format ruff pylint audit bandit
