"use client";

import { useState } from "react";
import { Panel } from "@/components/layout/panel";
import { StateBadge } from "@/components/market/structure-badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { useMarket } from "@/lib/market-context";
import { api, ApiError } from "@/lib/api";
import type { Timeframe } from "@/lib/types";

const TIMEFRAMES: Timeframe[] = ["H4", "H1", "M15", "M5"];

export function NewTradeForm({ onCreated }: { onCreated: () => void }) {
  const { snapshot } = useMarket();
  const structure = snapshot?.structure ?? {};

  const [direction, setDirection] = useState<"BUY" | "SELL">("BUY");
  const [entry, setEntry] = useState("");
  const [stopLoss, setStopLoss] = useState("");
  const [takeProfit, setTakeProfit] = useState("");
  const [setupLabel, setSetupLabel] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const plannedRr =
    entry && stopLoss && takeProfit && Number(entry) !== Number(stopLoss)
      ? Math.abs((Number(takeProfit) - Number(entry)) / (Number(entry) - Number(stopLoss)))
      : null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!entry || !stopLoss) {
      setError("Entry and Stop Loss are required.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      // The trade's date and time are captured server-side in the project's
      // session timezone so both always describe the same instant.
      await api.createTrade({
        direction,
        entry: Number(entry),
        stop_loss: Number(stopLoss),
        take_profit: takeProfit ? Number(takeProfit) : undefined,
        planned_rr: plannedRr ?? undefined,
        setup: setupLabel || undefined,
        notes: notes || undefined,
      });
      setEntry("");
      setStopLoss("");
      setTakeProfit("");
      setSetupLabel("");
      setNotes("");
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save trade.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Panel title="New Trade">
      <p className="text-xs text-muted-foreground mb-3">
        Captured automatically from current market analysis — nothing here needs to be typed.
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4">
        {TIMEFRAMES.map((tf) => (
          <div key={tf} className="rounded border border-border p-2">
            <p className="text-[10px] text-muted-foreground mb-1">{tf}</p>
            {structure[tf] ? <StateBadge state={structure[tf]!.state} /> : <span className="text-xs">—</span>}
          </div>
        ))}
      </div>

      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="mb-1.5 block text-xs">Direction</Label>
            <div className="flex gap-1">
              {(["BUY", "SELL"] as const).map((d) => (
                <button
                  type="button"
                  key={d}
                  onClick={() => setDirection(d)}
                  className={`flex-1 h-8 rounded text-sm font-medium border transition-colors ${
                    direction === d
                      ? d === "BUY"
                        ? "bg-bullish/15 text-bullish border-bullish/40"
                        : "bg-bearish/15 text-bearish border-bearish/40"
                      : "border-border text-muted-foreground"
                  }`}
                >
                  {d}
                </button>
              ))}
            </div>
          </div>
          <div>
            <Label className="mb-1.5 block text-xs">Setup</Label>
            <Input value={setupLabel} onChange={(e) => setSetupLabel(e.target.value)} placeholder="e.g. Sweep + MSS" />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div>
            <Label className="mb-1.5 block text-xs">Entry</Label>
            <Input type="number" step="0.01" value={entry} onChange={(e) => setEntry(e.target.value)} required />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs">Stop Loss</Label>
            <Input type="number" step="0.01" value={stopLoss} onChange={(e) => setStopLoss(e.target.value)} required />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs">Take Profit</Label>
            <Input type="number" step="0.01" value={takeProfit} onChange={(e) => setTakeProfit(e.target.value)} />
          </div>
        </div>

        <p className="text-xs text-muted-foreground">
          Planned RR: <span className="font-mono">{plannedRr ? `1:${plannedRr.toFixed(2)}` : "—"}</span>
        </p>

        <div>
          <Label className="mb-1.5 block text-xs">Notes</Label>
          <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Why did you take this trade?" rows={2} />
        </div>

        {error && <p className="text-xs text-bearish">{error}</p>}

        <Button type="submit" disabled={submitting} className="w-full">
          {submitting ? "Saving…" : "Save Trade"}
        </Button>
      </form>
    </Panel>
  );
}
