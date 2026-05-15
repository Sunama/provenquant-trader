import { cn } from "@/lib/utils";
import { formatPnl } from "@/lib/utils";
import type { PositionStats } from "@/lib/types";

interface Props {
  stats: PositionStats | null | undefined;
  assetsCount: number;
}

export function StatsCards({ stats, assetsCount }: Props) {
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <div className="rounded-lg border bg-card p-4">
        <p className="text-xs text-muted-foreground">Total P&L</p>
        <p className={cn("text-xl font-bold mt-1", (stats?.total_pnl ?? 0) >= 0 ? "text-green-600" : "text-red-500")}>
          {formatPnl(stats?.total_pnl)}
        </p>
      </div>
      <div className="rounded-lg border bg-card p-4">
        <p className="text-xs text-muted-foreground">Win Rate</p>
        <p className="text-xl font-bold mt-1">
          {stats ? `${(stats.win_rate * 100).toFixed(1)}%` : "—"}
        </p>
      </div>
      <div className="rounded-lg border bg-card p-4">
        <p className="text-xs text-muted-foreground">Total Trades</p>
        <p className="text-xl font-bold mt-1">{stats?.total_trades ?? 0}</p>
      </div>
      <div className="rounded-lg border bg-card p-4">
        <p className="text-xs text-muted-foreground">Assets</p>
        <p className="text-xl font-bold mt-1">{assetsCount}</p>
      </div>
    </div>
  );
}
