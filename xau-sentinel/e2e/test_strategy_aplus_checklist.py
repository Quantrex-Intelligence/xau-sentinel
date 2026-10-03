"""E2E checklist for Stage 4 (A+ Strategy Evaluation). Requires both
servers running in MOCK mode with AI_PROVIDER=mock:
    MODE=mock AI_PROVIDER=mock uvicorn api.main:app --host 127.0.0.1 --port 8000
    (cd frontend && npm run dev)   # http://localhost:3000

Run directly (not via pytest — it drives two live dev servers rather than
exercising code in-process):
    python e2e/test_strategy_aplus_checklist.py
"""
import sys

import httpx
from playwright.sync_api import Page, sync_playwright

BASE = "http://localhost:3000"
API_BASE = "http://127.0.0.1:8000"
results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = ""):
    results.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'}: {name}" + (f" — {detail}" if detail and not condition else ""))


def wait_for(page: Page, text: str, timeout: int = 20000) -> bool:
    try:
        page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def main() -> int:
    # --- API-level checks first ---
    resp = httpx.get(f"{API_BASE}/api/strategy/aplus", timeout=15)
    check("API: /aplus returns 200", resp.status_code == 200)
    body = resp.json()
    check("API: rating is one of the three known values", body["rating"] in ("A+", "DEVELOPING", "INVALID"))
    check("API: direction is BUY/SELL/None", body["direction"] in ("BUY", "SELL", None))
    check("API: fundednext gate is present", "safety_level" in body["fundednext"])
    check("API: evaluated_at timestamp is present", bool(body.get("evaluated_at")))
    check("API: criteria statuses are only passed/failed/unknown",
          all(c["status"] in ("passed", "failed", "unknown") for c in body["criteria"]))

    # A rating never claims A+ without an empty missing_conditions list.
    if body["rating"] == "A+":
        check("API: A+ rating has no missing conditions", body["missing_conditions"] == [])

    # --- Browser checks ---
    console_errors, page_errors, failed_requests = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}"))

        page.goto(f"{BASE}/setups", wait_until="networkidle", timeout=30000)
        check("UI: Setups page loads", wait_for(page, "Summary"))
        check("UI: A+ Strategy Evaluation panel renders", wait_for(page, "A+ Strategy Evaluation"))
        check("UI: a rating is shown (A+ / DEVELOPING / INVALID)",
              any(wait_for(page, r, timeout=5000) for r in ("A+", "DEVELOPING", "INVALID")))
        page.get_by_role("button", name="Full evaluation").click()
        check("UI: FundedNext risk section is shown", wait_for(page, "FundedNext Risk", timeout=5000))
        check("UI: an evaluation timestamp is shown", "Evaluated" in page.inner_text("body"))

        # The frozen Stage 1 panel must still render untouched alongside it
        # (Panel titles are CSS-uppercased, so compare case-insensitively).
        page.get_by_role("button", name="Setup checklist").click()
        body_text = page.inner_text("body").upper()
        check("UI: Stage 1 SetupPanel still renders (not disturbed by Stage 4)",
              "SETUP CHECKLIST" in body_text and "LIQUIDITY SWEEP" in body_text)

        check("UI: no browser console errors", len(console_errors) == 0 and len(page_errors) == 0,
              str(console_errors + page_errors))
        check("UI: no failed network requests", len(failed_requests) == 0, str(failed_requests))

        browser.close()

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
