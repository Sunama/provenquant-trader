"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { positions, strategies } from "@/lib/api";
import { StatCard } from "@/components/dashboard/StatCard";
import { formatPnl } from "@/lib/utils";
import { cn } from "@/lib/utils";
import type { Strategy } from "@/lib/types";

function StrategyOverviewRow({ strategy }: { strategy: Strategy }) {
  const { data: stats } = useQuery({
    queryKey: ["position-stats", strategy.id],
    queryFn: () => positions.stats(strategy.id),
  });

  return (
    <tr className="border-b last:border-0 hover:bg-accent/30 text-sm">
      <td className="py-2.5 px-3">
        <Link href={`/strategies/${strategy.id}`} className="flex items-center gap-2 hover:underline">
          <span className={cn("h-2 w-2 rounded-full flex-shrink-0", strategy.enabled ? "bg-green-500" : "bg-muted-foreground")} />
          <span className="font-medium">{strategy.name}</span>
          <span className={cn("text-xs rounded px-1.5 py-0.5 font-medium", strategy.is_paper ? "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400" : "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400")}>
            {strategy.is_paper ? "paper" : "live"}
          </span>
        </Link>
        <p className="text-xs text-muted-foreground font-mono ml-4">{strategy.strategy_class.split(".").pop()}</p>
      </td>
      <td className="py-2.5 px-3 text-right text-muted-foreground">{stats?.total_trades ?? "—"}</td>
      <td className="py-2.5 px-3 text-right">
        {stats ? (
          <span className={stats.win_rate >= 0.5 ? "text-green-600" : "text-red-500"}>
            {(stats.win_rate * 100).toFixed(1)}%
          </span>
        ) : "—"}
      </td>
      <td className="py-2.5 px-3 text-right font-medium">
        {stats ? (
          <span className={stats.total_pnl >= 0 ? "text-green-600" : "text-red-500"}>
            {formatPnl(stats.total_pnl)}
          </span>
        ) : "—"}
      </td>
    </tr>
  );
}

export default function DashboardPage() {
  const { data: stats } = useQuery({
    queryKey: ["position-stats"],
    queryFn: () => positions.stats(),
    refetchInterval: 30_000,
  });

  const { data: allStrategies } = useQuery({
    queryKey: ["strategies"],
    queryFn: () => strategies.list(),
    refetchInterval: 60_000,
  });

  const { data: openPositions } = useQuery({
    queryKey: ["positions-open"],
    queryFn: () => positions.list({ open_only: true }),
    refetchInterval: 15_000,
  });

  const activeStrategies = allStrategies?.filter((s) => s.enabled).length ?? 0;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Total P&L"
          value={formatPnl(stats?.total_pnl)}
          subtext={`${stats?.total_trades ?? 0} closed trades`}
          positive={(stats?.total_pnl ?? 0) > 0}
          negative={(stats?.total_pnl ?? 0) < 0}
        />
        <StatCard
          label="Win Rate"
          value={stats ? `${(stats.win_rate * 100).toFixed(1)}%` : "—"}
          subtext={`${stats?.wins ?? 0} wins`}
        />
        <StatCard
          label="Active Strategies"
          value={String(activeStrategies)}
          subtext={`${allStrategies?.length ?? 0} total`}
        />
        <StatCard
          label="Open Positions"
          value={String(openPositions?.length ?? 0)}
          subtext="across all strategies"
        />
      </div>

      {allStrategies && allStrategies.length > 0 && (
        <div className="rounded-lg border bg-card overflow-hidden">
          <div className="border-b px-4 py-3">
            <p className="text-sm font-semibold">Strategies</p>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="py-2 px-3 text-left font-medium">Strategy</th>
                <th className="py-2 px-3 text-right font-medium">Trades</th>
                <th className="py-2 px-3 text-right font-medium">Win %</th>
                <th className="py-2 px-3 text-right font-medium">P&L</th>
              </tr>
            </thead>
            <tbody>
              {allStrategies.map((s) => (
                <StrategyOverviewRow key={s.id} strategy={s} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {openPositions && openPositions.length > 0 && (
        <div className="rounded-lg border bg-card p-5">
          <p className="mb-3 text-sm font-semibold">Open Positions</p>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="pb-2 text-left font-medium">Asset</th>
                <th className="pb-2 text-left font-medium">Side</th>
                <th className="pb-2 text-left font-medium">Entry</th>
                <th className="pb-2 text-left font-medium">Size</th>
                <th className="pb-2 text-left font-medium">Strategy</th>
              </tr>
            </thead>
            <tbody>
              {openPositions.map((pos) => (
                <tr key={pos.id} className="border-b last:border-0">
                  <td className="py-2 font-semibold uppercase">{pos.symbol}</td>
                  <td className={`py-2 font-semibold ${pos.side === "long" || pos.side === "buy" ? "text-green-600" : "text-red-500"}`}>
                    {pos.side.toUpperCase()}
                  </td>
                  <td className="py-2">${pos.entry_price.toLocaleString()}</td>
                  <td className="py-2">{pos.size.toFixed(4)}</td>
                  <td className="py-2 font-mono text-xs text-muted-foreground">
                    <Link href={`/strategies/${pos.strategy_id}`} className="hover:underline">
                      {pos.strategy_id.slice(0, 8)}…
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
