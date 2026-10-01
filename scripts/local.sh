#!/usr/bin/env bash
# Fallback when Docker isn't available: run every service as a local process (Ctrl+C stops them all).
# The gateway runs with uvx and reads provider keys from .env, like the compose service does.
set -euo pipefail
cd "$(dirname "$0")/.."
trap 'kill 0' EXIT

[ "${NO_GATEWAY:-}" ] || uvx --env-file .env --from 'litellm[proxy]' litellm --config gateway/litellm.yaml --port 4400 &
uv run uvicorn dataproducts.app:app --port 8001 --log-level warning &
uv run python -m skills.instrument_context &
uv run python -m skills.manuals &
uv run python -m skills.parts &
PARTS_SKILL_VERSION=0.4 PORT=8113 uv run python -m skills.parts &   # sandbox candidate for SC7
uv run python -m agents.scheduling.agent &
wait
