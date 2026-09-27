"""Tracks the account balance at the start of the current FundedNext
trading day (server time), so the daily-loss floor can be computed as
day_start_balance - daily_loss_pct * initial_balance, per FundedNext's
documented mechanics (see risk/rules.py). A day boundary is server-local
midnight, not UTC midnight or wall-clock local time.

Small JSON file, same rationale as settings_store.py: this is single-row
runtime state, not journal data, so it stays out of the Stage 1 schema.
"""
import json
from datetime import date
from pathlib import Path
from typing import Optional

import config

STATE_PATH = Path(config.BASE_DIR) / "data" / "fundednext_day_state.json"


def get_day_start_balance(current_date: date, current_balance: float) -> float:
    """Returns the balance to use as today's anchor. Resets to
    `current_balance` whenever the stored date is not `current_date`
    (a new server-local day has started) or no state exists yet."""
    state = _read()
    if state is None or state.get("date") != current_date.isoformat():
        _write(current_date, current_balance)
        return current_balance
    return float(state["day_start_balance"])


def _read() -> Optional[dict]:
    if not STATE_PATH.exists():
        return None
    try:
        return json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _write(current_date: date, day_start_balance: float) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({
        "date": current_date.isoformat(),
        "day_start_balance": day_start_balance,
    }))
