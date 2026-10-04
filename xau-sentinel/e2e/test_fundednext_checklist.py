"""E2E checklist for Stage 2 (FundedNext integration). Requires both servers
running in MOCK mode (see e2e/test_migration_checklist.py for how to start
them). Run directly:
    python e2e/test_fundednext_checklist.py
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
    # API-level checks first (fast, precise).
    status = httpx.get(f"{API_BASE}/api/fundednext/status", timeout=10).json()
    check("API: /status returns mock mode data", status["mode"] == "mock" and status["data_available"] is True)
    check("API: safety_level is a known state",
          status["safety_level"] in ("SAFE", "WARNING", "CRITICAL", "BREACHED", "UNKNOWN"))

    rules = httpx.get(f"{API_BASE}/api/fundednext/rules", timeout=10).json()
    check("API: /rules lists both account types", {r["account_type"] for r in rules} == {"stellar_2step", "stellar_lite"})

    settings = httpx.put(f"{API_BASE}/api/fundednext/settings",
                          json={"account_type": "stellar_lite", "phase": "funded"}, timeout=10).json()
    check("API: /settings PUT persists changes", settings["account_type"] == "stellar_lite" and settings["phase"] == "funded")
    status2 = httpx.get(f"{API_BASE}/api/fundednext/status", timeout=10).json()
    check("API: /status reflects updated settings", status2["account_type"] == "stellar_lite" and status2["phase"] == "funded")
    check("API: funded phase has no profit target", status2["profit_target"] is None)
    httpx.put(f"{API_BASE}/api/fundednext/settings", json={"account_type": "stellar_2step", "phase": "challenge"}, timeout=10)

    # Browser checks.
    console_errors, page_errors, failed_requests = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}"))

        page.goto(f"{BASE}/fundednext", wait_until="networkidle", timeout=30000)
        # The page title is the h1 "FundedNext" with a "Read-only monitoring" line beside
        # the mode badge (redesign 9053c10 replaced the old "FundedNext — read-only" title).
        try:
            page.get_by_role("heading", name="FundedNext", exact=True).wait_for(state="visible", timeout=15000)
            page.get_by_text("Read-only monitoring", exact=False).wait_for(state="visible", timeout=5000)
            check("UI: FundedNext page loads", True)
        except Exception:
            check("UI: FundedNext page loads", False)

        body = page.inner_text("body")
        check("UI: mock mode clearly labeled", "MOCK" in body)
        check("UI: safety banner visible", any(s in body for s in ("SAFE", "WARNING", "CRITICAL", "BREACHED", "UNKNOWN")))
        check("UI: loss limit bars visible", "Daily Loss Limit" in body and "Maximum Loss Limit" in body)
        check("UI: account configuration selector visible", "account configuration" in body.lower())

        # Interactive: switch account type and confirm the page actually
        # recomputes (2-Step's 10%/5% max/daily loss differs from Lite's 8%/4%).
        before_body = page.inner_text("body")
        page.get_by_text("Stellar Lite", exact=True).click()
        page.wait_for_timeout(1500)
        after_body = page.inner_text("body")
        check("UI: switching account type changes the displayed figures", before_body != after_body)
        page.get_by_text("Stellar 2-Step", exact=True).click()
        page.wait_for_timeout(1000)

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
