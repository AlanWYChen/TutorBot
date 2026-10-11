#!/usr/bin/env bash
# Synthetic-only storage restart and lost-broker gate; restore services on failures.
set -euo pipefail
compose=(docker compose --env-file .env -f infra/compose/compose.yaml)
probe_run="$(date +%s)-$$"
restore() {
  "${compose[@]}" up --no-build -d --wait --wait-timeout 120 redis runtime-worker runtime-relay >/dev/null
}
trap restore EXIT
"${compose[@]}" run --rm --no-deps --build -e RUN_PRIVATE_IO_INTEGRATION=1 api-checks pytest tests/test_private_io_integration.py
"${compose[@]}" stop runtime-worker runtime-relay redis
"${compose[@]}" exec -T api python -m scripts.storage_restart_probe prepare "$probe_run"
"${compose[@]}" restart storage api
restore
"${compose[@]}" exec -T api python -m scripts.storage_restart_probe check "$probe_run"
"${compose[@]}" exec -T api python -m scripts.storage_restart_probe cleanup "$probe_run"
"${compose[@]}" restart storage
"${compose[@]}" exec -T api python -m scripts.storage_restart_probe deleted "$probe_run"
