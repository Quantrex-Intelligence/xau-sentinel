"""Persists the user's FundedNext account-type/phase selection. A small JSON
file rather than a new SQLite table — this is a single-row settings blob,
not journal data, and keeping it out of journal/database.py means the
Stage 1 schema is never touched. Independent of config.py's env-driven
settings: this is runtime-changeable through the API (account type/phase
selection genuinely changes as a trader progresses), where config.py is
startup-time-only.
"""
import json
from pathlib import Path
from typing import Optional

import config
from risk.models import AccountType, Phase

SETTINGS_PATH = Path(config.BASE_DIR) / "data" / "fundednext_settings.json"

DEFAULTS = {
    "account_type": AccountType.STELLAR_2STEP.value,
    "phase": Phase.CHALLENGE.value,
    "consistency_enabled": False,
}


def get_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(SETTINGS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULTS)
    return {**DEFAULTS, **data}


def save_settings(account_type: Optional[str] = None, phase: Optional[str] = None,
                   consistency_enabled: Optional[bool] = None) -> dict:
    current = get_settings()
    if account_type is not None:
        current["account_type"] = AccountType(account_type).value
    if phase is not None:
        current["phase"] = Phase(phase).value
    if consistency_enabled is not None:
        current["consistency_enabled"] = bool(consistency_enabled)

    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(current, indent=2))
    return current
