"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Sparkles } from "lucide-react";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetFooter,
} from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { FundedNextContextCard } from "./fundednext-context-card";
import { cn } from "@/lib/utils";
import { formatPrice } from "@/lib/format";
import { api, ApiError } from "@/lib/api";
import type { Trade, TradeReview } from "@/lib/types";

const ALIGNMENT_STYLE: Record<string, string> = {
  ALIGNED: "text-bullish bg-bullish/10",
  PARTIALLY_ALIGNED: "text-warning bg-warning/10",
  NOT_ALIGNED: "text-bearish bg-bearish/10",
  UNKNOWN: "text-muted-foreground bg-muted",
};

function AlignmentBadge({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-xs py-0.5">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded", ALIGNMENT_STYLE[value] ?? ALIGNMENT_STYLE.UNKNOWN)}>
        {value.replace(/_/g, " ")}
      </span>
    </div>
  );
}

export function TradeDetailSheet({
  tradeId,
  onOpenChange,
  onClosed,
}: {
  tradeId: number | null;
  onOpenChange: (open: boolean) => void;
  onClosed: () => void;
}) {
  // Fetches the full trade detail (including fundednext_context, which the
  // list endpoint deliberately omits to keep the table lean) rather than
  // reusing the row object the table already had. `trade` is derived so it
  // only ever reflects the currently-selected tradeId — no separate
  // synchronous reset call needed when the selection changes.
  const [fetched, setFetched] = useState<{ id: number; data: Trade } | null>(null);
  const trade = fetched?.id === tradeId ? fetched.data : null;
  const [exitPrice, setExitPrice] = useState("");
  const [result, setResult] = useState<"WIN" | "LOSS" | "BE">("WIN");
  const [rMultiple, setRMultiple] = useState("");
  const [pnl, setPnl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Same "derive from a keyed fetch result" pattern as `trade` above — no
  // separate synchronous reset needed when the selected trade changes.
  const [fetchedReview, setFetchedReview] = useState<{ id: number; data: TradeReview } | null>(null);
  const review = fetchedReview?.id === tradeId ? fetchedReview.data : null;
  const [showReview, setShowReview] = useState(false);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [reviewError, setReviewError] = useState(false);
  const [generatingAiReview, setGeneratingAiReview] = useState(false);

  useEffect(() => {
    if (tradeId === null) return;
    let cancelled = false;
    api.trade(tradeId).then((t) => !cancelled && setFetched({ id: tradeId, data: t }));
    return () => {
      cancelled = true;
    };
  }, [tradeId]);

  async function handleToggleReview() {
    const next = !showReview;
    setShowReview(next);
    if (next && trade && review === null && !reviewLoading) {
      setReviewLoading(true);
      setReviewError(false);
      try {
        const data = await api.tradeReview(trade.id);
        setFetchedReview({ id: trade.id, data });
      } catch {
        setReviewError(true);
      } finally {
        setReviewLoading(false);
      }
    }
  }

  async function handleGenerateAiReview() {
    if (!trade) return;
    setGeneratingAiReview(true);
    try {
      const data = await api.generateTradeReview(trade.id);
      setFetchedReview({ id: trade.id, data });
    } catch {
      // deterministic review stays displayed either way
    } finally {
      setGeneratingAiReview(false);
    }
  }

  async function handleClose() {
    if (!trade) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.closeTrade(trade.id, {
        exit_price: Number(exitPrice),
        result,
        r_multiple: rMultiple ? Number(rMultiple) : undefined,
        pnl: pnl ? Number(pnl) : undefined,
      });
      setExitPrice("");
      setRMultiple("");
      setPnl("");
      onClosed();
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to close trade.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Sheet open={tradeId !== null} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-md">
        {trade && (
          <>
            <SheetHeader>
              <SheetTitle>
                Trade #{trade.id} —{" "}
                <span className={trade.direction === "BUY" ? "text-bullish" : "text-bearish"}>
                  {trade.direction}
                </span>
              </SheetTitle>
              <SheetDescription>{trade.trade_date} {trade.trade_time}</SheetDescription>
            </SheetHeader>

            <div className="px-4 space-y-4 overflow-y-auto flex-1">
              <div className="grid grid-cols-3 gap-2 text-sm">
                <Field label="Entry" value={formatPrice(trade.entry)} />
                <Field label="Stop Loss" value={formatPrice(trade.stop_loss)} />
                <Field label="Take Profit" value={trade.take_profit ? formatPrice(trade.take_profit) : "—"} />
              </div>

              <div className="rounded border border-border p-3">
                <p className="text-[11px] font-semibold text-muted-foreground mb-2">MARKET CONTEXT AT ENTRY</p>
                <div className="grid grid-cols-2 gap-1.5 text-xs">
                  <Field label="H4" value={trade.h4_bias ?? "—"} />
                  <Field label="H1" value={trade.h1_bias ?? "—"} />
                  <Field label="M15" value={trade.m15_bias ?? "—"} />
                  <Field label="M5" value={trade.m5_bias ?? "—"} />
                  <Field label="Regime" value={trade.regime ?? "—"} />
                  <Field label="Liquidity" value={trade.liquidity ?? "None"} />
                  <Field label="MSS" value={trade.mss ?? "None"} />
                  <Field label="Displacement" value={trade.displacement ?? "None"} />
                </div>
              </div>

              <FundedNextContextCard snapshot={trade.fundednext_context} />

              {trade.notes && (
                <div>
                  <p className="text-[11px] font-semibold text-muted-foreground mb-1">NOTES</p>
                  <p className="text-sm text-foreground">{trade.notes}</p>
                </div>
              )}

              {trade.status === "CLOSED" ? (
                <div className="rounded border border-border p-3">
                  <p className="text-[11px] font-semibold text-muted-foreground mb-2">RESULT</p>
                  <div className="grid grid-cols-2 gap-1.5 text-xs">
                    <Field label="Exit" value={trade.exit_price ? formatPrice(trade.exit_price) : "—"} />
                    <Field
                      label="Result"
                      value={trade.result ?? "—"}
                      className={cn(
                        trade.result === "WIN" ? "text-bullish" : trade.result === "LOSS" ? "text-bearish" : "text-warning"
                      )}
                    />
                    <Field label="R Multiple" value={trade.r_multiple !== null ? trade.r_multiple.toFixed(2) : "—"} />
                    <Field label="P/L" value={trade.pnl !== null ? `$${trade.pnl.toFixed(2)}` : "—"} />
                  </div>

                  <button
                    onClick={handleToggleReview}
                    className="text-[11px] text-muted-foreground hover:text-foreground underline mt-2"
                  >
                    {showReview ? "Hide review" : "Review Trade"}
                  </button>

                  {showReview && (
                    reviewLoading ? (
                      <p className="text-xs text-muted-foreground mt-2">Loading review…</p>
                    ) : reviewError ? (
                      <p className="text-xs text-muted-foreground mt-2">Review unavailable.</p>
                    ) : review ? (
                      <div className="mt-2 border-t border-border pt-2 text-xs space-y-2">
                        <div>
                          <AlignmentBadge label="Strategy alignment" value={review.strategy_alignment} />
                          <AlignmentBadge label="Setup alignment" value={review.setup_alignment} />
                          <AlignmentBadge label="Execution alignment" value={review.execution_alignment} />
                          <AlignmentBadge label="Risk alignment" value={review.risk_alignment} />
                        </div>

                        {review.deviations.length > 0 && (
                          <div>
                            <p className="text-[10px] font-semibold text-muted-foreground uppercase mb-1">Deviations</p>
                            {review.deviations.map((d, i) => (
                              <p key={i} className="text-foreground">
                                <span className="font-medium">{d.type.replace(/_/g, " ")}:</span> {d.evidence}
                              </p>
                            ))}
                          </div>
                        )}

                        <div>
                          <p className="text-[10px] font-semibold text-muted-foreground uppercase mb-1">Rule Observations</p>
                          {review.rule_observations.map((o, i) => (
                            <p key={i} className="text-foreground">{o}</p>
                          ))}
                        </div>

                        {review.interpretation ? (
                          <div>
                            <p className="text-[10px] font-semibold text-muted-foreground uppercase mb-1">AI Review</p>
                            <p className="text-foreground">{review.interpretation}</p>
                            {review.similar_trade_context && (
                              <p className="text-foreground mt-1">{review.similar_trade_context}</p>
                            )}
                          </div>
                        ) : (
                          <button
                            onClick={handleGenerateAiReview}
                            disabled={generatingAiReview}
                            className="text-[11px] text-muted-foreground hover:text-foreground underline"
                          >
                            {generatingAiReview ? "Generating…" : "Generate AI review"}
                          </button>
                        )}
                      </div>
                    ) : null
                  )}
                </div>
              ) : (
                <div className="rounded border border-border p-3 space-y-2">
                  <p className="text-[11px] font-semibold text-muted-foreground">CLOSE THIS TRADE</p>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <Label className="mb-1 block text-xs">Exit Price</Label>
                      <Input type="number" step="0.01" value={exitPrice} onChange={(e) => setExitPrice(e.target.value)} />
                    </div>
                    <div>
                      <Label className="mb-1 block text-xs">Result</Label>
                      <div className="flex gap-1">
                        {(["WIN", "LOSS", "BE"] as const).map((r) => (
                          <button
                            key={r}
                            type="button"
                            onClick={() => setResult(r)}
                            className={cn(
                              "flex-1 h-8 rounded text-xs font-medium border",
                              result === r ? "border-info bg-info/15 text-info" : "border-border text-muted-foreground"
                            )}
                          >
                            {r}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div>
                      <Label className="mb-1 block text-xs">R Multiple</Label>
                      <Input type="number" step="0.1" value={rMultiple} onChange={(e) => setRMultiple(e.target.value)} />
                    </div>
                    <div>
                      <Label className="mb-1 block text-xs">P/L ($)</Label>
                      <Input type="number" step="1" value={pnl} onChange={(e) => setPnl(e.target.value)} />
                    </div>
                  </div>
                  {error && <p className="text-xs text-bearish">{error}</p>}
                  <Button onClick={handleClose} disabled={submitting || !exitPrice} className="w-full">
                    {submitting ? "Saving…" : "Save Result"}
                  </Button>
                </div>
              )}
            </div>
            <SheetFooter>
              <Link
                href={`/assistant?trade=${trade.id}`}
                className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground border border-border rounded px-3 py-1.5 w-fit"
              >
                <Sparkles className="size-3.5" />
                Explain with AI
              </Link>
            </SheetFooter>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}

function Field({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div>
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className={cn("font-medium text-foreground", className)}>{value}</p>
    </div>
  );
}
