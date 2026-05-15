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
import { formatPnl, formatPct } from "@/lib/utils";
import { cn } from "@/lib/utils";

const MARKET_TYPE_COLORS: Record<string, string> = {
  spot:    "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
  futures: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  options: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
};

function MarketTypeBadge({ type }: { type?: string }) {
  if (!type) return <span className="opacity-40">—</span>;
  return (
    <span className={cn("text-xs rounded-full px-2 py-0.5 font-medium", MARKET_TYPE_COLORS[type] ?? "bg-muted text-muted-foreground")}>
      {type}
    </span>
  );
}

const TRADE_TYPE_COLORS: Record<string, string> = {
  open_long: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
  close_long: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
  open_short: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  close_short: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
  deposit: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  withdraw: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400",
  transfer: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
};

function TradeTypeBadge({ type }: { type: string }) {
  return (
    <span className={cn("text-xs rounded-full px-2 py-0.5 font-medium whitespace-nowrap", TRADE_TYPE_COLORS[type] ?? "bg-muted text-muted-foreground")}>
      {type.replace(/_/g, " ")}
    </span>
  );
}

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
  const totalRealizedPnl = closedPositions.reduce((sum, p) => sum + (p.pnl ?? 0), 0);

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

      {strategy.is_paper && balancesData && Object.keys(balancesData.balances).length > 0 && (
        <div className="rounded-lg border bg-card p-4">
          <p className="text-xs font-semibold text-muted-foreground mb-3 uppercase tracking-wide">Paper Balances</p>
          <div className="flex flex-wrap gap-4">
            {Object.entries(balancesData.balances).map(([asset, qty]) => (
              <div key={asset} className="flex flex-col">
                <span className="text-xs text-muted-foreground">{asset}</span>
                <span className="text-base font-mono font-semibold">
                  {(qty as number).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 })}
                </span>
              </div>
            ))}
          </div>
        </div>
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

      {recentExecutions.length > 0 && (
        <div className="rounded-lg border bg-card p-5">
          <p className="mb-3 text-sm font-semibold">Live Executions</p>
          <div className="space-y-2">
            {recentExecutions.slice(0, 10).map((exec, i) => {
              const price = parseFloat(exec.price);
              const size = parseFloat(exec.size);
              const pnl = exec.pnl ? parseFloat(exec.pnl) : null;
              const pnlPct = exec.pnl_pct ? parseFloat(exec.pnl_pct) : null;
              return (
                <div key={i} className="flex items-center gap-3 text-sm flex-wrap">
                  <span className={cn("text-xs font-bold uppercase rounded px-1.5 py-0.5", exec.action === "open" ? "bg-green-100 text-green-700" : "bg-orange-100 text-orange-700")}>
                    {exec.action}
                  </span>
                  <span className="font-semibold uppercase">{exec.symbol}</span>
                  <span className={cn("font-medium", exec.side === "long" || exec.side === "buy" ? "text-green-600" : "text-red-500")}>
                    {exec.side.toUpperCase()}
                  </span>
                  {!isNaN(price) && price > 0 && (
                    <span>${price.toLocaleString()}</span>
                  )}
                  {!isNaN(size) && size > 0 && (
                    <span className="text-muted-foreground">×{size}</span>
                  )}
                  {pnl !== null && !isNaN(pnl) && (
                    <span className={cn("font-medium", pnl >= 0 ? "text-green-600" : "text-red-500")}>
                      {formatPnl(pnl)}
                      {pnlPct !== null && !isNaN(pnlPct) && (
                        <span className="ml-1 text-xs">({formatPct(pnlPct)})</span>
                      )}
                    </span>
                  )}
                  {exec.reason && (
                    <span className="text-xs text-muted-foreground">{exec.reason}</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {recentSignals.length > 0 && (
        <div className="rounded-lg border bg-card p-5">
          <p className="mb-1 text-sm font-semibold">Recent Signals</p>
          <p className="mb-3 text-xs text-muted-foreground">Actions requested by the strategy (pre-execution)</p>
          <div className="space-y-2">
            {recentSignals.slice(0, 10).map((sig, i) => {
              const execute = sig.execute ?? "";
              const price = parseFloat(sig.price);
              const amount = parseFloat(sig.amount);
              const ts = parseFloat(sig.ts);
              const isLong = execute.includes("long") || execute === "buy";
              return (
                <div key={i} className="flex items-center gap-3 text-sm flex-wrap">
                  <span className={cn("text-xs font-bold uppercase rounded px-1.5 py-0.5", isLong ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700")}>
                    {execute.replace(/_/g, " ")}
                  </span>
                  <span className="text-xs text-muted-foreground uppercase">{sig.market_type}</span>
                  {!isNaN(price) && price > 0 && (
                    <span>${price.toLocaleString()}</span>
                  )}
                  {!isNaN(amount) && (
                    <span className="text-muted-foreground">{(amount * 100).toFixed(0)}%</span>
                  )}
                  {!isNaN(ts) && (
                    <span className="text-xs text-muted-foreground">{new Date(ts * 1000).toLocaleTimeString()}</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="rounded-lg border bg-card p-5">
        <p className="mb-3 text-sm font-semibold">Trade History</p>
        {!tradeHistoryList || tradeHistoryList.length === 0 ? (
          <p className="text-sm text-muted-foreground">No trades recorded yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="pb-2 text-left font-medium">Time</th>
                  <th className="pb-2 text-left font-medium">Type</th>
                  <th className="pb-2 text-left font-medium">Symbol</th>
                  <th className="pb-2 text-left font-medium">Market</th>
                  <th className="pb-2 text-left font-medium">Leverage</th>
                  <th className="pb-2 text-left font-medium">Price</th>
                  <th className="pb-2 text-left font-medium">Bought</th>
                  <th className="pb-2 text-left font-medium">Sold</th>
                  <th className="pb-2 text-left font-medium">Fee</th>
                  <th className="pb-2 text-left font-medium">Reason</th>
                </tr>
              </thead>
              <tbody>
                {tradeHistoryList.map((th) => (
                  <tr key={th.id} className="border-b last:border-0">
                    <td className="py-2 text-xs text-muted-foreground whitespace-nowrap">
                      {new Date(th.occurred_at).toLocaleString()}
                    </td>
                    <td className="py-2">
                      <TradeTypeBadge type={th.trade_type} />
                    </td>
                    <td className="py-2 font-semibold uppercase">{th.symbol}</td>
                    <td className="py-2"><MarketTypeBadge type={th.market_type} /></td>
                    <td className="py-2 text-xs font-medium">
                      {(th.leverage ?? 1) > 1 ? `${th.leverage}×` : <span className="opacity-40">—</span>}
                    </td>
                    <td className="py-2">${th.exchange_rate.toLocaleString()}</td>
                    <td className="py-2 text-green-600 font-medium">
                      {th.bought_qty.toLocaleString(undefined, { maximumFractionDigits: 6 })}{" "}
                      <span className="text-xs text-muted-foreground">{th.bought_asset}</span>
                    </td>
                    <td className="py-2 text-red-500 font-medium">
                      {th.sold_qty.toLocaleString(undefined, { maximumFractionDigits: 6 })}{" "}
                      <span className="text-xs text-muted-foreground">{th.sold_asset}</span>
                    </td>
                    <td className="py-2 text-xs text-muted-foreground whitespace-nowrap">
                      {th.fee > 0 ? `${th.fee} ${th.fee_asset}` : "—"}
                    </td>
                    <td className="py-2 text-xs text-muted-foreground max-w-[240px]">
                      {th.reason ?? <span className="opacity-40">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {openPositions.length > 0 && (
        <div className="rounded-lg border bg-card p-5">
          <p className="mb-3 text-sm font-semibold">Open Positions</p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="pb-2 text-left font-medium">Asset</th>
                  <th className="pb-2 text-left font-medium">Market</th>
                  <th className="pb-2 text-left font-medium">Leverage</th>
                  <th className="pb-2 text-left font-medium">Side</th>
                  <th className="pb-2 text-left font-medium">Entry Price</th>
                  <th className="pb-2 text-left font-medium">Size</th>
                  <th className="pb-2 text-left font-medium">TP</th>
                  <th className="pb-2 text-left font-medium">SL</th>
                  <th className="pb-2 text-left font-medium">Entry Reason</th>
                  <th className="pb-2 text-left font-medium">Unrealized P&L</th>
                </tr>
              </thead>
              <tbody>
                {openPositions.map((pos) => {
                  const currentPrice = getPriceForSymbol(pos.symbol, [livePrices, latestTicks]);
                  const isLong = pos.side === "long";
                  const unrealizedPnl =
                    currentPrice != null
                      ? isLong
                        ? (currentPrice - pos.entry_price) * pos.size
                        : (pos.entry_price - currentPrice) * pos.size
                      : null;
                  const unrealizedPnlPct =
                    unrealizedPnl != null && pos.entry_price > 0 && pos.size > 0
                      ? unrealizedPnl / (pos.entry_price * pos.size)
                      : null;
                  return (
                    <tr key={pos.id} className="border-b last:border-0">
                      <td className="py-2 uppercase font-semibold">{pos.symbol}</td>
                      <td className="py-2"><MarketTypeBadge type={pos.market_type} /></td>
                      <td className="py-2 text-xs font-medium">
                        {(pos.leverage ?? 1) > 1 ? `${pos.leverage}×` : <span className="opacity-40">—</span>}
                      </td>
                      <td className={cn("py-2 font-semibold", isLong ? "text-green-600" : "text-red-500")}>
                        {pos.side.toUpperCase()}
                      </td>
                      <td className="py-2">${pos.entry_price.toLocaleString()}</td>
                      <td className="py-2 text-muted-foreground">{pos.size}</td>
                      <td className="py-2 text-xs">
                        {pos.tp_price != null ? (
                          <span className="text-green-600 font-medium">
                            ${pos.tp_price.toLocaleString()}
                            <span className="ml-1 text-muted-foreground">
                              ({isLong
                                ? `+${(((pos.tp_price - pos.entry_price) / pos.entry_price) * 100).toFixed(2)}%`
                                : `+${(((pos.entry_price - pos.tp_price) / pos.entry_price) * 100).toFixed(2)}%`})
                            </span>
                          </span>
                        ) : (
                          <span className="opacity-40">—</span>
                        )}
                      </td>
                      <td className="py-2 text-xs">
                        {pos.sl_price != null ? (
                          <span className="text-red-500 font-medium">
                            ${pos.sl_price.toLocaleString()}
                            <span className="ml-1 text-muted-foreground">
                              ({isLong
                                ? `-${(((pos.entry_price - pos.sl_price) / pos.entry_price) * 100).toFixed(2)}%`
                                : `-${(((pos.sl_price - pos.entry_price) / pos.entry_price) * 100).toFixed(2)}%`})
                            </span>
                          </span>
                        ) : (
                          <span className="opacity-40">—</span>
                        )}
                      </td>
                      <td className="py-2 text-xs text-muted-foreground max-w-[220px]">
                        {pos.entry_reason ?? <span className="opacity-40">—</span>}
                      </td>
                      <td className="py-2">
                        {unrealizedPnl != null ? (
                          <span className={cn("font-medium", unrealizedPnl >= 0 ? "text-green-600" : "text-red-500")}>
                            {formatPnl(unrealizedPnl)}
                            {unrealizedPnlPct != null && (
                              <span className="ml-1 text-xs">({formatPct(unrealizedPnlPct)})</span>
                            )}
                            <span className="ml-2 text-xs text-muted-foreground">
                              @ ${currentPrice!.toLocaleString()}
                            </span>
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">Waiting for price…</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="rounded-lg border bg-card p-5">
        <p className="mb-3 text-sm font-semibold">Position History</p>
        {closedPositions.length === 0 ? (
          <p className="text-sm text-muted-foreground">No closed positions yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="pb-2 text-left font-medium">Asset</th>
                  <th className="pb-2 text-left font-medium">Market</th>
                  <th className="pb-2 text-left font-medium">Leverage</th>
                  <th className="pb-2 text-left font-medium">Side</th>
                  <th className="pb-2 text-left font-medium">Entry</th>
                  <th className="pb-2 text-left font-medium">Exit</th>
                  <th className="pb-2 text-left font-medium">Entry Reason</th>
                  <th className="pb-2 text-left font-medium">Realized P&L</th>
                  <th className="pb-2 text-left font-medium">Exit Reason</th>
                </tr>
              </thead>
              <tbody>
                {closedPositions.map((pos) => (
                  <tr key={pos.id} className="border-b last:border-0">
                    <td className="py-2 uppercase font-semibold">{pos.symbol}</td>
                    <td className="py-2"><MarketTypeBadge type={pos.market_type} /></td>
                    <td className="py-2 text-xs font-medium">
                      {(pos.leverage ?? 1) > 1 ? `${pos.leverage}×` : <span className="opacity-40">—</span>}
                    </td>
                    <td className={cn("py-2 font-semibold", pos.side === "long" ? "text-green-600" : "text-red-500")}>
                      {pos.side.toUpperCase()}
                    </td>
                    <td className="py-2">${pos.entry_price.toLocaleString()}</td>
                    <td className="py-2">{pos.exit_price != null ? `$${pos.exit_price.toLocaleString()}` : "—"}</td>
                    <td className="py-2 text-xs text-muted-foreground max-w-[200px]">
                      {pos.entry_reason ?? <span className="opacity-40">—</span>}
                    </td>
                    <td className={cn("py-2 font-medium", (pos.pnl ?? 0) >= 0 ? "text-green-600" : "text-red-500")}>
                      {formatPnl(pos.pnl)}
                      {pos.pnl_pct != null && (
                        <span className="ml-1 text-xs">({formatPct(pos.pnl_pct)})</span>
                      )}
                    </td>
                    <td className="py-2 text-xs text-muted-foreground max-w-[200px]">
                      {pos.exit_reason ?? <span className="opacity-40">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t">
                  <td colSpan={7} className="pt-3 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                    Total Realized P&L ({closedPositions.length} trades)
                  </td>
                  <td className={cn("pt-3 font-bold", totalRealizedPnl >= 0 ? "text-green-600" : "text-red-500")}>
                    {formatPnl(totalRealizedPnl)}
                  </td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
