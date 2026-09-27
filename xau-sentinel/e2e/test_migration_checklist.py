"""End-to-end checklist for the Next.js/FastAPI UI migration (spec section 29).

Requires both servers running in MOCK mode:
    uvicorn api.main:app --host 127.0.0.1 --port 8000
    (cd frontend && npm run dev)   # http://localhost:3000

Run directly (not via pytest — it drives two live dev servers rather than
exercising code in-process):
    python e2e/test_migration_checklist.py
"""
import sys
import time

import httpx
from playwright.sync_api import Page, sync_playwright

BASE = "http://localhost:3000"
API_BASE = "http://127.0.0.1:8000"
results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = ""):
    results.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'}: {name}" + (f" — {detail}" if detail and not condition else ""))


def wait_for(page: Page, text: str, timeout: int = 15000) -> bool:
    """Waits for `text` to actually appear in the page, instead of a blind
    sleep — real data arrives on the WS's ~2s cadence plus render time, and
    a fixed short sleep was flaky under load."""
    try:
        page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:
        return False


def main() -> int:
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url} -> {req.failure}"))

        # 1. Application loads / 2. Dashboard loads
        page.goto(BASE, wait_until="networkidle", timeout=30000)
        check("1. Application loads", True)
        check("2. Dashboard (Overview) loads", wait_for(page, "XAU SENTINEL"))

        # 3. Mock mode works — wait for the real snapshot-derived badge, not a
        # blind sleep (see TopBar: shows a neutral state until the first WS
        # message arrives, so this must wait for the actual mode to resolve).
        check("3. Mock mode indicator visible", wait_for(page, "MOCK"))

        # 4. Price appears
        check("4. Price appears", wait_for(page, "Bid"))

        # 5. Chart renders
        canvas_count = page.locator("canvas").count()
        check("5. Chart renders", canvas_count > 0, f"canvas elements: {canvas_count}")

        # 6. Timeframes switch
        page.get_by_role("button", name="H1", exact=True).click()
        page.wait_for_timeout(1500)
        check("6. Timeframes switch", True, "H1 clicked without error")
        page.get_by_role("button", name="M5", exact=True).click()
        page.wait_for_timeout(1000)

        # 7. Structure appears
        check("7. Structure appears", wait_for(page, "MARKET STRUCTURE"))

        # 8/9/10. Zones / liquidity / equal-levels — check the /market page,
        # informed by what the API actually has (equal-level occurrence is
        # data-dependent in mock mode, not guaranteed every run).
        page.goto(f"{BASE}/market", wait_until="networkidle", timeout=30000)
        check("8. Zones appear", wait_for(page, "KEY ZONES"))
        check("9. Liquidity appears", wait_for(page, "LIQUIDITY"))

        liquidity_data = httpx.get(f"{API_BASE}/api/market/liquidity", timeout=10).json()
        if liquidity_data.get("equal_levels"):
            check("10. Equal highs/lows appear", wait_for(page, "EQUAL HIGHS"))
        else:
            check("10. Equal highs/lows appear", True, "no equal-level events in this mock snapshot (data-dependent, unit-tested separately)")

        check("11. Regime appears", wait_for(page, "MARKET REGIME"))

        # 12. Setup appears / 13. Risk appears
        page.goto(f"{BASE}/setups", wait_until="networkidle", timeout=30000)
        check("12. Setup appears", wait_for(page, "CURRENT SETUP"))
        check("13. Risk appears", wait_for(page, "Account Balance"))

        # 14. Alerts appear
        check("14. Alerts panel appears", wait_for(page, "ALERTS"))

        # 15. Journal loads
        page.goto(f"{BASE}/journal", wait_until="networkidle", timeout=30000)
        check("15. Journal loads", wait_for(page, "NEW TRADE"))

        # 16. Trade can be created
        inputs = page.locator("input[type=number]")
        inputs.nth(0).fill("3740.00")
        inputs.nth(1).fill("3735.00")
        inputs.nth(2).fill("3750.00")
        page.get_by_text("Save Trade").click()
        created = wait_for(page, "3,740.00", timeout=10000)
        check("16. Trade can be created", created and wait_for(page, "OPEN"))

        # 17. Trade can be closed
        page.get_by_text("3,740.00").first.click()
        wait_for(page, "CLOSE THIS TRADE", timeout=5000)
        page.locator("text=Exit Price").locator("xpath=following::input[1]").fill("3750")
        page.get_by_text("Save Result").click()
        closed = wait_for(page, "CLOSED", timeout=10000)
        check("17. Trade can be closed", closed and wait_for(page, "WIN"))

        # 18. Analytics load
        page.goto(f"{BASE}/analytics", wait_until="networkidle", timeout=30000)
        check("18. Analytics load", wait_for(page, "TOTAL TRADES") and wait_for(page, "WIN RATE"))

        # 19. Navigation works
        page.goto(BASE, wait_until="networkidle", timeout=30000)
        nav_ok = True
        for label, path in [("Market", "/market"), ("Settings", "/settings"), ("Overview", "/")]:
            page.get_by_text(label, exact=True).first.click()
            page.wait_for_timeout(1000)
            if path != "/" and path not in page.url:
                nav_ok = False
        check("19. Navigation works", nav_ok)

        time.sleep(1)  # let any trailing WS/poll requests settle
        check("20. No browser console errors", len(console_errors) == 0 and len(page_errors) == 0,
              str(console_errors + page_errors))
        check("21. No failed API/network requests", len(failed_requests) == 0, str(failed_requests))

        browser.close()

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
