# nba-edge-finder

<!-- AGENTS.md — the agent contract. Vendor-neutral, eagerly loaded at the start
     of every session that touches this repo. This is a MAP, not an encyclopedia:
     it points into the Expert and the code. Keep it under ~150 lines — everything
     here is paid in tokens on every invocation. -->

## Onboarding (read before doing anything non-trivial)

1. `.claude/skills/expert/SKILL.md` — this project's Expert. Long-term memory; consult it.
2. `prds/<f>/prd.md` — why a feature exists. `prds/<f>/run-prd-test.sh` — its runnable definition of done.
3. `specs/<f>/mainspec.md` (+ `slices/`) — the plan for a feature.

## The Expert (consult before non-trivial work)

The `expert` skill is this project's long-term memory — pulled on demand, not
always in context. It encodes architectural decisions, how features get verified
here, patterns (DO/DON'T), procedural steps for new features, core files, and
the project's **invariants** (hard rules, some enforced by custom lints).

Read `.claude/skills/expert/references/*.md` before:
- adding a feature, debugging unexpected behavior, choosing where new code lives,
  or deciding how to verify a change.

The Expert reflects what is **committed to main**, not what is planned. Trust the
Expert for current reality; trust PRDs and specs for intended direction.

## The skill chain

Skills walk a state machine forward, one step at a time. Each reads its
predecessor's artifacts, does its work, commits, and writes a sentinel as its final
action. The next skill fires when its trigger condition is met.

| Skill | Fires when | Writes |
|---|---|---|
| `/intent` | Human initiates | `prds/<f>/{prd.md, run-prd-test.sh}` on `prd/<author>/<f>` |
| `/spec-planning` | `specs/<f>/.planning-done` absent on `feature/<f>` | mainspec + slices + `.planning-done` |
| `/spec-validate` | `.planning-done` present, `.validated` absent | in-place spec edits + `.validated` |
| `/implement-mainspec` | `.validated` present, `specs/<f>/.prd-passed` absent | commits on `feature/<f>` until `run-prd-test.sh` exits 0 (dispatcher then records `.prd-passed`) |
| `/fix-local-checks` | `scripts/local-checks.sh` fails post-implement | patch + commit |
| `/address-feedback` | PR has unresolved reviewer findings (budget enforced externally) | commits for Clear; replies for Ambiguous/Complex/Out-of-Scope |
| `/evaluate-pr` | *human-initiated* after the reviewer converges (the "Ready for your review" handoff) | merge, close, or fix-and-push; **no memory writes** |
| `/learn` | post-merge to main, no `learn/<sha>` on origin | Expert shards + invariants + AGENTS.md pointers + candidate lints |

**Idempotency rule.** Every skill must be safe to re-invoke on the same disk state.
Commit all required artifacts *before* writing your sentinel. A crash mid-skill
leaves the next invocation a clean re-derivation from disk.

## Memory: two shapes, one write path

- **AGENTS.md (this file + nested ones) = eager memory.** A map; loaded
  automatically. Keep it pointer-shaped and under the line cap.
- **The Expert = lazy memory.** The dense knowledge, pulled on demand.
- `/learn` (post-merge, ground truth) writes both. It is the **only** path that
  writes memory; it lands on a reviewable PR a human merges.
- When the reviewer converges, the harness hands the PR to you for **`/evaluate-pr`**:
  walk the change, run it, build understanding, then merge (or fix-and-push, or
  close). Nothing learned there is memory until it merges.
- If a feature hits **STUCK** (any step's retry cap), the dispatcher posts the
  diagnostic to the PR and halts. The **human's first job is the context
  defect**, not the code — correct the misleading `AGENTS.md` / Expert / spec
  / PRD on the branch, then fix the code, then merge. `/learn` observes the
  context correction in the merged diff.

## Branch lifecycle

    prd/<author>/<feature>   ← /intent output: prd.md + run-prd-test.sh.
                                Do not work on these directly; an atomic
                                rename to feature/<f> is the claim.
    feature/<feature>         ← active implementation lane.
    main                      ← humans merge only. Never push directly.
    learn/<sha>               ← auto-generated post-merge memory PR; humans merge.

## Non-bypassable verification

Four layers gate "done." All four must pass; none can be talked past.

1. **Pre-commit hooks** — none configured yet (no `.pre-commit-config.yaml` /
   `.husky/`). `frontend/package.json` declares a `lint` script, but `eslint`
   is not installed and no config file exists — it does not currently run.
   `backend/` has no lint/format/typecheck tooling wired up either (no
   `pyproject.toml`, `ruff`, or `mypy`). Until one of these is added deliberately,
   `scripts/local-checks.sh` is intentionally absent — see its own note below.
2. **Slice unit tests** — each slice's tests run during `/implement-slice`. This
   project has no test framework yet (no `pytest` in `backend/requirements.txt`,
   no `vitest`/`jest` in `frontend/package.json`) — the first feature that needs
   real unit tests should add one deliberately (ask first; see
   `.claude/skills/intent/references/runner-recipes.md`), not invent ad hoc
   assertions.
3. **CI** — none configured yet (no `.github/workflows/`). The PR runner in
   step 4 below is the only automated gate today.
4. **PRD runner** — `./prds/<feature>/run-prd-test.sh` must exit 0 before merge.
   This is the definition of done.

**Silencing a check is bypassing it.** Suppression directives (`@ts-ignore`,
`eslint-disable`, `as`/`!`, …), weakened configs, and skipped tests (`.skip`,
`xfail`, …) may only be added by a human, deliberately, on the branch — never by an
agent. An agent that can't pass a check honestly lets it reach STUCK.

Anything bypassing these layers is a bug, not a feature.

## Stack quick reference

- **Backend** — FastAPI (`backend/main.py`), run with `uvicorn main:app` from
  `backend/`, default port 8000. Config via `pydantic-settings`
  (`backend/config.py`), reading `backend/.env` (see `backend/.env.example`).
  Routes: `backend/routers/{games,props}.py`, mounted at `/api/v1`. Domain
  services: `nba_data.py`, `odds.py`, `polymarket.py`, `edge_engine.py`.
- **Frontend** — Vite + React (`frontend/`), `npm run dev` on port 5173,
  proxies `/api` to `VITE_API_URL` (`frontend/.env`, default
  `http://localhost:8000`).
