import type { Analytics } from "@/lib/types";

export function WinLossBar({ stats }: { stats: Analytics }) {
  const total = stats.wins + stats.losses + stats.breakeven;
  if (total === 0) return <p className="text-xs text-muted-foreground">No closed trades yet.</p>;

  const winPct = (stats.wins / total) * 100;
  const lossPct = (stats.losses / total) * 100;
  const bePct = (stats.breakeven / total) * 100;

  return (
    <div>
      <div className="h-3 w-full rounded overflow-hidden flex bg-muted">
        <div style={{ width: `${winPct}%` }} className="bg-bullish" />
        <div style={{ width: `${lossPct}%` }} className="bg-bearish" />
        <div style={{ width: `${bePct}%` }} className="bg-warning" />
      </div>
      <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
        <span><span className="text-bullish font-medium">{stats.wins}</span> wins</span>
        <span><span className="text-bearish font-medium">{stats.losses}</span> losses</span>
        <span><span className="text-warning font-medium">{stats.breakeven}</span> BE</span>
      </div>
    </div>
  );
}
