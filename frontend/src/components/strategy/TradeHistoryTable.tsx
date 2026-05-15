import { cn } from "@/lib/utils";
import type { TradeHistory } from "@/lib/types";

const MARKET_TYPE_COLORS: Record<string, string> = {
  spot:    "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
  futures: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  options: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
};

const TRADE_TYPE_COLORS: Record<string, string> = {
  open_long:   "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
  close_long:  "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
  open_short:  "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  close_short: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
  deposit:     "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
  withdraw:    "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400",
  transfer:    "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
};

function MarketTypeBadge({ type }: { type?: string }) {
  if (!type) return <span className="opacity-40">—</span>;
  return (
    <span className={cn("text-xs rounded-full px-2 py-0.5 font-medium", MARKET_TYPE_COLORS[type] ?? "bg-muted text-muted-foreground")}>
      {type}
    </span>
  );
}

function TradeTypeBadge({ type }: { type: string }) {
  return (
    <span className={cn("text-xs rounded-full px-2 py-0.5 font-medium whitespace-nowrap", TRADE_TYPE_COLORS[type] ?? "bg-muted text-muted-foreground")}>
      {type.replace(/_/g, " ")}
    </span>
  );
}

interface Props {
  trades: TradeHistory[];
}

export function TradeHistoryTable({ trades }: Props) {
  return (
    <div className="rounded-lg border bg-card p-5">
      <p className="mb-3 text-sm font-semibold">Trade History</p>
      {trades.length === 0 ? (
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
              {trades.map((th) => (
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
  );
}
