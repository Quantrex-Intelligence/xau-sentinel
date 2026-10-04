"use client";

import { AnalysisView } from "@/components/analysis/analysis-view";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/use-polling";

export default function AnalysisPage() {
  const { data, error, loading } = usePolling(() => api.analysisV2(), 15000);

  return (
    <div className="p-4 flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold text-foreground tracking-tight">Market analysis</h1>
        <p className="text-xs text-muted-foreground">
          Structured reading of closed candles. Facts, interpretation and conditional scenarios are labelled separately.
        </p>
      </div>
      <AnalysisView data={data} error={error} loading={loading} />
    </div>
  );
}
