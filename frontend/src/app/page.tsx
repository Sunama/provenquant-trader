"use client";

import { useQuery } from "@tanstack/react-query";
import { positions, strategies, trades } from "@/lib/api";
import { useLiveDataStore } from "@/lib/store/useLiveDataStore";
import { StatCard } from "@/components/dashboard/StatCard";
import { RecentSignalsTable } from "@/components/dashboard/RecentSignalsTable";
import { LivePriceChart } from "@/components/dashboard/LivePriceChart";
import { formatPnl } from "@/lib/utils";

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

  const { data: balance } = useQuery({
    queryKey: ["balance"],
    queryFn: () => trades.balance(),
    refetchInterval: 15_000,
  });

  const lastBalance = useLiveDataStore((s) => s.lastBalance);
  const displayBalance = lastBalance ?? balance?.balance ?? 0;

  const activeStrategies = allStrategies?.filter((s) => s.enabled).length ?? 0;

  // Show chart for first tick-processed asset of first active strategy
  const chartAsset = allStrategies
    ?.find((s) => s.enabled)
    ?.assets.find((a) => a.tick_process)
    ?? allStrategies?.find((s) => s.enabled)?.assets[0]
    ?? null;

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
          label="Paper Balance"
          value={`$${displayBalance.toLocaleString("en-US", { minimumFractionDigits: 2 })}`}
          subtext={`${openPositions?.length ?? 0} open positions`}
        />
      </div>

      {chartAsset && (
        <div className="rounded-lg border bg-card p-5">
          <p className="mb-3 text-sm font-semibold">
            {chartAsset.asset_slug.toUpperCase()} — {chartAsset.timeframe}
            <span className="ml-2 text-xs font-normal text-muted-foreground">({chartAsset.exchange})</span>
          </p>
          <LivePriceChart assetSlug={chartAsset.asset_slug} timeframe={chartAsset.timeframe} />
        </div>
      )}

      <RecentSignalsTable />

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
                  <td className="py-2 font-semibold uppercase">{pos.asset_slug}</td>
                  <td className={`py-2 font-semibold ${pos.side === "long" || pos.side === "buy" ? "text-green-600" : "text-red-500"}`}>
                    {pos.side.toUpperCase()}
                  </td>
                  <td className="py-2">${pos.entry_price.toLocaleString()}</td>
                  <td className="py-2">{pos.size.toFixed(4)}</td>
                  <td className="py-2 font-mono text-xs text-muted-foreground">{pos.strategy_id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
