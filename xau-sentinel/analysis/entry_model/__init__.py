"""Entry Model (manual decision support).

The active implementation is the Top-Down Multi-Timeframe Entry Model (hierarchy.py). See
docs/entry-model-v2-hierarchy.md for its design, and docs/entry-model-v1-plan.md /
docs/entry-model-v1-research.md / docs/entry-model-v1-m5-confirmation-audit.md for the V1
architecture this replaces and the raw-data findings that motivated the redesign. V1's own module
(model.py) and its research helpers (dataset.py, outcome.py) are kept, unimported here, for
historical reference and their own tests (tests/test_entry_model.py, tests/test_entry_model_outcome.py)."""
from analysis.entry_model.hierarchy import DISCLAIMER, evaluate  # noqa: F401
