USE WHEN: touching backend/services/edge_engine.py or backend/models/predictor.py,
or asked to improve prediction accuracy, wire in a model, or implement prop edges.

## Decision

Real ML model integration for `NBAPredictor` (training + loading a fitted
XGBClassifier/XGBRegressor) is deferred to a later phase — not an active
near-term goal. Data/odds/polymarket infrastructure was built out first,
deliberately, before investing in modeling.

## Current state (as of the initial scaffold commit, 743f359)

- `NBAPredictor._game_model` / `_prop_model` are always `None` — no trained
  model file is loaded anywhere; the docstring's references to
  `_load_game_model()` / `_load_prop_model()` describe intent, not code that
  exists.
- `EdgeEngine._score_game_edge` (edge_engine.py) uses a hardcoded
  `model_prob = 0.5` placeholder (see the TODO at that line) instead of a
  real prediction.
- `EdgeEngine.find_prop_edges` is a full stub that returns `[]`.

See also [[pattern-dont-silently-fix-scaffolds]].

## Until fulfilled

Unrelated feature work touching these files must leave the placeholder logic
untouched — don't wire in a real model, remove the TODO, or implement
`find_prop_edges`, even if it looks like an easy win. Only touch this when
the user explicitly asks to build out the predictor.
