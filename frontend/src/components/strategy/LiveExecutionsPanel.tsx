import { cn, formatPnl, formatPct } from "@/lib/utils";
import type { ExecutionPayload } from "@/lib/types";

interface Props {
  executions: ExecutionPayload[];
}

export function LiveExecutionsPanel({ executions }: Props) {
  if (executions.length === 0) return null;
  return (
    <div className="rounded-lg border bg-card p-5">
      <p className="mb-3 text-sm font-semibold">Live Executions</p>
      <div className="space-y-2">
        {executions.slice(0, 10).map((exec, i) => {
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
              {!isNaN(price) && price > 0 && <span>${price.toLocaleString()}</span>}
              {!isNaN(size) && size > 0 && <span className="text-muted-foreground">×{size}</span>}
              {pnl !== null && !isNaN(pnl) && (
                <span className={cn("font-medium", pnl >= 0 ? "text-green-600" : "text-red-500")}>
                  {formatPnl(pnl)}
                  {pnlPct !== null && !isNaN(pnlPct) && (
                    <span className="ml-1 text-xs">({formatPct(pnlPct)})</span>
                  )}
                </span>
              )}
              {exec.reason && <span className="text-xs text-muted-foreground">{exec.reason}</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
