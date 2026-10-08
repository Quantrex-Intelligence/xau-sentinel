"""Build the V2 research dataset in parallel chunks (warm-up per chunk)."""
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

from backtest.data import load_history
from backtest.research.v2_features import build_rows_v2

WARMUP = 60
TFS = ("M5", "M15", "H1", "H4")
OUT = Path(__file__).parent / "data" / "features_v2_6m.csv"


def _chunk(args):
    frames, start, end = args
    rows = build_rows_v2(frames, max(0, start - WARMUP), end)
    return [r for r in rows if r["f_index"] >= start]


def build(months: int = 6, workers: int = 8, out: Path = OUT) -> pd.DataFrame:
    frames = {tf: load_history(tf, months).reset_index(drop=True) for tf in TFS}
    n = len(frames["M5"])
    step = max(1, (n - 300) // (workers * 4))
    jobs = [(frames, s, min(s + step, n)) for s in range(300, n, step)]
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for part in pool.map(_chunk, jobs):
            rows.extend(part)
    df = pd.DataFrame(rows).sort_values("f_index").reset_index(drop=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    return df


if __name__ == "__main__":
    d = build()
    print(len(d), "rows; columns:", len(d.columns), "triggers:", {c: int(d[c].sum()) for c in d.columns if c.startswith("trig_")})
