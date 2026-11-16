# PRD: promos-tracker

## Why
Sportsbooks hand out promos (signup bonuses, odds boosts, free bets, deposit
matches) that are only valuable if someone actually tracks them before they
expire. There's no free API for this — it's inherently manual — so today
there's nowhere in the app to log one and no reminder that it's about to lapse.
The developer wants a simple place to record a promo as they get it and see,
at a glance, which ones are closing in.

## User story
As the developer, I can log a promo (sportsbook, type, amount, expiry date,
status, notes) as I receive it, see all my promos in one list sorted by
soonest expiry, mark one used once I claim it, and delete one that was a
mistake or duplicate — so nothing lapses unnoticed.

## Definition of done
`./prds/promos-tracker/run-prd-test.sh` exits 0:

- `POST /api/v1/promos` creates a promo (sportsbook, promo_type, amount,
  expiry_date, optional notes; status defaults to `available`) and returns it
  with a generated `id` — persisted in a dedicated SQLite table, not `cache.db`
  (cache.db is the shared TTL cache; this data must survive independent of any
  TTL and live in its own table/file).
- `GET /api/v1/promos` returns all promos sorted by soonest `expiry_date`
  first, and `GET /api/v1/promos?status=available` (also `used`, `expired`)
  returns only promos matching that status.
- `PATCH /api/v1/promos/{id}` updates a promo's status (`available` / `used` /
  `expired`) and the change is visible on a subsequent `GET`; a non-existent
  `id` returns 404.
- `DELETE /api/v1/promos/{id}` removes a promo — it no longer appears in a
  subsequent `GET /api/v1/promos`; a non-existent `id` returns 404.
- The frontend `/promos` page renders an add-promo form (sportsbook, promo
  type, amount, expiry date, notes) and, on submit, the new promo appears in
  the list without a manual refresh.
- The promos list on that page is sorted soonest-expiry-first, and any promo
  that is still `available` and expires within 3 days of today renders with a
  visually distinct style (e.g. a warning badge/border) that promos further
  out, or not `available`, do not get.
- `npm run build` (frontend) and importing every new/changed backend module
  both succeed with no errors.

## Out of scope
- Any sportsbook-promo-scraping or auto-fetching — manual entry only, there is
  no free API for this.
- Linking promos to anything in the edge-finding pipeline (`edge_engine.py`,
  games/props routes) — promos are a standalone tracker.
- Touching `NBAPredictor` or anything under `decision-predictor-ml-integration`.
- Adding any new dependency (backend or frontend) — stdlib `sqlite3` /
  existing FastAPI/Pydantic/React/axios/Tailwind stack only.
- Any test framework (pytest/vitest/etc.) — none exists today; verification is
  deterministic shell + a bare `node` check, per this project's current state.
- Authentication/multi-user support — single-user, matches the rest of the app.

## Constraints
- New persistent store is a dedicated SQLite file (`backend/data/promos.db`,
  gitignored like `cache.db` already is), separate from `services/cache.py`'s
  TTL cache — a plain CRUD table, no TTL semantics.
- The store's path is a `Settings` field (`promos_db_path`, defaulting to
  `data/promos.db` under `backend/`), not hardcoded — config flows through
  `backend/config.py` only, enforced by the existing
  `no-direct-env-access.sh` lint. This also lets the runner point it at a
  temp file via env var for isolated testing.
- Request/response shapes are Pydantic models in `backend/models/schemas.py`
  (`PromoCreate`, `PromoUpdate`, `Promo`, `PromoListResponse`), not inline
  dicts crossing the router boundary — matches `games.py`/`props.py`.
- New route lives in `backend/routers/promos.py`, registered on `app` with
  prefix `/api/v1` in `backend/main.py` (same pattern as `games`/`props`).
- `main.py`'s CORS middleware must add `PATCH` and `DELETE` to
  `allow_methods` (currently only `GET`/`POST`) or the frontend update/delete
  calls will be blocked by the browser.
- Frontend follows existing page conventions: Tailwind utility classes
  matching `Props.jsx`'s style (slate-800 cards, brand/edge color accents),
  added to `App.jsx`'s routes and `Navbar.jsx`'s links.
- `amount` is free text (e.g. `"$50 free bet"`, `"100% up to $200"`) — promo
  structures vary too much for a single numeric field.
