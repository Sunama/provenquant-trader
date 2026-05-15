import { cn } from "@/lib/utils";
import type { SignalPayload } from "@/lib/types";

interface Props {
  signals: SignalPayload[];
}

export function RecentSignalsPanel({ signals }: Props) {
  if (signals.length === 0) return null;
  return (
    <div className="rounded-lg border bg-card p-5">
      <p className="mb-1 text-sm font-semibold">Recent Signals</p>
      <p className="mb-3 text-xs text-muted-foreground">Actions requested by the strategy (pre-execution)</p>
      <div className="space-y-2">
        {signals.slice(0, 10).map((sig, i) => {
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
              {!isNaN(price) && price > 0 && <span>${price.toLocaleString()}</span>}
              {!isNaN(amount) && <span className="text-muted-foreground">{(amount * 100).toFixed(0)}%</span>}
              {!isNaN(ts) && (
                <span className="text-xs text-muted-foreground">{new Date(ts * 1000).toLocaleTimeString()}</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
