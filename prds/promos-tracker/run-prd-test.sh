#!/usr/bin/env bash
# Definition of done for promos-tracker. The harness checks only the exit code.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

BACKEND_PORT="${PORT:-8099}"
PY="$REPO_ROOT/backend/venv/bin/python3"

# ---------------------------------------------------------------------------
# 1. Backend modules import cleanly (static check — new/changed files).
# ---------------------------------------------------------------------------
echo "--- Checking backend modules import ---"
( cd backend && "$PY" -c "
import config, models.schemas, services.promos_db, routers.promos, main
print('OK — config, schemas, promos_db, routers.promos, main all import cleanly')
" )

# ---------------------------------------------------------------------------
# 2. Frontend Promos page exists and is actually wired into routing/nav — a
#    clean build alone wouldn't catch a page that was simply never added.
# ---------------------------------------------------------------------------
echo "--- Checking Promos page exists and is wired into routing ---"
[[ -f frontend/src/pages/Promos.jsx ]] \
  || { echo "missing frontend/src/pages/Promos.jsx" >&2; exit 1; }
[[ -f frontend/src/utils/promos.js ]] \
  || { echo "missing frontend/src/utils/promos.js" >&2; exit 1; }
grep -q 'path="/promos"' frontend/src/App.jsx \
  || { echo "App.jsx does not route /promos" >&2; exit 1; }
grep -q '"/promos"' frontend/src/components/Navbar.jsx \
  || { echo "Navbar.jsx does not link /promos" >&2; exit 1; }

echo "--- Checking frontend build ---"
( cd frontend && npm run build --silent )

# ---------------------------------------------------------------------------
# 3. Pure sort/flag logic (frontend/src/utils/promos.js) — no browser needed.
# ---------------------------------------------------------------------------
echo "--- Checking sortByExpiry / isExpiringSoon ---"
node --input-type=module -e "
import { sortByExpiry, isExpiringSoon } from '$REPO_ROOT/frontend/src/utils/promos.js';
import assert from 'node:assert';

const now = new Date('2026-10-19T00:00:00Z');

const promos = [
  { id: 1, status: 'available', expiry_date: '2026-11-01' },
  { id: 2, status: 'available', expiry_date: '2026-10-20' },
  { id: 3, status: 'available', expiry_date: '2026-10-25' },
];
const sorted = sortByExpiry(promos);
assert.deepStrictEqual(sorted.map((p) => p.id), [2, 3, 1], 'sortByExpiry did not sort soonest-first');

assert.strictEqual(isExpiringSoon({ status: 'available', expiry_date: '2026-10-20' }, now), true, 'promo 1 day out should be flagged');
assert.strictEqual(isExpiringSoon({ status: 'available', expiry_date: '2026-11-01' }, now), false, 'promo weeks out should not be flagged');
assert.strictEqual(isExpiringSoon({ status: 'used', expiry_date: '2026-10-20' }, now), false, 'a used promo should not be flagged even if expiry is near');

console.log('OK — sortByExpiry and isExpiringSoon behave correctly');
"

# ---------------------------------------------------------------------------
# 4. Promos.jsx actually wires the flag/sort logic into rendering (not just
#    defined-but-unused).
# ---------------------------------------------------------------------------
echo "--- Checking Promos.jsx wires sort/flag logic into the component ---"
grep -q "sortByExpiry" frontend/src/pages/Promos.jsx \
  || { echo "Promos.jsx does not call sortByExpiry" >&2; exit 1; }
grep -q "isExpiringSoon" frontend/src/pages/Promos.jsx \
  || { echo "Promos.jsx does not call isExpiringSoon" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 5. HTTP: create, list (+filter), update status, delete — against a temp
#    database, proving persistence is independent of cache.db.
# ---------------------------------------------------------------------------
echo "--- Checking promos HTTP API against a temp database ---"

if curl -sf "http://localhost:${BACKEND_PORT}/health" >/dev/null 2>&1; then
  echo "port ${BACKEND_PORT} is already serving something (not started by this runner) — set PORT to a free port" >&2
  exit 1
fi

TMP_DB="$(mktemp -u /tmp/promos-tracker-test-XXXXXX.db)"
cleanup() {
  if [[ -n "${SERVER_PID:-}" ]]; then kill "$SERVER_PID" 2>/dev/null || true; fi
  pkill -f "uvicorn main:app --port $BACKEND_PORT" 2>/dev/null || true
  rm -f "$TMP_DB"
}
trap cleanup EXIT

( cd backend && PROMOS_DB_PATH="$TMP_DB" "$PY" -m uvicorn main:app --port "$BACKEND_PORT" >/tmp/promos-tracker-backend.log 2>&1 & )

for _ in $(seq 1 30); do
  if curl -sf "http://localhost:${BACKEND_PORT}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
if ! curl -sf "http://localhost:${BACKEND_PORT}/health" >/dev/null 2>&1; then
  echo "backend never came up on :${BACKEND_PORT} — see /tmp/promos-tracker-backend.log" >&2
  cat /tmp/promos-tracker-backend.log >&2 || true
  exit 1
fi

if [[ -f "$TMP_DB" ]]; then
  echo "temp db $TMP_DB already existed before any promo was created — not isolated" >&2
  exit 1
fi

# --- create ---
create_code=$(curl -s -o /tmp/promos-tracker-create.json -w '%{http_code}' \
  -X POST "http://localhost:${BACKEND_PORT}/api/v1/promos" \
  -H "Content-Type: application/json" \
  -d '{"sportsbook":"DraftKings","promo_type":"signup_bonus","amount":"$50 free bet","expiry_date":"2026-10-20"}')
if [[ "$create_code" != "201" ]]; then
  echo "POST /api/v1/promos returned $create_code, expected 201" >&2
  cat /tmp/promos-tracker-create.json >&2 || true
  exit 1
fi

"$PY" - <<'PYEOF'
import json, sys
with open("/tmp/promos-tracker-create.json") as fh:
    data = json.load(fh)
assert data["status"] == "available", f"new promo should default to available, got {data['status']}"
assert isinstance(data["id"], int), "created promo missing integer id"
print(f"OK — created promo id={data['id']}")
PYEOF

PROMO_ID=$("$PY" -c "import json; print(json.load(open('/tmp/promos-tracker-create.json'))['id'])")

if [[ ! -f "$TMP_DB" ]]; then
  echo "temp db $TMP_DB was not created after POST — not persisting to the configured path" >&2
  exit 1
fi

# A second promo, already expired, to prove the status filter actually narrows.
curl -sf -X POST "http://localhost:${BACKEND_PORT}/api/v1/promos" \
  -H "Content-Type: application/json" \
  -d '{"sportsbook":"FanDuel","promo_type":"odds_boost","amount":"50% boost","expiry_date":"2020-01-01"}' >/dev/null

# --- list, sorted soonest-expiry-first ---
list_body=$(curl -sf "http://localhost:${BACKEND_PORT}/api/v1/promos")
echo "$list_body" | "$PY" -c "
import json, sys
data = json.load(sys.stdin)
promos = data['promos']
assert len(promos) == 2, f'expected 2 promos, got {len(promos)}'
dates = [p['expiry_date'] for p in promos]
assert dates == sorted(dates), f'promos not sorted soonest-expiry-first: {dates}'
print('OK — list returns both promos sorted soonest-expiry-first')
"

# --- filter by status ---
filtered_body=$(curl -sf "http://localhost:${BACKEND_PORT}/api/v1/promos?status=available")
echo "$filtered_body" | "$PY" -c "
import json, sys
data = json.load(sys.stdin)
assert data['count'] == 2, f'both seeded promos are available, expected count=2, got {data[\"count\"]}'
"

# --- update status (PATCH) ---
patch_code=$(curl -s -o /tmp/promos-tracker-patch.json -w '%{http_code}' \
  -X PATCH "http://localhost:${BACKEND_PORT}/api/v1/promos/${PROMO_ID}" \
  -H "Content-Type: application/json" \
  -d '{"status":"used"}')
if [[ "$patch_code" != "200" ]]; then
  echo "PATCH /api/v1/promos/${PROMO_ID} returned $patch_code, expected 200" >&2
  cat /tmp/promos-tracker-patch.json >&2 || true
  exit 1
fi
"$PY" -c "
import json
data = json.load(open('/tmp/promos-tracker-patch.json'))
assert data['status'] == 'used', f\"expected status=used, got {data['status']}\"
"

# Status change visible on a subsequent GET.
after_patch=$(curl -sf "http://localhost:${BACKEND_PORT}/api/v1/promos?status=used")
echo "$after_patch" | "$PY" -c "
import json, sys
data = json.load(sys.stdin)
assert data['count'] == 1, f'expected exactly 1 used promo after PATCH, got {data[\"count\"]}'
"

# PATCH on a nonexistent id -> 404
missing_patch_code=$(curl -s -o /dev/null -w '%{http_code}' \
  -X PATCH "http://localhost:${BACKEND_PORT}/api/v1/promos/999999" \
  -H "Content-Type: application/json" -d '{"status":"used"}')
[[ "$missing_patch_code" == "404" ]] || { echo "PATCH on missing id returned $missing_patch_code, expected 404" >&2; exit 1; }

# --- delete ---
delete_code=$(curl -s -o /dev/null -w '%{http_code}' \
  -X DELETE "http://localhost:${BACKEND_PORT}/api/v1/promos/${PROMO_ID}")
[[ "$delete_code" == "204" ]] || { echo "DELETE /api/v1/promos/${PROMO_ID} returned $delete_code, expected 204" >&2; exit 1; }

after_delete=$(curl -sf "http://localhost:${BACKEND_PORT}/api/v1/promos")
echo "$after_delete" | "$PY" -c "
import json, sys
data = json.load(sys.stdin)
assert data['count'] == 1, f'expected 1 promo remaining after delete, got {data[\"count\"]}'
assert all(p['id'] != $PROMO_ID for p in data['promos']), 'deleted promo still present in list'
"

# DELETE on a nonexistent id -> 404
missing_delete_code=$(curl -s -o /dev/null -w '%{http_code}' \
  -X DELETE "http://localhost:${BACKEND_PORT}/api/v1/promos/999999")
[[ "$missing_delete_code" == "404" ]] || { echo "DELETE on missing id returned $missing_delete_code, expected 404" >&2; exit 1; }

echo "OK — create/list/filter/update/delete all verified against a temp database ($TMP_DB)"

echo "--- ALL CHECKS PASSED ---"
