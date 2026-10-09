"""Guards against this feature accidentally touching the frozen OOS research spec. Importing
research/entry_model_v2_oos/spec.py here only to read its constants, same as any other test -- the
production ai/entry_judge/* package itself never imports this module (see
ai/entry_judge/snapshot.py's own comment on why ELIGIBLE_STATES is duplicated, not imported)."""
import ast
from pathlib import Path

from research.entry_model_v2_oos import spec

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_frozen_hypothesis_bounds_are_unchanged():
    assert spec.RR_LOW == 0.5
    assert spec.RR_HIGH == 1.0


def test_frozen_is_boundary_is_unchanged():
    assert str(spec.IS_DATA_END) == "2026-10-06 12:20:00+00:00"


def test_frozen_model_fingerprint_constant_is_unchanged():
    assert spec.FROZEN_MODEL_FINGERPRINT == "62427db38bef9e8f1d67ebd6d4e3417e5506f6c504fc865610bfef97113fcdaa"


def test_the_live_model_fingerprint_still_matches_the_frozen_one():
    # The strongest form of this guard: recomputes the real fingerprint over the live files and
    # checks it against the frozen constant, exactly like research/entry_model_v2_oos/boundary.py's
    # own assert_model_unchanged() does before any real OOS run.
    assert spec.compute_model_fingerprint() == spec.FROZEN_MODEL_FINGERPRINT


def test_ai_entry_judge_package_never_imports_research_or_backtest():
    package_dir = REPO_ROOT / "ai" / "entry_judge"
    for py_file in package_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if node.module else []
            else:
                continue
            for name in names:
                assert name is None or not name.startswith(("research", "backtest")), (
                    f"{py_file.name} imports {name!r} -- ai/entry_judge/* must never import the "
                    f"research/backtest packages"
                )


def test_entry_model_judge_route_never_imports_research_or_backtest():
    route_file = REPO_ROOT / "api" / "routes" / "entry_model_judge.py"
    tree = ast.parse(route_file.read_text(encoding="utf-8"), filename=str(route_file))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
            for name in names:
                assert name is None or not name.startswith(("research", "backtest"))
