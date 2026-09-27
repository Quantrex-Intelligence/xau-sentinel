import { cn } from "@/lib/utils";
import type { ChatResponse } from "@/lib/types";
import { ContextIndicator } from "./context-indicator";
import { KnowledgeSources } from "./knowledge-sources";

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
  response?: ChatResponse;
  /** Set on an assistant turn that failed client-side (e.g. network error) —
   * rendered distinctly, never mistaken for a real answer. */
  isError?: boolean;
}

export function ChatMessage({ turn }: { turn: ChatTurn }) {
  const isUser = turn.role === "user";
  return (
    <div className={cn("flex flex-col gap-1", isUser ? "items-end" : "items-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-md px-3 py-2 text-sm whitespace-pre-wrap",
          isUser
            ? "bg-primary text-primary-foreground"
            : turn.isError
              ? "bg-bearish/10 text-bearish border border-bearish/30"
              : "bg-muted text-foreground"
        )}
      >
        {turn.content}
      </div>
      {!isUser && turn.response && (
        <div className="max-w-[85%] w-full">
          <ContextIndicator sources={turn.response.sources} category={turn.response.category} />
          <KnowledgeSources sources={turn.response.knowledge_used} />
        </div>
      )}
    </div>
  );
}
