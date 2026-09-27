"use client";

import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { formatPrice } from "@/lib/format";
import type { Trade } from "@/lib/types";

export function TradeTable({ trades, onSelect }: { trades: Trade[]; onSelect: (t: Trade) => void }) {
  if (trades.length === 0) {
    return <p className="text-sm text-muted-foreground py-6 text-center">No trades logged yet. Create one above.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Date</TableHead>
          <TableHead>Session</TableHead>
          <TableHead>Setup</TableHead>
          <TableHead>Dir</TableHead>
          <TableHead>Entry</TableHead>
          <TableHead>R</TableHead>
          <TableHead>Result</TableHead>
          <TableHead>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {trades.map((t) => (
          <TableRow key={t.id} className="cursor-pointer hover:bg-accent/50" onClick={() => onSelect(t)}>
            <TableCell className="font-mono text-xs">{t.trade_date}</TableCell>
            <TableCell className="text-xs">{t.session ?? "—"}</TableCell>
            <TableCell className="text-xs">{t.setup ?? "—"}</TableCell>
            <TableCell>
              <span className={cn("text-xs font-semibold", t.direction === "BUY" ? "text-bullish" : "text-bearish")}>
                {t.direction}
              </span>
            </TableCell>
            <TableCell className="font-mono text-xs">{formatPrice(t.entry)}</TableCell>
            <TableCell className="font-mono text-xs">
              {t.r_multiple !== null ? `${t.r_multiple >= 0 ? "+" : ""}${t.r_multiple.toFixed(2)}R` : "—"}
            </TableCell>
            <TableCell>
              {t.result ? (
                <span
                  className={cn(
                    "text-xs font-semibold",
                    t.result === "WIN" ? "text-bullish" : t.result === "LOSS" ? "text-bearish" : "text-warning"
                  )}
                >
                  {t.result}
                </span>
              ) : (
                <span className="text-xs text-muted-foreground">—</span>
              )}
            </TableCell>
            <TableCell>
              <span className={cn("text-xs", t.status === "OPEN" ? "text-info" : "text-muted-foreground")}>
                {t.status}
              </span>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
