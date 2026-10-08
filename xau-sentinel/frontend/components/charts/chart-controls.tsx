"use client";

import { cn } from "@/lib/utils";
import type { Timeframe } from "@/lib/types";
import type { ChartOverlayToggles } from "./candlestick-chart";

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
}: {
  timeframe: Timeframe;
  onTimeframeChange: (tf: Timeframe) => void;
  overlays: ChartOverlayToggles;
  onOverlaysChange: (overlays: ChartOverlayToggles) => void;
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
