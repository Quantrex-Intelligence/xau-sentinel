"use client";

import { cn } from "@/lib/utils";
import type { Timeframe } from "@/lib/types";
import type { ChartOverlayToggles } from "./candlestick-chart";

const TIMEFRAMES: Timeframe[] = ["H4", "H1", "M15", "M5"];

const OVERLAY_LABELS: { key: keyof ChartOverlayToggles; label: string }[] = [
  { key: "zones", label: "Zones" },
  { key: "liquidity", label: "Liquidity" },
  { key: "setup", label: "Setup" },
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
            {tf}
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
