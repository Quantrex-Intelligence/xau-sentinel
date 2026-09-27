"""A deterministic, offline provider — no network call, no API key, no
external dependency. Selected with AI_PROVIDER=mock, and used directly by
the test suite so the ai/ layer can be exercised without depending on
network access or a real credential.

Its answers are template text built only from what it was given (the last
user message, and whether a context block is present) — never a
fabrication, and never claiming to be a real model's output (the text says
"[MOCK PROVIDER]" up front, same spirit as the rest of the app never
presenting mock data as live).
"""
from typing import List

from ai.providers.base import BaseProvider, ProviderResponse

MODEL_NAME = "mock-deterministic-v1"


class MockProvider(BaseProvider):
    name = "mock"
    model = MODEL_NAME

    def chat(self, system: str, messages: List[dict]) -> ProviderResponse:
        last_user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        has_context = "CONTEXT" in system

        text = (
            "[MOCK PROVIDER — offline, deterministic, no API key used]\n"
            f"You asked: {last_user}\n\n"
            + (
                "I reviewed the context block in the system prompt above and would normally "
                "answer from it alone."
                if has_context
                else "No context block was supplied."
            )
            + " This is a template response — set AI_PROVIDER=anthropic and AI_API_KEY for real answers."
        )
        return ProviderResponse(text=text, provider=self.name, model=MODEL_NAME)
