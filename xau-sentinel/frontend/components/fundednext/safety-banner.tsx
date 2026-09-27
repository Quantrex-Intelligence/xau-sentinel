import { cn } from "@/lib/utils";
import type { SafetyLevel } from "@/lib/types";
import { AlertTriangle, CheckCircle2, HelpCircle, ShieldAlert, XCircle } from "lucide-react";

const LEVEL_CONFIG: Record<SafetyLevel, { label: string; className: string; Icon: typeof CheckCircle2 }> = {
  SAFE: { label: "SAFE", className: "text-bullish bg-bullish/10 border-bullish/30", Icon: CheckCircle2 },
  WARNING: { label: "WARNING", className: "text-warning bg-warning/10 border-warning/30", Icon: AlertTriangle },
  CRITICAL: { label: "CRITICAL", className: "text-bearish bg-bearish/10 border-bearish/30", Icon: ShieldAlert },
  BREACHED: { label: "BREACHED", className: "text-bearish bg-bearish/20 border-bearish/50", Icon: XCircle },
  UNKNOWN: { label: "UNKNOWN / DATA UNAVAILABLE", className: "text-muted-foreground bg-muted border-border", Icon: HelpCircle },
};

export function SafetyBanner({ level, reason }: { level: SafetyLevel; reason: string }) {
  const { label, className, Icon } = LEVEL_CONFIG[level];
  return (
    <div className={cn("rounded-md border px-4 py-3 flex items-center gap-3", className)}>
      <Icon className="size-6 shrink-0" />
      <div>
        <p className="text-lg font-bold tracking-wide">{label}</p>
        <p className="text-sm opacity-90">{reason}</p>
      </div>
    </div>
  );
}
