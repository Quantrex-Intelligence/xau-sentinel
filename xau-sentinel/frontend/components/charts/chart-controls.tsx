"use client";

import { Lock, RotateCcw, Unlock, ZoomIn, ZoomOut } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Timeframe } from "@/lib/types";
import type { ChartHandle, ChartOverlayToggles } from "./candlestick-chart";

const TIMEFRAMES: Timeframe[] = ["M1", "M5", "M15", "H1", "H4", "D1"];

const TIMEFRAME_LABELS: Record<Timeframe, string> = {
  M1: "1m",
  M5: "5m",
  M15: "15m",
  H1: "1h",
  H4: "4h",
  D1: "1d",
};

const OVERLAY_LABELS: { key: keyof ChartOverlayToggles; label: string }[] = [
  { key: "zones", label: "Levels" },
  { key: "liquidity", label: "Liquidity" },
  { key: "structure", label: "Structure" },
  { key: "areas", label: "Key areas" },
  { key: "setup", label: "A+ lines" },
  { key: "ict", label: "ICT (LuxAlgo)" },
];

export function ChartControls({
  timeframe,
  onTimeframeChange,
  overlays,
  onOverlaysChange,
  priceScaleLocked,
  onPriceScaleLockedChange,
  chartHandle,
}: {
  timeframe: Timeframe;
  onTimeframeChange: (tf: Timeframe) => void;
  overlays: ChartOverlayToggles;
  onOverlaysChange: (overlays: ChartOverlayToggles) => void;
  priceScaleLocked: boolean;
  onPriceScaleLockedChange: (locked: boolean) => void;
  /** The chart lives in a sibling component, not a child of this one -- this ref is how these
   * buttons reach its imperative zoom/reset actions. */
  chartHandle: React.RefObject<ChartHandle | null>;
}) {
  return (
    <div className="flex items-center justify-between px-1 py-2 text-sm">
      <div className="flex items-center gap-1">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf}
            onClick={() => onTimeframeChange(tf)}
            className={cn(
              "px-2.5 py-1 rounded text-xs font-medium transition-colors",
              tf === timeframe
                ? "bg-info/15 text-info"
                : "text-muted-foreground hover:text-foreground hover:bg-accent"
            )}
          >
            {TIMEFRAME_LABELS[tf]}
          </button>
        ))}
        <button
          onClick={() => onPriceScaleLockedChange(!priceScaleLocked)}
          title={priceScaleLocked
            ? "Price scale locked — drag the right axis to adjust manually"
            : "Price scale auto-fits to the visible candles as you zoom/pan (TradingView's default)"}
          className={cn(
            "ml-1 flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors",
            priceScaleLocked
              ? "bg-info/15 text-info"
              : "text-muted-foreground hover:text-foreground hover:bg-accent"
          )}
        >
          {priceScaleLocked ? <Lock className="size-3" /> : <Unlock className="size-3" />}
          {priceScaleLocked ? "Scale locked" : "Auto scale"}
        </button>
        <div className="ml-1 flex items-center gap-0.5 border-l border-border pl-2">
          <button
            onClick={() => chartHandle.current?.zoomIn()}
            title="Zoom in"
            className="p-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
          >
            <ZoomIn className="size-3.5" />
          </button>
          <button
            onClick={() => chartHandle.current?.zoomOut()}
            title="Zoom out"
            className="p-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
          >
            <ZoomOut className="size-3.5" />
          </button>
          <button
            onClick={() => chartHandle.current?.resetView()}
            title="Reset view (fit all candles, clear scale lock)"
            className="p-1.5 rounded text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
          >
            <RotateCcw className="size-3.5" />
          </button>
        </div>
      </div>
      <div className="flex items-center gap-3">
        {OVERLAY_LABELS.map(({ key, label }) => (
          <label key={key} className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
            <input
              type="checkbox"
              checked={overlays[key]}
              onChange={(e) => onOverlaysChange({ ...overlays, [key]: e.target.checked })}
              className="accent-info"
            />
            {label}
          </label>
        ))}
      </div>
    </div>
  );
}
