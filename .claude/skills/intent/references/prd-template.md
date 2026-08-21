# PRD template

The PRD is the prose half of the contract: **why** the feature exists and **what** "done"
means. Its companion `run-prd-test.sh` is the executable half — the *Definition of done*
below is the prose the runner operationalizes; the runner **is** the acceptance criteria,
so there is no separate acceptance-criteria section.

Default to the minimal skeleton. Add an optional block **only when the conversation
surfaced it** (P9 / lean-by-default). Never emit an empty section to "be thorough".

## Minimal skeleton (always)

```markdown
# PRD: <feature>

## Why
<The need, in user terms. Who is hurting and how. Not the solution.>

## User story
As a <user>, I can <observable action> so that <outcome>.

## Definition of done
`./prds/<feature>/run-prd-test.sh` exits 0:
- <observable criterion 1 — what's true from outside when this is built>
- <observable criterion 2>
- ...
(Each bullet maps to a check in the runner — see runner-recipes.md. Behavioral,
not implementation-bound.)

## Out of scope
- <explicitly excluded thing — keeps the chain from drifting and lets the
  reviewer reject out-of-scope findings>

## Constraints
- <convention this must honor, sourced from the Expert — e.g. "SSR everywhere",
  "no new dependencies", "conform to the existing API contract">
```

## This project's conventions (fill Constraints from these when relevant)

nba-edge-finder is a FastAPI backend (`backend/`) + Vite/React frontend
(`frontend/`), no test framework or CI wired up yet (scanned: no pytest/vitest/
jest in either manifest, no `.github/`). Recurring constraints worth checking
against for new features:
- New routes live under `backend/routers/`, registered on `app` with prefix
  `/api/v1` (see `backend/main.py`) — request/response shapes go in
  `backend/models/schemas.py` as Pydantic models, not inline dicts.
- CORS origins and API keys are read from `Settings` (`backend/config.py`),
  never hardcoded — a feature that talks to a new external API needs a new
  `Settings` field with an `.env.example` entry, not a bare `os.getenv`.
- `SecurityHeadersMiddleware` and the `slowapi` rate limiter already wrap every
  route (`backend/main.py`) — a new endpoint gets them for free; don't bypass.
- No ORM/DB migration tooling is present (`backend/services/cache.py` is a
  SQLite cache, `backend/data/cache.db`, gitignored) — a feature needing
  persistent schema changes should flag that explicitly as a constraint.

## Optional blocks (add only when raised)

```markdown
## Inputs / References
- `prds/<feature>/<contract-or-fixture>` — <what it is; copied in because the runner
  needs it>
- `<repo/path/to/existing-doc>` — <governing design/architecture doc, linked in place>
(Anything the runner needs is copied under prds/<feature>/ for self-containment;
pure intent/design docs may be co-located or linked by repo path. List them here so
the downstream chain, which reads this file, discovers them.)

## Non-functional requirements
- <perf / latency / accessibility / security target, stated observably so the runner
  can check it — e.g. "search results render in < 500ms with 10k seeded posts">

## Scale
- <volume / concurrency the feature must handle, if it shaped any criterion above>

## Business rules
- <rule that must be enforced in code — e.g. "drafts never appear in search results">
```

## Notes
- **Definition of done bullets are behavioral** (P4): "`/search?q=x` returns matching
  posts", not "calls `searchPosts()`". The reader should be able to verify each without
  reading the implementation.
- A near 1:1 correspondence between these bullets and the runner's checks is a *byproduct*
  of eliciting each one through "how would we know that's true?" — not bookkeeping you
  enforce afterward.
- Keep `Why` in user/problem terms. It's the project's permanent "why" history; resist
  letting it become a design doc.
