"use client";

import { use } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { strategies, positions } from "@/lib/api";
import { StrategyAssetChart } from "@/components/charts/StrategyAssetChart";
import { useLiveDataStore } from "@/lib/store/useLiveDataStore";
import { useShallow } from "zustand/react/shallow";
import { formatPnl, formatPct } from "@/lib/utils";
import { cn } from "@/lib/utils";

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

  const recentSignals = useLiveDataStore(
    useShallow((s) =>
      s.recentSignals.filter((sig) => sig.config_id === id || sig.strategy_id === strategy?.id)
    )
  );

  if (!strategy) return <p className="text-muted-foreground">Loading…</p>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span
              className={cn("h-2 w-2 rounded-full", strategy.enabled ? "bg-green-500" : "bg-muted-foreground")}
            />
            <h1 className="text-2xl font-bold">{strategy.id}</h1>
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

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <div className="rounded-lg border bg-card p-4">
          <p className="text-xs text-muted-foreground">Total P&L</p>
          <p className={cn("text-xl font-bold mt-1", (positionStats?.total_pnl ?? 0) >= 0 ? "text-green-600" : "text-red-500")}>
            {formatPnl(positionStats?.total_pnl)}
          </p>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <p className="text-xs text-muted-foreground">Win Rate</p>
          <p className="text-xl font-bold mt-1">
            {positionStats ? `${(positionStats.win_rate * 100).toFixed(1)}%` : "—"}
          </p>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <p className="text-xs text-muted-foreground">Total Trades</p>
          <p className="text-xl font-bold mt-1">{positionStats?.total_trades ?? 0}</p>
        </div>
        <div className="rounded-lg border bg-card p-4">
          <p className="text-xs text-muted-foreground">Assets</p>
          <p className="text-xl font-bold mt-1">{strategy.assets.length}</p>
        </div>
      </div>

      {strategy.assets.map((asset) => (
        <div key={asset.asset_num} className="rounded-lg border bg-card p-5">
          <div className="flex flex-wrap items-center gap-2 mb-4">
            <p className="text-sm font-semibold uppercase">{asset.symbol}</p>
            <span className="text-xs text-muted-foreground">
              {asset.exchange} • {asset.timeframe} • {asset.market_type}
            </span>
            {asset.tick_process && (
              <span className="text-xs rounded-full bg-primary/10 text-primary px-2 py-0.5">trigger</span>
            )}
            {asset.description && (
              <span className="text-xs text-muted-foreground">— {asset.description}</span>
            )}
          </div>
          <StrategyAssetChart
            strategyId={id}
            asset={asset}
            positions={positionList ?? []}
          />
        </div>
      ))}

      {recentSignals.length > 0 && (
        <div className="rounded-lg border bg-card p-5">
          <p className="mb-3 text-sm font-semibold">Live Signal Feed</p>
          <div className="space-y-2">
            {recentSignals.slice(0, 10).map((sig, i) => (
              <div key={i} className="flex items-center gap-3 text-sm">
                <span className={cn("font-bold uppercase", sig.execute === "long" || sig.execute === "buy" ? "text-green-600" : "text-red-500")}>
                  {sig.execute}
                </span>
                <span>${parseFloat(sig.price).toLocaleString()}</span>
                <span className="text-muted-foreground">{(parseFloat(sig.amount) * 100).toFixed(0)}%</span>
                <span className="text-xs text-muted-foreground">{new Date(parseFloat(sig.ts) * 1000).toLocaleTimeString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-lg border bg-card p-5">
        <p className="mb-3 text-sm font-semibold">Positions</p>
        {!positionList || positionList.length === 0 ? (
          <p className="text-sm text-muted-foreground">No positions yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="pb-2 text-left font-medium">Asset</th>
                <th className="pb-2 text-left font-medium">Side</th>
                <th className="pb-2 text-left font-medium">Entry</th>
                <th className="pb-2 text-left font-medium">Exit</th>
                <th className="pb-2 text-left font-medium">P&L</th>
                <th className="pb-2 text-left font-medium">Reason</th>
                <th className="pb-2 text-left font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {positionList.map((pos) => (
                <tr key={pos.id} className="border-b last:border-0">
                  <td className="py-2 uppercase font-semibold">{pos.symbol}</td>
                  <td className={cn("py-2 font-semibold", pos.side === "long" || pos.side === "buy" ? "text-green-600" : "text-red-500")}>
                    {pos.side.toUpperCase()}
                  </td>
                  <td className="py-2">${pos.entry_price.toLocaleString()}</td>
                  <td className="py-2">{pos.exit_price ? `$${pos.exit_price.toLocaleString()}` : "—"}</td>
                  <td className={cn("py-2 font-medium", (pos.pnl ?? 0) >= 0 ? "text-green-600" : "text-red-500")}>
                    {formatPnl(pos.pnl)}
                    {pos.pnl_pct !== undefined && pos.pnl_pct !== null && (
                      <span className="ml-1 text-xs">({formatPct(pos.pnl_pct)})</span>
                    )}
                  </td>
                  <td className="py-2 text-muted-foreground text-xs">{pos.exit_reason ?? "—"}</td>
                  <td className="py-2">
                    <span className={cn("text-xs rounded-full px-2 py-0.5", pos.is_open ? "bg-green-100 text-green-700" : "bg-muted text-muted-foreground")}>
                      {pos.is_open ? "OPEN" : "CLOSED"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
