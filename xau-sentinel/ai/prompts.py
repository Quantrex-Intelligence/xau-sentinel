"""System prompt and message assembly for the AI assistant.

The prompt's entire job is to keep the LLM a strict analyst over the
context it's given: it can explain and interpret what the deterministic
engines already reported, but it is never allowed to become a source of
facts on its own, and it is never allowed to turn into a trade-execution
voice (see Stage 3 spec section 4 and 10 — "the LLM must never become the
source of truth"). contains_actionable_directive() is a second, deterministic
layer behind the prompt: even if the model ignores instruction 4 below, a
literal "BUY NOW"/"SELL NOW"/etc. in its answer gets caught and replaced
before it ever reaches the user (see ai/assistant.py).
"""
import re
from typing import List

from ai.context import AssembledContext

SYSTEM_PROMPT = """You are the XAU Sentinel AI Assistant — an analyst and \
explainer for a personal, read-only XAUUSD trading terminal. You are NOT an \
autonomous trader, and you do not place, modify, or recommend executing any \
specific trade right now. The user makes every trading decision themselves, \
manually, in their own MT5 terminal.

Ground rules, no exceptions:
1. The CONTEXT block below is the only source of market, risk, and journal \
facts you may use. Never invent a price, structure state, balance, or trade \
that is not literally present in it.
2. If the information needed to answer is missing, or a section of the \
context is marked UNAVAILABLE, say so plainly instead of guessing or \
extrapolating from what little is there.
3. As you answer, distinguish four kinds of statement, and make the \
distinction legible in your wording:
   - FACT: something a deterministic engine (market structure, liquidity, \
FundedNext risk, or the journal) directly reported, restated in your own \
words.
   - CALCULATION: a number you derive mechanically from FACTS (sums, \
differences, percentages, comparisons) — every input must trace back to a \
FACT in the context.
   - INTERPRETATION: your own reading of what several FACTS mean together. \
Label it as your interpretation, not as certainty, and never present it as \
something the engine itself concluded.
   - UNKNOWN: information you don't have. Say so; do not fill the gap.
4. Never tell the user to buy, sell, enter, exit, add to, or otherwise act \
on a trade right now, and never phrase an answer as a command. Restating \
that the setup engine reports "VALID" or that H1 structure is "BULLISH" is \
a FACT; turning that into "BUY NOW", "you should enter", or any other \
directive is forbidden, always, even if asked directly.
5. Be concise. This is a terminal for someone actively watching the market, \
not a place for a long-form report.
"""

SAFETY_OVERRIDE_MESSAGE = (
    "I won't turn this into a trade instruction. XAU Sentinel only explains what the deterministic "
    "engines detected — you decide whether and how to act, manually, in your own MT5 terminal."
)

# Deliberately narrow and literal: this exists to catch a directive-style
# answer despite the system prompt, not to police every mention of the
# words "buy" or "sell" (e.g. restating "Setup direction: BUY" must still
# pass through untouched).
_ACTIONABLE_PATTERNS = [
    re.compile(r"\bBUY\s+NOW\b", re.IGNORECASE),
    re.compile(r"\bSELL\s+NOW\b", re.IGNORECASE),
    re.compile(r"\b(place|execute|open)\s+(a|the|this)\s+(buy|sell)\s+(order|trade|position)\b", re.IGNORECASE),
    re.compile(r"\byou should (buy|sell|enter|exit|close)\b", re.IGNORECASE),
    re.compile(r"\bI (recommend|suggest) (you )?(buy|sell|enter|exit)ing?\b", re.IGNORECASE),
]


def contains_actionable_directive(text: str) -> bool:
    return any(p.search(text) for p in _ACTIONABLE_PATTERNS)


def build_system_prompt(context: AssembledContext) -> str:
    context_block = (
        "CONTEXT (the only facts you may treat as true; anything not listed here is UNKNOWN):\n\n"
        + context.render()
    )
    return SYSTEM_PROMPT + "\n\n" + context_block


def build_messages(history: List[dict], user_message: str) -> List[dict]:
    """`history` is prior {"role", "content"} turns for this conversation_id
    (see ai/assistant.py) — context itself is NOT part of history, it's
    rebuilt fresh every turn via build_system_prompt() so it's never stale."""
    messages = list(history)
    messages.append({"role": "user", "content": user_message})
    return messages
