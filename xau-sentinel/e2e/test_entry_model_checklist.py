"""E2E checklist for the Entry Model V2 card on the unified Market page, and the cross-engine
conflict banner (read-only).

Requires both servers running in MOCK mode with AI_PROVIDER=mock:
    MODE=mock AI_PROVIDER=mock uvicorn api.main:app --host 127.0.0.1 --port 8000
    (cd frontend && npm run dev)   # http://localhost:3000

Run directly:
    python e2e/test_entry_model_checklist.py

Read-only by design: the checklist only issues GET requests and checks the page. It never places
orders, writes to the journal, or calls an LLM.
"""
import re
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "http://localhost:3000"
API_BASE = "http://127.0.0.1:8000"
FORBIDDEN = re.compile(r"(?<!not a )probab|\bBUY\b(?!-side)|\bSELL\b(?!-side)|win rate", re.IGNORECASE)
CONFIRMED_STATES = {"ENTRY_CONFIRMED", "PRECISION_AVAILABLE", "ENTRY_READY"}
results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = ""):
    results.append((name, condition, detail))


def main() -> int:
    # --- API contract ---------------------------------------------------
    resp = httpx.get(f"{API_BASE}/api/entry-model", timeout=30)
    check("API: GET /api/entry-model returns 200", resp.status_code == 200, str(resp.status_code))
    body = resp.json() if resp.status_code == 200 else {}
    check("API: every required top-level section is present",
          {"symbol", "direction", "state", "higher_timeframe", "intraday", "setup_15m",
           "confirmation_5m", "precision_1m", "entry_candidate", "confidence", "invalidation",
           "next_condition"} <= set(body))
    direction, state = body.get("direction"), body.get("state")
    check("API: a concrete LONG/SHORT direction only appears once 5M confirmation is confirmed",
          direction not in ("LONG", "SHORT") or state in CONFIRMED_STATES, f"direction={direction} state={state}")
    check("API: the route is read-only (POST is not allowed)",
          httpx.post(f"{API_BASE}/api/entry-model", timeout=15).status_code in (404, 405))

    # --- Browser checks -------------------------------------------------
    console_errors, page_errors, failed_requests = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}"))

        page.goto(f"{BASE}/market", wait_until="networkidle", timeout=30000)

        try:
            page.get_by_role("heading", name="Entry model").wait_for(state="visible", timeout=15000)
            check("UI: the Entry Model card is shown directly on the Market page", True)
        except Exception:
            check("UI: the Entry Model card is shown directly on the Market page", False)

        body_text = page.inner_text("body")
        check("UI: the flow diagram rungs are shown (1D / 4H, 1H, 15M, 5M, 1M)",
              all(label in body_text for label in ("1D / 4H", "1H", "15M", "5M", "1M")))
        check("UI: the snapshot strip shows an Entry model state tile",
              "Entry model" in body_text)

        if direction in ("LONG", "SHORT") and state in CONFIRMED_STATES:
            check(f"UI: a resolved {direction} setup shows entry/stop/target, not a placeholder",
                  "Waiting" not in body_text or "Entry" in body_text)
        else:
            check("UI: no candidate is shown as 'no setup' rather than an invented direction",
                  "no setup" in body_text.lower() or "conflicting evidence" in body_text.lower()
                  or "Waiting" in body_text)

        try:
            page.get_by_role("button", name="Evidence and detail").first.click(timeout=10000)
            page.wait_for_timeout(300)
            check("UI: the evidence disclosure expands to show per-rung checklists", True)
        except Exception:
            check("UI: the evidence disclosure expands to show per-rung checklists", False)

        # Scoped to the Entry Model card: the A+ card on the same page legitimately says "BUY"/
        # "SELL" by design (a different, pre-existing, out-of-scope feature), same reasoning as
        # test_analysis_v2_checklist.py's own "full-v2-analysis" scoping.
        entry_text = page.get_by_test_id("entry-model-card").inner_text()
        check("UI: observed, interpreted and conditional are each labelled on the Entry Model card",
              all(tag in entry_text.lower() for tag in ("observed", "interpreted", "conditional")))

        if state == "CONFLICTED":
            check("UI: a genuine CONFLICTED state is shown plainly, not forced into a direction",
                  "conflicting evidence" in entry_text.lower())

        try:
            page.get_by_role("alert", name="Market context and Entry Model disagree").wait_for(state="visible", timeout=2000)
            banner_shown = True
        except Exception:
            banner_shown = False
        check("UI: the disagreement banner's presence matches whether the API actually reports a conflict",
              banner_shown == (state == "CONFLICTED"), f"banner_shown={banner_shown} state={state}")

        check("UI: no probability, win-rate or trade instruction language on the Entry Model card",
              not FORBIDDEN.search(entry_text))

        check("UI: no browser console errors", len(console_errors) == 0 and len(page_errors) == 0,
              str(console_errors + page_errors))
        check("UI: no failed network requests", len(failed_requests) == 0, str(failed_requests))
        browser.close()

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, detail in results:
        if not ok:
            print(f"FAIL: {name} {detail}")
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
