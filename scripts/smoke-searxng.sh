#!/usr/bin/env bash
set -euo pipefail

compose=(docker compose -f docker-compose.dev.yml)
compose_name="${COMPOSE_FILE:-docker-compose.dev.yml}"
if [ -n "${compose_name}" ] && [ "${compose_name}" != "docker-compose.dev.yml" ]; then
  compose=(docker compose -f "${compose_name}")
fi

cleanup() {
  "${compose[@]}" logs searxng > /tmp/quip-searxng.log 2>&1 || true
  "${compose[@]}" stop searxng >/dev/null 2>&1 || true
}
trap cleanup EXIT

"${compose[@]}" up -d searxng

for _ in $(seq 1 30); do
  if curl -fsS "${SEARXNG_TEST_URL:-http://127.0.0.1:8888}/search?q=quip&format=json" > /tmp/quip-searxng.json; then
    break
  fi
  sleep 1
done

python - <<'PY'
import json
from pathlib import Path

payload = json.loads(Path('/tmp/quip-searxng.json').read_text())
assert isinstance(payload.get('results'), list), payload
print(f"SearXNG JSON API OK: {len(payload['results'])} results")
PY
