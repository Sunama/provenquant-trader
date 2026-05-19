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

function formatDateShort(iso?: string | null) {
  if (!iso) return null;
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

interface Props {
  positions: Position[];
}

export function PositionHistoryTable({ positions }: Props) {
  const totalPnl = positions.reduce((sum, p) => sum + (p.pnl ?? 0), 0);
  return (
    <div className="rounded-lg border bg-card p-5">
      <p className="mb-3 text-sm font-semibold">Position History</p>
      {positions.length === 0 ? (
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
                <th className="pb-2 text-left font-medium">Open Time</th>
                <th className="pb-2 text-left font-medium">Exit</th>
                <th className="pb-2 text-left font-medium">Close Time</th>
                <th className="pb-2 text-left font-medium">Entry Reason</th>
                <th className="pb-2 text-left font-medium">Realized P&L</th>
                <th className="pb-2 text-left font-medium">Exit Reason</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((pos) => (
                <tr key={pos.id} className="border-b last:border-0">
                  <td className="py-2 uppercase font-semibold">{pos.symbol}</td>
                  <td className="py-2"><MarketTypeBadge type={pos.market_type} /></td>
                  <td className="py-2 text-xs font-medium">{pos.leverage ?? 1}×</td>
                  <td className={cn("py-2 font-semibold", pos.side === "long" ? "text-green-600" : "text-red-500")}>
                    {pos.side.toUpperCase()}
                  </td>
                  <td className="py-2">${pos.entry_price.toLocaleString()}</td>
                  <td className="py-2 text-xs text-muted-foreground whitespace-nowrap">
                    {formatDateShort(pos.entry_time) ?? <span className="opacity-40">—</span>}
                  </td>
                  <td className="py-2">{pos.exit_price != null ? `$${pos.exit_price.toLocaleString()}` : "—"}</td>
                  <td className="py-2 text-xs text-muted-foreground whitespace-nowrap">
                    {formatDateShort(pos.exit_time) ?? <span className="opacity-40">—</span>}
                  </td>
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
                <td colSpan={9} className="pt-3 text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  Total Realized P&L ({positions.length} trades)
                </td>
                <td className={cn("pt-3 font-bold", totalPnl >= 0 ? "text-green-600" : "text-red-500")}>
                  {formatPnl(totalPnl)}
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  );
}
