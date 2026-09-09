USE WHEN: touching services/cache.py, evaluating a different caching
backend (Redis, in-memory, etc.), or reasoning about why SQLite was picked.

## What

`CacheDB` (services/cache.py) uses SQLite as a shared key-value TTL cache
backing every service (`odds.py`, etc. via `CACHE_DB_PATH`).

## Why SQLite

It was a default choice, not a decision backed by an evaluated tradeoff
(e.g. against Redis or an in-memory cache) — there is no strong rationale to
defend. The user is open to revisiting it later if a real need arises
(concurrency, multi-process scaling, persistence requirements, etc.).

## How to use this

Don't treat SQLite as a hard architectural invariant. A proposal to swap
backends doesn't need to overcome a documented rationale. If a task
materially depends on cache backend behavior, flag it and confirm with the
user rather than assuming SQLite is load-bearing.
