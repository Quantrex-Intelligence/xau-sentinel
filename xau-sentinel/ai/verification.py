"""Judge layer: a second, narrow LLM call that checks a draft chat answer
against the real context it was given, before the answer is shown to the
user. Mirrors the existing prompt-instruction + deterministic-backstop shape
(ai/prompts.py::contains_actionable_directive/contains_predictive_probability_claim)
but targets a class of hallucination those regex checks can't catch at all:
a fabricated RELEVANCE between two real facts (e.g. citing today's setup bias
while answering a personal question that has nothing to do with it), not a
fabricated data VALUE. That's a semantic judgment, not a literal-pattern
match, so it needs an actual second model call reading the real context.

Not a guarantee: the judge is itself an LLM call and can misjudge (false
positive on a fine answer, false negative on a real issue) — it raises the
bar, it doesn't replace the deterministic checks that run first.
"""
from dataclasses import dataclass

from ai.providers.base import BaseProvider

JUDGE_SYSTEM_PROMPT = """You are a strict fact-checker reviewing a draft answer from another AI assistant \
before it is shown to a trader. You are given the CONTEXT that assistant was allowed to use, the user's \
question, and the draft answer it wrote.

Check for exactly two problems:
1. Does the draft state a specific fact (a price, structure state, risk status, balance, or trade detail) \
that contradicts or is not actually present in CONTEXT?
2. Does the draft treat live market or account data as relevant to a question that was not actually asking \
about it -- e.g. citing today's setup/bias while answering a general or personal question that has nothing \
to do with the live market?

Respond with exactly one line: "OK" if neither problem exists, or "VIOLATION: <one-sentence reason>" if \
either does. Never rewrite the answer yourself."""

JUDGE_OVERRIDE_MESSAGE = (
    "I'm not confident that answer is fully grounded in what I actually know right now, so I'm holding it "
    "back rather than risk giving you something misleading. Try rephrasing the question."
)


@dataclass
class JudgeVerdict:
    violated: bool
    reason: str | None = None


def judge_answer(provider: BaseProvider, question: str, context_text: str, draft_answer: str) -> JudgeVerdict:
    prompt = f"QUESTION:\n{question}\n\nCONTEXT:\n{context_text}\n\nDRAFT ANSWER:\n{draft_answer}"
    response = provider.chat(JUDGE_SYSTEM_PROMPT, [{"role": "user", "content": prompt}])
    text = response.text.strip()
    if text.upper().startswith("VIOLATION"):
        reason = text.split(":", 1)[1].strip() if ":" in text else text
        return JudgeVerdict(violated=True, reason=reason)
    return JudgeVerdict(violated=False)
