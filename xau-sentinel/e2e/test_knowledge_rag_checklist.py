"""E2E checklist for Stage 5 (Strategy & Trading Knowledge RAG). Requires
both servers running in MOCK mode with AI_PROVIDER=mock (see
e2e/test_migration_checklist.py for how to start them). Run directly:
    python e2e/test_knowledge_rag_checklist.py
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
    docs = httpx.get(f"{API_BASE}/api/ai/knowledge/documents", timeout=10).json()
    check("API: knowledge documents are seeded", len(docs) > 0, str(docs))
    categories = {d["category"] for d in docs}
    check("API: strategy_rules category is seeded", "strategy_rules" in categories)
    check("API: fundednext_rules category is seeded", "fundednext_rules" in categories)
    check("API: methodology category is seeded", "methodology" in categories)

    relevant = httpx.post(f"{API_BASE}/api/ai/chat", timeout=15,
                           json={"message": "what reward to risk ratio does the A+ strategy require?"}).json()
    check("API: relevant question returns knowledge_used", len(relevant.get("knowledge_used", [])) > 0)
    check("API: relevant question's existing fields still present",
          "context_used" in relevant and "sources" in relevant and "answer" in relevant)

    irrelevant = httpx.post(f"{API_BASE}/api/ai/chat", timeout=15,
                             json={"message": "what is the capital of France?"}).json()
    check("API: off-topic question returns empty knowledge_used", irrelevant.get("knowledge_used") == [])

    note_resp = httpx.post(f"{API_BASE}/api/ai/knowledge/notes", timeout=10, json={
        "title": "E2E test playbook note", "content": "Only trade the London session liquidity sweep setup.",
    })
    check("API: user note can be added", note_resp.status_code == 200)
    docs_after = httpx.get(f"{API_BASE}/api/ai/knowledge/documents", timeout=10).json()
    check("API: added note appears in the listing", any(d["title"] == "E2E test playbook note" for d in docs_after))

    # --- Browser checks ---
    console_errors, page_errors, failed_requests = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}"))

        page.goto(f"{BASE}/assistant", wait_until="networkidle", timeout=30000)
        try:
            page.get_by_placeholder("Ask about market structure").wait_for(state="visible", timeout=15000)
            check("UI: Assistant page loads", True)
        except Exception:
            check("UI: Assistant page loads", False)

        # Note: the label is styled with CSS text-transform:uppercase, so
        # Playwright's rendered inner_text reports it as "KNOWLEDGE
        # REFERENCED:" even though the source renders "Knowledge referenced:".
        page.fill(
            "input[placeholder*='Ask about market structure']",
            "What does the A+ strategy require for the stop-loss buffer?",
        )
        page.get_by_role("button", name="Send").click()
        try:
            page.get_by_text("KNOWLEDGE REFERENCED:", exact=False).wait_for(state="visible", timeout=15000)
            check("UI: knowledge sources shown for a strategy question", True)
        except Exception:
            check("UI: knowledge sources shown for a strategy question", False)

        page.fill("input[placeholder*='Ask about market structure']", "what is the capital of France?")
        page.get_by_role("button", name="Send").click()
        page.wait_for_timeout(2000)
        body_text = page.inner_text("body")
        # Only one "KNOWLEDGE REFERENCED:" should be present (from the first,
        # relevant turn) — the second, off-topic turn must not add another.
        check("UI: off-topic question does not add a second knowledge panel",
              body_text.count("KNOWLEDGE REFERENCED:") == 1)

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
