"use client";

import { useState } from "react";
import { Panel } from "@/components/layout/panel";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import type { FundedNextSettings } from "@/lib/types";

const ACCOUNT_TYPES: { value: FundedNextSettings["account_type"]; label: string }[] = [
  { value: "stellar_2step", label: "Stellar 2-Step" },
  { value: "stellar_lite", label: "Stellar Lite" },
];

const PHASES: { value: FundedNextSettings["phase"]; label: string }[] = [
  { value: "challenge", label: "Challenge · Phase 1" },
  { value: "challenge_phase2", label: "Challenge · Phase 2" },
  { value: "funded", label: "Funded" },
];

export function AccountSelector({
  settings,
  onChanged,
}: {
  settings: FundedNextSettings;
  onChanged: () => void;
}) {
  const [saving, setSaving] = useState(false);

  async function update(patch: Partial<FundedNextSettings>) {
    setSaving(true);
    try {
      await api.updateFundedNextSettings(patch);
      onChanged();
    } finally {
      setSaving(false);
    }
  }

  return (
    <Panel title="Account Configuration">
      <div className="space-y-3">
        <div>
          <p className="text-xs text-muted-foreground mb-1.5">Account Type</p>
          <div className="flex gap-1">
            {ACCOUNT_TYPES.map((t) => (
              <button
                key={t.value}
                disabled={saving}
                onClick={() => update({ account_type: t.value })}
                className={cn(
                  "flex-1 h-8 rounded text-xs font-medium border transition-colors disabled:opacity-50",
                  settings.account_type === t.value
                    ? "border-info bg-info/15 text-info"
                    : "border-border text-muted-foreground"
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <p className="text-xs text-muted-foreground mb-1.5">Phase</p>
          <div className="flex gap-1">
            {PHASES.map((p) => (
              <button
                key={p.value}
                disabled={saving}
                onClick={() => update({ phase: p.value })}
                className={cn(
                  "flex-1 h-8 rounded text-xs font-medium border transition-colors disabled:opacity-50",
                  settings.phase === p.value
                    ? "border-info bg-info/15 text-info"
                    : "border-border text-muted-foreground"
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none pt-1">
          <input
            type="checkbox"
            checked={settings.consistency_enabled}
            disabled={saving}
            onChange={(e) => update({ consistency_enabled: e.target.checked })}
            className="accent-info"
          />
          On-Demand Rewards add-on active (enables the 40% consistency rule)
        </label>
      </div>
    </Panel>
  );
}
