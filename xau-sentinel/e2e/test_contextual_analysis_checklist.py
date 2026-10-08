"""E2E checklist for Stage 10 (Contextual AI Market & A+ Analysis). Requires
both servers running in MOCK mode with AI_PROVIDER=mock (see
e2e/test_migration_checklist.py for how to start them). Run directly:
    python e2e/test_contextual_analysis_checklist.py
"""
import sys

import httpx
from playwright.sync_api import sync_playwright

BASE = "http://localhost:3000"
API_BASE = "http://127.0.0.1:8000"
results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = ""):
    results.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'}: {name}" + (f" — {detail}" if detail and not condition else ""))


def main() -> int:
    # --- API-level checks ---
    body = httpx.get(f"{API_BASE}/api/strategy/aplus", timeout=15).json()
    check("API: /aplus still returns 200 with the pre-existing fields",
          all(k in body for k in ("rating", "criteria", "missing_conditions", "fundednext", "evaluated_at")))

    ca = body.get("contextual_analysis")
    check("API: contextual_analysis is present", ca is not None)
    if ca:
        check("API: rating and deterministic_rating both equal the top-level rating",
              ca.get("rating") == body["rating"] and ca.get("deterministic_rating") == body["rating"])
        check("API: contextual_analysis has all expected sections",
              all(k in ca for k in ("technical_summary", "strategy_summary", "market_intelligence",
                                     "historical_context", "risk_context", "interpretation", "uncertainties")))
        check("API: historical_context carries the descriptive-only note",
              "descriptive only" in ca["historical_context"].lower())
        check("API: response never mentions probability/win-forecast language",
              "probability" not in str(ca).lower() and "chance of winning" not in str(ca).lower())

    # Confirm the rating is stable and never influenced by re-evaluation timing.
    body2 = httpx.get(f"{API_BASE}/api/strategy/aplus", timeout=15).json()
    check("API: repeated evaluations agree on the deterministic rating",
          body2["rating"] == body["rating"])

    chat_resp = httpx.post(f"{API_BASE}/api/ai/chat", timeout=15,
                            json={"message": "Analyze XAUUSD — why is this setup developing?"}).json()
    check("API: chat response still has the pre-existing fields",
          all(k in chat_resp for k in ("answer", "context_used", "sources", "knowledge_used",
                                        "tools_used", "memory_used")))

    # --- Browser checks ---
    console_errors, page_errors, failed_requests = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}"))

        page.goto(f"{BASE}/market", wait_until="networkidle", timeout=30000)
        page.get_by_role("button", name="A+ evidence and AI explanation").first.click(timeout=15000)
        try:
            page.get_by_text("A+ Strategy Evaluation", exact=False).wait_for(state="visible", timeout=15000)
            check("UI: Market page still loads with the A+ panel", True)
        except Exception:
            check("UI: Market page still loads with the A+ panel", False)

        # The contextual analysis blocks live inside the A+ panel's "Full evaluation"
        # disclosure, which is collapsed by default since the summary-first layout
        # (a10aa88). Open it the way a user would before checking its contents.
        try:
            page.get_by_role("button", name="Full evaluation", exact=False).first.click(timeout=10000)
        except Exception:
            pass  # the section checks below report the failure if it never opened

        try:
            page.get_by_text("AI Interpretation", exact=False).wait_for(state="visible", timeout=15000)
            check("UI: AI Interpretation section renders", True)
        except Exception:
            check("UI: AI Interpretation section renders", False)

        try:
            # The A+ panel now mounts when its Details section opens, so its AI sections arrive later.
            page.get_by_text("Historical Context", exact=False).wait_for(state="visible", timeout=15000)
            check("UI: Historical Context section renders", True)
        except Exception:
            check("UI: Historical Context section renders", False)

        page.wait_for_timeout(1000)
        body_text = page.inner_text("body").lower()
        check("UI: no probability/win-forecast language anywhere on the Market page",
              "probability" not in body_text and "chance of winning" not in body_text)

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
