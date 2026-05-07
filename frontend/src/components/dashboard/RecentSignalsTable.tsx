"use client";

import { useLiveDataStore } from "@/lib/store/useLiveDataStore";
import { cn } from "@/lib/utils";

const SIDE_COLOR: Record<string, string> = {
  long: "text-green-600",
  buy: "text-green-600",
  call: "text-green-600",
  short: "text-red-500",
  sell: "text-red-500",
  put: "text-red-500",
};

export function RecentSignalsTable() {
  const signals = useLiveDataStore((s) => s.recentSignals);

  if (signals.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-5">
        <p className="mb-3 text-sm font-semibold">Recent Signals</p>
        <p className="text-sm text-muted-foreground">No signals yet — waiting for strategy execution.</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card p-5">
      <p className="mb-3 text-sm font-semibold">Recent Signals</p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-xs text-muted-foreground">
              <th className="pb-2 text-left font-medium">Strategy</th>
              <th className="pb-2 text-left font-medium">Action</th>
              <th className="pb-2 text-left font-medium">Price</th>
              <th className="pb-2 text-left font-medium">Amount</th>
              <th className="pb-2 text-left font-medium">Time</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((sig, i) => (
              <tr key={i} className="border-b last:border-0">
                <td className="py-2 font-mono text-xs">{sig.config_id || sig.strategy_id}</td>
                <td className={cn("py-2 font-semibold uppercase", SIDE_COLOR[sig.execute] ?? "")}>
                  {sig.execute}
                </td>
                <td className="py-2">${parseFloat(sig.price).toLocaleString()}</td>
                <td className="py-2">{(parseFloat(sig.amount) * 100).toFixed(0)}%</td>
                <td className="py-2 text-muted-foreground">
                  {new Date(parseFloat(sig.ts) * 1000).toLocaleTimeString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
