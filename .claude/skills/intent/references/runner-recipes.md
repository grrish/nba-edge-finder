# Runner recipes — building `run-prd-test.sh`

`run-prd-test.sh` is the executable definition of done. It exits **0 when the feature is
built**, non-zero otherwise. The harness contracts *only* on its exit code; its internals
are intentionally flexible. You draft it from the conversation and the Expert's patterns;
the human reviews it (never the reverse — P8).

## Shape

```bash
#!/usr/bin/env bash
# Definition of done for <feature>. The harness checks only the exit code.
set -euo pipefail

# --- Deterministic checks first (fast, cheap, unambiguous) ---
# --- LLM-as-judge on the fuzzy residue (cheap by default) ---
# --- or a project-native test, if that's how this project verifies ---
```

- `set -euo pipefail` so an unexpected error surfaces instead of a false pass.
- **Order checks cheap → expensive.** Deterministic checks gate the LLM-judge so the
  expensive call only runs once the basics hold. This also makes wrong-reason failures
  obvious during the right-reason loop.
- Print a one-line reason on each failure (`echo ... >&2; exit 1`) so the right-reason
  loop — and the implementing agent later — can see *why*.
- Keep it self-contained: anything it reads (fixtures, contracts, judge prompts) lives
  under `prds/<feature>/` and is committed alongside it.

## Recipe 1 — Deterministic checks

For crisp, binary criteria. Cheapest and most reliable; prefer these wherever the
criterion allows.

```bash
[[ -f app/search/page.tsx ]]            || { echo "missing app/search/page.tsx" >&2; exit 1; }
grep -q "export default" app/search/page.tsx || { echo "no default export" >&2; exit 1; }
npm run build --silent                  || { echo "build failed" >&2; exit 1; }

# A running endpoint:
npm run dev >/dev/null 2>&1 & SERVER=$!; trap 'kill $SERVER 2>/dev/null' EXIT
until curl -sf http://localhost:"${PORT:-3000}"/ >/dev/null; do sleep 0.5; done
code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${PORT:-3000}/search?q=hello")
[[ "$code" == "200" ]] || { echo "/search returned $code, expected 200" >&2; exit 1; }
```

Read the port from env (`${PORT:-3000}`) so the runner doesn't collide with the human's
dev server (a harness worktree may run concurrently).

## Recipe 2 — LLM-as-judge (for fuzzy criteria)

For criteria a snapshot can't pin down cleanly — "renders matching links", "message reads
like an instruction". Cheap by default: small model, low temperature, focused rubric,
observable-only.

```bash
exec claude -p "$(cat <<'EOF'
Start the dev server (npm run dev &) and wait for http://localhost:3000.

Verify all of:
1. GET /search?q=hello renders at least one <a> whose text contains "hello".
2. GET /search (no query) renders an instruction message and no results list.
3. The /search?q=hello HTML includes the matching title in view-source (SSR, not
   post-hydration).

Exit 0 only if all are true. Exit 1 with a one-line reason per failure. Use low
temperature; judge only what's observable, don't speculate.
EOF
)"
```

Or capture the judgement and gate on it (when deterministic checks must also run after):

```bash
verdict=$(claude -p --model claude-haiku-4-5 "<rubric>")
echo "$verdict" | grep -q '^PASS' || { echo "judge: $verdict" >&2; exit 1; }
```

Pin the model and keep the rubric tight — this is the only line item with real per-run
cost. Deterministic prefiltering should do the heavy lifting so the judge sees a small,
well-formed question.

## Recipe 3 — Project-native test

When the project already has a test framework and the criterion fits it, the runner can
just invoke a focused test that lives **under `prds/<feature>/`** (so the project's own
test discovery doesn't pick it up and go red on the PRD branch):

```bash
npx playwright test prds/<feature>/search.spec.ts --config prds/<feature>/pw.config.ts
# or: pytest prds/<feature>/test_search.py -q
```

Mirror whatever the Expert says this project uses. The runner is a thin wrapper; the
test file and its config are committed under `prds/<feature>/`.

## Recipe 4 — Conforming to a supplied contract

When the user brought an API contract / schema (Step 2), copy it under `prds/<feature>/`
and have the runner validate against it:

```bash
# OpenAPI/swagger conformance
npx @stoplight/spectral-cli lint prds/<feature>/api-contract.yaml >/dev/null \
  || { echo "contract invalid" >&2; exit 1; }
# then assert the running service matches it (e.g. schemathesis, dredd, or a
# focused check that the documented routes/shapes exist)
```

## This project's test idioms

Scanned: neither manifest has a test framework installed (no `pytest` in
`backend/requirements.txt`, no `vitest`/`jest` in `frontend/package.json`) and
there's no `.github/` CI. **Recipe 3 (project-native test) is not available
here today** — default to Recipe 1 (deterministic) and Recipe 2 (LLM-judge).
If a future feature is the one that adds a test framework, that's fine — note
it as a constraint in the PRD and Recipe 3 becomes available for the next one.

Known-good deterministic building blocks for this repo:

```bash
# Backend — run from backend/, port matches frontend/.env.example VITE_API_URL
( cd backend && uvicorn main:app --port "${PORT:-8000}" >/dev/null 2>&1 & )
SERVER=$!; trap 'kill $SERVER 2>/dev/null' EXIT
until curl -sf "http://localhost:${PORT:-8000}/health" >/dev/null; do sleep 0.5; done
code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${PORT:-8000}/api/v1/games/today")
[[ "$code" == "200" ]] || { echo "/api/v1/games/today returned $code, expected 200" >&2; exit 1; }

# Frontend — vite dev server defaults to :5173 (frontend/vite.config.js)
( cd frontend && npm run dev >/dev/null 2>&1 & )
SERVER=$!; trap 'kill $SERVER 2>/dev/null' EXIT
until curl -sf http://localhost:5173/ >/dev/null; do sleep 0.5; done
```

Both API keys (`ODDS_API_KEY`) and CORS origins come from `backend/.env` —
a runner that needs live odds/Polymarket data depends on that file being
populated in the worktree (see `scripts/bootstrap-worktree.sh`'s secret-copy
step); a runner that only needs the app to boot and route correctly does not.

## Choosing the shape (the Expert's call)

For each criterion, the Expert picks the cheapest shape that can actually detect the
behavior's absence:

- Crisp and observable in the filesystem / HTTP / process exit → **deterministic**.
- Fuzzy / semantic / "looks right" → **LLM-judge** on the residue, after deterministic
  prefilters.
- The project has a native pattern that fits → **native test** wrapped by the runner.

Most runners are a *mix*: deterministic checks for structure and status, an LLM-judge for
the one or two genuinely fuzzy bits. Don't reach for the judge when a `grep` will do.

## Conventions
- `chmod +x prds/<feature>/run-prd-test.sh` before committing.
- Helper artifacts (fixtures, judge prompts, configs, contracts) live under
  `prds/<feature>/` and are committed with the runner.
- The runner must be runnable from the repo root: `./prds/<feature>/run-prd-test.sh`.
- Always finish with the right-reason loop (`references/right-reason.md`) before commit.
