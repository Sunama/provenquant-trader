"use client";

import { use } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { strategies, positions, tradeHistory, trades } from "@/lib/api";
import { StrategyAssetChart } from "@/components/charts/StrategyAssetChart";
import { useLiveDataStore } from "@/lib/store/useLiveDataStore";
import { useShallow } from "zustand/react/shallow";
import type { TickPayload } from "@/lib/types";
import { Breadcrumb } from "@/components/shared/Breadcrumb";
import { cn } from "@/lib/utils";
import { StatsCards } from "@/components/strategy/StatsCards";
import { PaperBalances } from "@/components/strategy/PaperBalances";
import { LiveExecutionsPanel } from "@/components/strategy/LiveExecutionsPanel";
import { RecentSignalsPanel } from "@/components/strategy/RecentSignalsPanel";
import { OpenPositionsTable } from "@/components/strategy/OpenPositionsTable";
import { PositionHistoryTable } from "@/components/strategy/PositionHistoryTable";
import { TradeHistoryTable } from "@/components/strategy/TradeHistoryTable";

function getPriceForSymbol(
  symbol: string,
  stores: Record<string, TickPayload>[],
): number | null {
  const lower = symbol.toLowerCase();
  for (const store of stores) {
    for (const [key, tick] of Object.entries(store)) {
      if (key.split(":")[0].toLowerCase() === lower) {
        return tick.close;
      }
    }
  }
  return null;
}

export default function StrategyDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  const { data: strategy } = useQuery({
    queryKey: ["strategy", id],
    queryFn: () => strategies.get(id),
  });

  const { data: positionStats } = useQuery({
    queryKey: ["position-stats", id],
    queryFn: () => positions.stats(id),
  });

  const { data: positionList } = useQuery({
    queryKey: ["positions", id],
    queryFn: () => positions.list({ strategy_id: id, limit: 200 }),
  });

  const { data: tradeHistoryList } = useQuery({
    queryKey: ["trade-history", id],
    queryFn: () => tradeHistory.list({ strategy_id: id, limit: 30 }),
    refetchInterval: 15_000,
  });

  const { data: balancesData } = useQuery({
    queryKey: ["balances", id],
    queryFn: () => trades.balances(id),
    refetchInterval: 10_000,
    enabled: !!strategy?.is_paper,
  });

  const recentSignals = useLiveDataStore(
    useShallow((s) =>
      s.recentSignals.filter((sig) => sig.config_id === id || sig.strategy_id === strategy?.id)
    )
  );

  const recentExecutions = useLiveDataStore(
    useShallow((s) =>
      s.recentExecutions.filter((e) => e.strategy_id === id || e.strategy_id === strategy?.id)
    )
  );

  const { livePrices, latestTicks } = useLiveDataStore(
    useShallow((s) => ({ livePrices: s.livePrices, latestTicks: s.latestTicks }))
  );

  const openPositions = (positionList ?? []).filter((p) => p.is_open);
  const closedPositions = (positionList ?? []).filter((p) => !p.is_open);

  if (!strategy) return <p className="text-muted-foreground">Loading…</p>;

  return (
    <div className="space-y-6">
      <Breadcrumb items={[
        { label: "Strategies", href: "/strategies" },
        { label: strategy.name },
      ]} />
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span
              className={cn("h-2 w-2 rounded-full", strategy.enabled ? "bg-green-500" : "bg-muted-foreground")}
            />
            <h1 className="text-2xl font-bold">{strategy.name}</h1>
            <span className={cn("text-xs rounded px-1.5 py-0.5 font-medium", strategy.is_paper ? "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400" : "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400")}>
              {strategy.is_paper ? "paper" : "live"}
            </span>
          </div>
          <p className="text-sm text-muted-foreground font-mono">{strategy.strategy_class}</p>
        </div>
        <Link
          href={`/strategies/${id}/edit`}
          className="flex items-center gap-2 rounded-md border px-4 py-2 text-sm font-medium hover:bg-accent"
        >
          <Pencil className="h-4 w-4" />
          Edit
        </Link>
      </div>

      <StatsCards stats={positionStats} assetsCount={strategy.assets.length} />

      {strategy.is_paper && balancesData && (
        <PaperBalances balances={balancesData.balances as Record<string, number>} />
      )}

      {strategy.assets.map((asset) => (
        <div key={asset.leg_num} className="rounded-lg border bg-card p-5">
          <div className="flex flex-wrap items-center gap-2 mb-4">
            <p className="text-sm font-semibold uppercase">{asset.symbol}</p>
            <span className="text-xs text-muted-foreground">
              {asset.exchange} • {asset.timeframe} • {asset.market_type}
            </span>
            {asset.role !== "primary" && (
              <span className="text-xs rounded-full bg-secondary text-secondary-foreground px-2 py-0.5">{asset.role}</span>
            )}
          </div>
          <StrategyAssetChart
            strategyId={id}
            asset={asset}
            positions={positionList ?? []}
          />
        </div>
      ))}

      <LiveExecutionsPanel executions={recentExecutions} />
      <RecentSignalsPanel signals={recentSignals} />
      <TradeHistoryTable trades={tradeHistoryList ?? []} />
      <OpenPositionsTable
        positions={openPositions}
        getLivePrice={(sym) => getPriceForSymbol(sym, [livePrices, latestTicks])}
      />
      <PositionHistoryTable positions={closedPositions} />
    </div>
  );
}
