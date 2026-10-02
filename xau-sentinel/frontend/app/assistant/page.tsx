"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Panel } from "@/components/layout/panel";
import { ChatMessage, type ChatTurn } from "@/components/ai/chat-message";
import { SuggestedQuestions } from "@/components/ai/suggested-questions";
import { MemoryPanel } from "@/components/ai/memory-panel";
import { MarketIntelligencePanel } from "@/components/market-intelligence/market-intelligence-panel";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { api, ApiError } from "@/lib/api";
import { useMediaQuery } from "@/lib/use-media-query";
import type { AiConfig } from "@/lib/types";

export default function AssistantPage() {
  // useSearchParams() needs a Suspense boundary above it in the app router.
  return (
    <Suspense fallback={null}>
      <AssistantPageInner />
    </Suspense>
  );
}

function AssistantPageInner() {
  const searchParams = useSearchParams();
  const tradeIdParam = searchParams.get("trade");

  const [aiConfig, setAiConfig] = useState<AiConfig | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [conversationId, setConversationId] = useState<string | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [memoryPrefill, setMemoryPrefill] = useState<string | undefined>(undefined);
  const bottomRef = useRef<HTMLDivElement>(null);
  const autoAskedTradeRef = useRef<string | null>(null);
  // Must be called unconditionally (Rules of Hooks) -- the early returns
  // below for aiConfig===null/unconfigured mean this can't live any later.
  const isDesktop = useMediaQuery("(min-width: 1024px)");

  useEffect(() => {
    api
      .aiConfig()
      .then(setAiConfig)
      .catch(() =>
        setAiConfig({ configured: false, provider: "unknown", model: null, reason: "Could not reach the API." })
      );
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, loading]);

  // Deep-linked from a trade's detail sheet ("Explain with AI") — ask once
  // automatically, scoped to ONLY that trade's captured-at-entry context.
  useEffect(() => {
    if (!aiConfig?.configured || !tradeIdParam) return;
    if (autoAskedTradeRef.current === tradeIdParam) return;
    autoAskedTradeRef.current = tradeIdParam;
    send(`Explain trade #${tradeIdParam} using the context captured at entry.`, undefined, Number(tradeIdParam));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aiConfig?.configured, tradeIdParam]);

  async function send(message: string, contextScope?: string[], tradeId?: number) {
    if (!message.trim() || loading) return;
    setInput("");
    setTurns((t) => [...t, { role: "user", content: message }]);
    setLoading(true);
    try {
      const response = await api.aiChat({
        message,
        conversation_id: conversationId,
        context_scope: contextScope,
        trade_id: tradeId,
      });
      setConversationId(response.conversation_id);
      setTurns((t) => [...t, { role: "assistant", content: response.answer, response }]);
    } catch (err) {
      const detail = err instanceof ApiError ? err.message : "Something went wrong reaching the AI assistant.";
      setTurns((t) => [...t, { role: "assistant", content: detail, isError: true }]);
    } finally {
      setLoading(false);
    }
  }

  function clearConversation() {
    setTurns([]);
    setConversationId(undefined);
  }

  if (aiConfig === null) return null;

  if (!aiConfig.configured) {
    return (
      <div className="p-4 max-w-2xl">
        <Panel title="AI Assistant">
          <p className="text-sm text-muted-foreground">Not configured — {aiConfig.reason}</p>
          <p className="text-xs text-muted-foreground mt-3">
            This is an analyst and explainer over XAU Sentinel&apos;s own deterministic engine — it
            never places, modifies, or recommends executing a trade. Set{" "}
            <code className="text-foreground">AI_PROVIDER</code> and{" "}
            <code className="text-foreground">AI_API_KEY</code> on the API server to enable it (see
            .env.example), or set <code className="text-foreground">AI_PROVIDER=mock</code> to try the
            offline demo provider.
          </p>
        </Panel>
      </div>
    );
  }

  return (
    <div className="p-4 grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-4 h-[calc(100vh-3.5rem)]">
      <div className="flex flex-col gap-3 min-w-0 h-full">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold text-foreground tracking-tight">AI Assistant</h1>
            <p className="text-xs text-muted-foreground mt-0.5">
              Explains what the deterministic engines detected. It never places or recommends a trade —
              you decide, manually, in MT5.
            </p>
          </div>
          <button
            onClick={clearConversation}
            disabled={turns.length === 0}
            className="shrink-0 text-xs text-muted-foreground hover:text-foreground border border-border rounded px-2 py-1 disabled:opacity-40"
          >
            Clear conversation
          </button>
        </div>

        {/* Below lg, the right rail collapses into tabs above the chat so
            the conversation stays primary instead of being pushed down by
            three stacked panels. Only one of this and the desktop rail
            below is ever mounted (see isDesktop). */}
        {!isDesktop && (
          <Tabs defaultValue="suggestions">
            <TabsList>
              <TabsTrigger value="suggestions">Suggestions</TabsTrigger>
              <TabsTrigger value="memory">Memory</TabsTrigger>
              <TabsTrigger value="market-intel">Market Intel</TabsTrigger>
            </TabsList>
            <TabsContent value="suggestions">
              <SuggestedQuestions onSelect={(q, scope) => send(q, scope)} disabled={loading} />
            </TabsContent>
            <TabsContent value="memory">
              <MemoryPanel prefill={memoryPrefill} onPrefillConsumed={() => setMemoryPrefill(undefined)} />
            </TabsContent>
            <TabsContent value="market-intel">
              <MarketIntelligencePanel />
            </TabsContent>
          </Tabs>
        )}

        <ScrollArea className="flex-1 rounded-md border border-border bg-card">
          <div className="p-4 flex flex-col gap-3">
            {turns.length === 0 && (
              <p className="text-sm text-muted-foreground">
                Ask about current market structure, the setup state, FundedNext risk, or your journal —
                or pick a question above.
              </p>
            )}
            {turns.map((turn, i) => (
              <ChatMessage key={i} turn={turn} onSaveToMemory={setMemoryPrefill} />
            ))}
            {loading && <div className="text-xs text-muted-foreground">Thinking…</div>}
            <div ref={bottomRef} />
          </div>
        </ScrollArea>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
          className="flex gap-2"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about market structure, setup, risk, or your journal…"
            disabled={loading}
            className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={loading || !input.trim()}
            className="rounded-md bg-primary text-primary-foreground text-sm font-medium px-4 py-2 disabled:opacity-50"
          >
            Send
          </button>
        </form>
      </div>

      {isDesktop && (
        <div className="flex flex-col gap-4 overflow-y-auto">
          <SuggestedQuestions onSelect={(q, scope) => send(q, scope)} disabled={loading} />
          <MemoryPanel prefill={memoryPrefill} onPrefillConsumed={() => setMemoryPrefill(undefined)} />
          <MarketIntelligencePanel />
        </div>
      )}
    </div>
  );
}
