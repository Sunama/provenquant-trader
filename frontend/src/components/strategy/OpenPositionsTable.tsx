"use client";

import { useState } from "react";
import { cn, formatPnl, formatPct } from "@/lib/utils";
import type { Position } from "@/lib/types";

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

function formatDateShort(iso?: string) {
  if (!iso) return null;
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

interface Props {
  positions: Position[];
  getLivePrice: (symbol: string) => number | null;
  onClose?: (posId: number, price: number) => Promise<void>;
}

export function OpenPositionsTable({ positions, getLivePrice, onClose }: Props) {
  const [closing, setClosing] = useState<number | null>(null);

  if (positions.length === 0) return null;

  async function handleClose(pos: Position) {
    if (!onClose) return;
    const price = getLivePrice(pos.symbol) ?? pos.entry_price;
    setClosing(pos.id);
    try {
      await onClose(pos.id, price);
    } finally {
      setClosing(null);
    }
  }

  return (
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
              <th className="pb-2 text-left font-medium">Open Time</th>
              <th className="pb-2 text-left font-medium">Entry Price</th>
              <th className="pb-2 text-left font-medium">Size</th>
              <th className="pb-2 text-left font-medium">TP</th>
              <th className="pb-2 text-left font-medium">SL</th>
              <th className="pb-2 text-left font-medium">Timeout</th>
              <th className="pb-2 text-left font-medium">Entry Reason</th>
              <th className="pb-2 text-left font-medium">Unrealized P&L</th>
              {onClose && <th className="pb-2 text-left font-medium">Actions</th>}
            </tr>
          </thead>
          <tbody>
            {positions.map((pos) => {
              const currentPrice = getLivePrice(pos.symbol);
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
              const timeoutLabel = pos.timeout ? formatDateShort(pos.timeout) : null;
              const isExpired = pos.timeout ? new Date(pos.timeout) <= new Date() : false;

              return (
                <tr key={pos.id} className="border-b last:border-0">
                  <td className="py-2 uppercase font-semibold">{pos.symbol}</td>
                  <td className="py-2"><MarketTypeBadge type={pos.market_type} /></td>
                  <td className="py-2 text-xs font-medium">{pos.leverage ?? 1}×</td>
                  <td className={cn("py-2 font-semibold", isLong ? "text-green-600" : "text-red-500")}>
                    {pos.side.toUpperCase()}
                  </td>
                  <td className="py-2 text-xs text-muted-foreground whitespace-nowrap">
                    {formatDateShort(pos.entry_time) ?? <span className="opacity-40">—</span>}
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
                  <td className="py-2 text-xs whitespace-nowrap">
                    {timeoutLabel ? (
                      <span className={cn("font-medium", isExpired ? "text-red-500" : "text-muted-foreground")}>
                        {timeoutLabel}
                        {isExpired && <span className="ml-1 text-red-500">(expired)</span>}
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
                  {onClose && (
                    <td className="py-2">
                      <button
                        onClick={() => handleClose(pos)}
                        disabled={closing === pos.id}
                        className="text-xs px-2 py-1 rounded border border-red-300 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      >
                        {closing === pos.id ? "Closing…" : "Close"}
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
