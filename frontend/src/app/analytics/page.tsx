"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { positions, strategies } from "@/lib/api";
import type { Position, Strategy } from "@/lib/types";
import { cn, formatPnl, formatPct, formatPrice } from "@/lib/utils";

function StatBlock({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border bg-card p-5">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-bold">{value}</p>
      {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
    </div>
  );
}

function StrategyRow({ strategy, selected, onSelect }: { strategy: Strategy; selected: boolean; onSelect: () => void }) {
  const { data: stats } = useQuery({
    queryKey: ["position-stats", strategy.id],
    queryFn: () => positions.stats(strategy.id),
  });

  return (
    <tr
      className={cn("cursor-pointer border-b transition-colors last:border-0 hover:bg-accent/50", selected && "bg-accent")}
      onClick={onSelect}
    >
      <td className="py-2.5 px-3">
        <div className="flex items-center gap-2">
          <span className={cn("h-2 w-2 rounded-full flex-shrink-0", strategy.enabled ? "bg-green-500" : "bg-muted-foreground")} />
          <span className="font-medium text-sm">{strategy.id}</span>
        </div>
        <p className="text-xs text-muted-foreground font-mono ml-4">{strategy.strategy_class.split(".").pop()}</p>
      </td>
      <td className="py-2.5 px-3 text-sm text-right">{stats?.total_trades ?? "—"}</td>
      <td className="py-2.5 px-3 text-sm text-right">
        {stats ? (
          <span className={stats.win_rate >= 0.5 ? "text-green-600" : "text-red-600"}>
            {formatPct(stats.win_rate)}
          </span>
        ) : "—"}
      </td>
      <td className="py-2.5 px-3 text-sm text-right font-medium">
        {stats ? (
          <span className={stats.total_pnl >= 0 ? "text-green-600" : "text-red-600"}>
            {formatPnl(stats.total_pnl)}
          </span>
        ) : "—"}
      </td>
    </tr>
  );
}

function PositionRow({ pos }: { pos: Position }) {
  const open = pos.is_open;
  const duration = pos.exit_time && pos.entry_time
    ? Math.round((new Date(pos.exit_time).getTime() - new Date(pos.entry_time).getTime()) / 60000)
    : null;

  return (
    <tr className="border-b text-sm last:border-0 hover:bg-accent/30">
      <td className="py-2 px-3 font-mono text-xs text-muted-foreground">{pos.id}</td>
      <td className="py-2 px-3 font-medium">{pos.asset_slug.toUpperCase()}</td>
      <td className="py-2 px-3">
        <span className={cn(
          "rounded-full px-2 py-0.5 text-xs font-medium",
          pos.side === "long" ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" :
          "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
        )}>
          {pos.side.toUpperCase()}
        </span>
      </td>
      <td className="py-2 px-3 text-right">{formatPrice(pos.entry_price)}</td>
      <td className="py-2 px-3 text-right">{pos.exit_price ? formatPrice(pos.exit_price) : "—"}</td>
      <td className="py-2 px-3 text-right">
        {open ? (
          <span className="text-xs text-muted-foreground">Open</span>
        ) : pos.pnl !== undefined ? (
          <span className={pos.pnl >= 0 ? "text-green-600 font-medium" : "text-red-600 font-medium"}>
            {formatPnl(pos.pnl)}
          </span>
        ) : "—"}
      </td>
      <td className="py-2 px-3 text-right text-muted-foreground">
        {duration !== null ? `${duration}m` : "—"}
      </td>
      <td className="py-2 px-3 text-right text-xs text-muted-foreground">
        {pos.exit_reason ?? (open ? "open" : "—")}
      </td>
    </tr>
  );
}

export default function AnalyticsPage() {
  const [selectedStrategy, setSelectedStrategy] = useState<string | null>(null);

  const { data: strategiesList } = useQuery({
    queryKey: ["strategies"],
    queryFn: () => strategies.list(),
  });

  const { data: globalStats } = useQuery({
    queryKey: ["position-stats"],
    queryFn: () => positions.stats(),
  });

  const { data: closedPositions, isLoading: posLoading } = useQuery({
    queryKey: ["positions", selectedStrategy],
    queryFn: () => positions.list({ open_only: false, strategy_id: selectedStrategy ?? undefined, limit: 100 }),
  });

  const { data: openPositions } = useQuery({
    queryKey: ["positions-open"],
    queryFn: () => positions.list({ open_only: true, limit: 50 }),
    refetchInterval: 5000,
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Analytics</h1>

      {/* Global stats */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatBlock
          label="Total PnL"
          value={globalStats ? formatPnl(globalStats.total_pnl) : "—"}
          sub={globalStats ? `${globalStats.wins} wins` : undefined}
        />
        <StatBlock
          label="Win Rate"
          value={globalStats ? formatPct(globalStats.win_rate) : "—"}
          sub={globalStats ? `${globalStats.total_trades} trades` : undefined}
        />
        <StatBlock
          label="Open Positions"
          value={String(openPositions?.length ?? "—")}
        />
        <StatBlock
          label="Strategies"
          value={String(strategiesList?.length ?? "—")}
          sub={`${strategiesList?.filter((s) => s.enabled).length ?? 0} active`}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
        {/* Per-strategy sidebar */}
        <section className="rounded-lg border bg-card overflow-hidden">
          <div className="border-b px-3 py-3">
            <h2 className="text-sm font-semibold">Per-Strategy Performance</h2>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="py-2 px-3 text-left font-medium">Strategy</th>
                <th className="py-2 px-3 text-right font-medium">Trades</th>
                <th className="py-2 px-3 text-right font-medium">Win%</th>
                <th className="py-2 px-3 text-right font-medium">PnL</th>
              </tr>
            </thead>
            <tbody>
              {strategiesList?.map((s) => (
                <StrategyRow
                  key={s.id}
                  strategy={s}
                  selected={selectedStrategy === s.id}
                  onSelect={() => setSelectedStrategy(selectedStrategy === s.id ? null : s.id)}
                />
              ))}
              {(!strategiesList || strategiesList.length === 0) && (
                <tr>
                  <td colSpan={4} className="py-4 text-center text-xs text-muted-foreground">No strategies</td>
                </tr>
              )}
            </tbody>
          </table>
          {selectedStrategy && (
            <div className="border-t px-3 py-2">
              <button
                onClick={() => setSelectedStrategy(null)}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                ✕ Clear filter
              </button>
            </div>
          )}
        </section>

        {/* Position history */}
        <section className="rounded-lg border bg-card overflow-hidden">
          <div className="border-b px-4 py-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">
              Trade History
              {selectedStrategy && <span className="ml-1 text-muted-foreground">— {selectedStrategy}</span>}
            </h2>
            <span className="text-xs text-muted-foreground">Last 100 trades</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="py-2 px-3 text-left font-medium">#</th>
                  <th className="py-2 px-3 text-left font-medium">Asset</th>
                  <th className="py-2 px-3 text-left font-medium">Side</th>
                  <th className="py-2 px-3 text-right font-medium">Entry</th>
                  <th className="py-2 px-3 text-right font-medium">Exit</th>
                  <th className="py-2 px-3 text-right font-medium">PnL</th>
                  <th className="py-2 px-3 text-right font-medium">Duration</th>
                  <th className="py-2 px-3 text-right font-medium">Reason</th>
                </tr>
              </thead>
              <tbody>
                {posLoading && (
                  <tr>
                    <td colSpan={8} className="py-8 text-center text-xs text-muted-foreground">Loading…</td>
                  </tr>
                )}
                {!posLoading && (!closedPositions || closedPositions.length === 0) && (
                  <tr>
                    <td colSpan={8} className="py-8 text-center text-xs text-muted-foreground">
                      No trades recorded yet.
                    </td>
                  </tr>
                )}
                {closedPositions?.map((pos) => (
                  <PositionRow key={pos.id} pos={pos} />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
