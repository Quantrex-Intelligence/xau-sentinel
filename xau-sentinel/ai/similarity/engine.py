"""Orchestrates historical setup similarity: pull candidate trades -> extract
features (the no-look-ahead-safe boundary in ai/similarity/features.py) ->
score -> attach outcome AFTER scoring -> top-K above a threshold. No new
journal capability — reads only journal.trades.list_trades(), the same
function every other read path already uses.
"""
from typing import List, Optional, Tuple

import pandas as pd

import config
from journal import trades as trades_repo
from ai.similarity.features import extract_features_from_live_setup, extract_features_from_trade
from ai.similarity.models import MatchedSetup, Outcome, SetupFeatures, SimilarityResult
from ai.similarity.scoring import score

# A setup can't be meaningfully compared without at least knowing its
# direction and H1 bias — a candidate missing either is excluded entirely,
# never scored with a partial or fabricated value.
_REQUIRED_FIELDS = ("direction", "h1_structure")


def _clean_records(df: pd.DataFrame) -> List[dict]:
    return df.where(pd.notnull(df), None).to_dict(orient="records")


def _outcome_from_row(row: dict) -> Outcome:
    status = row.get("status") or "OPEN"
    result = row.get("result") if status == "CLOSED" else None
    return Outcome(
        status=status, result=result,
        r_multiple=row.get("r_multiple"), pnl=row.get("pnl"),
        duration_minutes=row.get("duration_minutes"),
        entry_date=row.get("trade_date"), entry_time=row.get("trade_time"),
    )


def resolve_query_features(trade_id: Optional[int] = None) -> Tuple[Optional[SetupFeatures], Optional[int]]:
    """Shared by the tool and the REST routes so both resolve "what are we
    comparing against" identically. `trade_id=None` means "the current live
    candidate setup" (api.snapshot.build_snapshot() + analysis.setup.detect_setup()
    — the same calls every other market/setup tool already makes, never
    re-run or duplicated logic). A given `trade_id` means "compare that past
    trade against the rest of history" — returns (None, None) if the id
    doesn't exist, so the caller can report it as unavailable rather than
    crash."""
    if trade_id is None:
        from api.snapshot import build_snapshot

        snapshot = build_snapshot()
        if snapshot.data_error or snapshot.setup is None:
            return None, None
        # build_snapshot() already ran the setup engine — snapshot.setup is
        # its SetupOut mirror (same .direction/.rr fields detect_setup()'s
        # own SetupResult has), so there's no second detection call to make.
        return extract_features_from_live_setup(snapshot, snapshot.setup), None

    trade = trades_repo.get_trade(trade_id)
    if trade is None:
        return None, None
    return extract_features_from_trade(trade), trade_id


def find_similar_setups(query: SetupFeatures, exclude_trade_id: Optional[int] = None,
                         top_k: Optional[int] = None,
                         min_similarity: Optional[float] = None) -> SimilarityResult:
    top_k = top_k if top_k is not None else config.AI_SIMILARITY_DEFAULT_TOP_K
    min_similarity = (
        min_similarity if min_similarity is not None else config.AI_SIMILARITY_DEFAULT_MIN_SIMILARITY
    )

    df = trades_repo.list_trades()
    if df.empty:
        return SimilarityResult()

    considered = 0
    excluded = 0
    scored: List[MatchedSetup] = []

    for row in _clean_records(df):
        trade_id = row["id"]
        if exclude_trade_id is not None and trade_id == exclude_trade_id:
            continue

        features = extract_features_from_trade(row)
        if any(getattr(features, f) is None for f in _REQUIRED_FIELDS):
            excluded += 1
            continue

        considered += 1
        similarity, matched, different = score(query, features)
        if similarity < min_similarity:
            continue

        scored.append(MatchedSetup(
            trade_id=trade_id, similarity=similarity, entry_snapshot=features,
            outcome=_outcome_from_row(row), matched_features=matched, different_features=different,
        ))

    scored.sort(key=lambda m: m.similarity, reverse=True)
    return SimilarityResult(matches=scored[:top_k], considered_count=considered, excluded_count=excluded)
