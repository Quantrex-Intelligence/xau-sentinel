"use client";

/** Straight from the Stage 3 spec's own example question list (section 3).
 * A question's `scope` narrows the context sent for it — the journal/risk
 * questions ask for exactly the section they need, nothing more. */
const QUESTIONS: { label: string; scope?: string[] }[] = [
  { label: "What is the current market structure?", scope: ["market"] },
  { label: "Why is the market classified as ranging?", scope: ["market"] },
  { label: "What happened during the latest liquidity sweep?", scope: ["market"] },
  { label: "Explain the current setup state.", scope: ["market"] },
  { label: "How much FundedNext daily loss do I have remaining?", scope: ["risk"] },
  { label: "Summarize my recent trading performance.", scope: ["journal"] },
  { label: "What patterns appear in my recent journal?", scope: ["journal"] },
];

export function SuggestedQuestions({
  onSelect,
  disabled,
}: {
  onSelect: (question: string, scope?: string[]) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {QUESTIONS.map((q) => (
        <button
          key={q.label}
          type="button"
          disabled={disabled}
          onClick={() => onSelect(q.label, q.scope)}
          className="text-xs text-muted-foreground hover:text-foreground hover:border-foreground/30 border border-border rounded-full px-2.5 py-1 disabled:opacity-50 disabled:pointer-events-none transition-colors"
        >
          {q.label}
        </button>
      ))}
    </div>
  );
}
