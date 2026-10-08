"""Entry Model V2 out-of-sample research pipeline (research-only; see
docs/entry-model-v2-oos-research-spec.md).

Named explicitly to avoid any confusion with the unrelated, pre-existing `backtest/` package
(Analysis Engine V2 feature research -- a different "V2", a different model, a different owner).
This package never imports from or writes into `backtest/`.

Nothing here is wired into the production app. It is read-only with respect to
`analysis/entry_model/*` and `ai/strategy/rules.py`: it imports and calls the frozen model exactly
as production does, and never alters its parameters, thresholds, or logic.
"""
