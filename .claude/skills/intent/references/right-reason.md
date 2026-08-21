# Failing for the right reason

*Hackable seam: this file is the "failing-test heuristic". A project can sharpen what
counts as a right-reason failure for its stack without touching the flow in SKILL.md.*

This is the load-bearing check that proves `prd.md` and `run-prd-test.sh` actually
correspond (P6). After drafting the runner, you run it **against today's unbuilt code**
and inspect *why* it fails.

A PRD runner that exits non-zero is necessary but not sufficient. It must exit non-zero
**because the feature is absent** — exercising the exact gap the PRD describes. A runner
that fails for an unrelated reason is lying to the harness: it'll go green the moment the
unrelated problem is fixed, with the feature still missing, or it'll stay red forever on
something orthogonal.

## Right reason vs wrong reason

| Failure | Reason | Verdict |
|---|---|---|
| `missing app/search/page.tsx` | The route the PRD calls for doesn't exist yet | ✅ Right reason — exercises the gap |
| Deterministic check: route returns 404 | Endpoint not implemented | ✅ Right reason |
| LLM-judge: "no matching link rendered" | Behavior not built | ✅ Right reason |
| `command not found: clade` | Typo in the runner | ❌ Wrong reason — fix the script |
| `ECONNREFUSED localhost:3000` | Runner never started the dev server | ❌ Wrong reason — fix the harness in the script |
| `SyntaxError` in the test helper | Broken helper, not a missing feature | ❌ Wrong reason — fix the helper |
| Fails because an *unrelated* existing test is red | Pre-existing breakage | ❌ Wrong reason — isolate this PRD's checks |
| Exits 0 already | The behavior may already exist, or the check is too weak to detect absence | ❌ Investigate — a PRD whose runner passes today is testing nothing |

## The loop

1. `chmod +x prds/<feature>/run-prd-test.sh` and run it.
2. Read the **exit code and the full output** — don't trust exit code alone.
3. Map each non-zero check back to a PRD criterion. Ask: *does this failure exercise the
   gap that criterion describes?*
4. **Wrong reason** → fix the runner or its helpers (a real bug in the check, a missing
   `chmod`, a server that wasn't started, an unrelated test bleeding in) and re-run.
5. **Passes already** → the check is too weak or the behavior exists. Strengthen the
   check until absence is detected, or reconsider whether the PRD describes new work.
6. Repeat until **every** criterion fails for the right reason.
7. Show the user the output and narrate what each failure proves. They should agree the
   runner is testing the real thing before you commit.

## Notes
- A runner can mix check types; verify each *independently* fails for the right reason —
  a deterministic check passing while an LLM-judge check is the real signal (or vice
  versa) can mask a wrong-reason failure.
- Cheap deterministic checks run first so the expensive LLM-judge only runs once the
  basics hold. During this loop that ordering also makes wrong-reason failures obvious:
  a deterministic check failing on a typo'd path is unmistakable.
- This is the step most likely to need project-specific judgment. Keep the heuristic
  ("does the failure exercise the described gap?") fixed; let the examples evolve.
