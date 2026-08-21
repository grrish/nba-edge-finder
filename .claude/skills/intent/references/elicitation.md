# Elicitation — how to run the Q&A

*Hackable seam: this file controls the intent Q&A style. A project can rewrite it to
change how open-ended the conversation is and when a PRD gets offered, without touching
the flow in SKILL.md.*

The goal of the conversation is not to collect requirements off a checklist. It's to
*draw out* what the user actually needs and turn it into outcomes you can verify. A
person who feels heard and understood gives you far more than a person being interviewed.

## Elicit outcomes, not solutions (P2)

People open with a solution because it's concrete in their head:

> "Add a `/api/search` endpoint that queries Postgres with `ILIKE`."

That sentence hides the actual need and prematurely fixes the *how*. Peel it back:

- **"Who's hurting, and how?"** → "Readers can't find a post by title; the list on `/`
  is unsorted and grows unbounded."
- **"Why is that a problem now?"** → reveals scale, urgency, the real pain.
- **"What would they do instead, once this exists?"** → the observable outcome:
  "navigate to `/search?q=foo` and see posts whose title contains foo."

Now you have a *need* and an *observable outcome*. The endpoint, the database, the
`ILIKE` — those are implementation, and they belong to spec-planning, not here (P4).

Useful moves:
- **"Why is that?"** — the generic follow-up that keeps you from assuming. Repeat it
  (the 5-whys move) until you hit the real driver.
- **Play it back.** "So the win is: a reader types a title fragment and lands on the
  post. Yes?" Confirming in your own words catches mismatches early.
- **Resist solutionizing — including your own.** When you catch yourself proposing a
  design, stop and ask what outcome it's serving.

## The throughline question (P3)

For every outcome the user cares about, ask:

> **"How would we know that's true?"**

This is the hinge. The answer is simultaneously:
- a **prose criterion** for the PRD's *Definition of done*, and
- a **concrete check** for `run-prd-test.sh`.

You are not writing prose and then translating it. You are eliciting one verifiable fact
and writing it down two ways. Example:

| You ask | They answer | → PRD bullet | → runner check |
|---|---|---|---|
| How would we know search works? | "`/search?q=hello` shows a link to a post with 'hello' in the title." | `/search?q=hello` renders ≥1 link to a matching post | LLM-judge: load page, assert a matching `<a>` |
| What about an empty query? | "It shows an instruction, no result list." | `/search` (no query) shows an instruction message, no results list | deterministic: grep rendered HTML |

If an answer is fuzzy ("it should feel fast", "results look relevant"), keep pushing:
*"What would you look at to decide it's fast/relevant?"* Either it sharpens into something
observable, or it's a non-functional concern to note explicitly — not a silent assumption.

## Keep the PRD lean

Default to the minimal skeleton (`references/prd-template.md`). Add an optional block
(non-functional requirements, scale, business rules) **only when the conversation raised
it.** Empty boilerplate sections are noise; an optional block the user actually cares
about is signal. Don't prompt for sections just to fill them.

## Pick the rhythm (P7)

Early, name the choice and follow the user's lead:
- **Interleaved** — for each outcome, write the prose bullet and draft its runner check
  right then. Good for users who think concretely and want to see "done" materialize.
- **Prose-first** — agree the whole definition of done as prose, then switch gears and
  build the runner from it in one pass. Good for users who want to settle *what* before
  touching *how we check*.

Both land in the same place because both rest on "how would we know?". Don't force one.

## Domain vocabulary for this project

nba-edge-finder finds +EV betting opportunities by comparing ML predictions
against market prices (scanned: `backend/services/edge_engine.py` computes
edges from `backend/services/nba_data.py` predictions vs.
`backend/services/odds.py` sportsbook lines and `backend/services/polymarket.py`
prediction-market prices; routes split `games` vs. `props`,
`backend/routers/games.py` / `props.py`). Features in this domain tend to hinge
on the same handful of questions — ask them where relevant instead of
rediscovering them each time:

- **Which entity is this about** — a game-level market (moneyline/spread/total)
  or a player prop (points/rebounds/assists/threes/...)? The two live in
  separate routers and schemas (`GamePrediction` vs. `PropPrediction` in
  `backend/models/schemas.py`) and rarely share logic.
- **Which price source(s)** — sportsbook odds (`OddsService`), Polymarket
  (`PolymarketService`), or a comparison between them? A feature that adds a
  new price source needs a new `Settings` field for its API key/config.
- **What counts as an "edge"** — what threshold or formula turns a prediction +
  a market price into a flagged opportunity? This is usually the crux of the
  Definition of done ("how would we know true?" → "an edge of ≥X% appears in
  the response/UI").
- **Confidence / model version surface** — predictions carry `confidence` and
  `model_version` fields already; does the new outcome need to expose or
  threshold on them?

## The decide-to-build gate (Step 3)

Offer to create a PRD **only when the intent is clear** — you can state the need, the
observable outcomes, and the scope boundaries back to the user and they agree. Signs
it's not ready: the user is still exploring, the outcome keeps shifting, or there's no
way yet to say what "done" looks like. It's completely fine for a conversation to end
with **no artifact** — sometimes the user just wanted to think out loud. Don't
manufacture a PRD to have something to show.

Before building, also settle:
- **Scope / out-of-scope.** What is explicitly *not* in this feature? This is what keeps
  the downstream chain from drifting and lets the reviewer reject out-of-scope findings.
- **Constraints** (from the Expert): conventions this feature must honor — "SSR
  everywhere", "no new dependencies", an existing contract to conform to.
- **External context** (Step 2): anything governing the feature that should be wired in.
