"use client";

import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Pencil, Trash2, Power } from "lucide-react";
import { toast } from "sonner";
import { strategies } from "@/lib/api";
import type { Strategy } from "@/lib/types";
import { cn } from "@/lib/utils";

function StrategyCard({ strategy }: { strategy: Strategy }) {
  const qc = useQueryClient();

  const toggleMutation = useMutation({
    mutationFn: () => strategies.toggle(strategy.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategies"] });
      toast.success(`Strategy ${strategy.enabled ? "disabled" : "enabled"}`);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => strategies.delete(strategy.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategies"] });
      toast.success("Strategy deleted");
    },
  });

  return (
    <div className="rounded-lg border bg-card p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "h-2 w-2 rounded-full",
                strategy.enabled ? "bg-green-500" : "bg-muted-foreground"
              )}
            />
            <span className="font-semibold">{strategy.name}</span>
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground font-mono">{strategy.strategy_class}</p>
          {strategy.description && (
            <p className="mt-1 text-sm text-muted-foreground">{strategy.description}</p>
          )}

          {strategy.assets.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {strategy.assets.map((a) => (
                <span
                  key={a.leg_num}
                  className="rounded-full bg-secondary px-2 py-0.5 text-xs font-medium"
                >
                  {a.symbol.toUpperCase()} {a.timeframe} ({a.market_type})
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={() => toggleMutation.mutate()}
            className="rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            title={strategy.enabled ? "Disable" : "Enable"}
          >
            <Power className="h-4 w-4" />
          </button>
          <Link
            href={`/strategies/${strategy.id}/edit`}
            className="rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
          >
            <Pencil className="h-4 w-4" />
          </Link>
          <button
            onClick={() => {
              if (confirm(`Delete strategy "${strategy.id}"?`)) {
                deleteMutation.mutate();
              }
            }}
            className="rounded-md p-2 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="mt-3">
        <Link
          href={`/strategies/${strategy.id}`}
          className="text-xs font-medium text-primary underline-offset-4 hover:underline"
        >
          View details →
        </Link>
      </div>
    </div>
  );
}

export default function StrategiesPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["strategies"],
    queryFn: () => strategies.list(),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Strategies</h1>
        <Link
          href="/strategies/new"
          className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          <Plus className="h-4 w-4" />
          New Strategy
        </Link>
      </div>

      {isLoading && <p className="text-muted-foreground">Loading…</p>}

      {data && data.length === 0 && (
        <div className="rounded-lg border border-dashed p-10 text-center">
          <p className="text-muted-foreground">No strategies yet.</p>
          <Link href="/strategies/new" className="mt-2 inline-block text-sm font-medium text-primary">
            Create your first strategy →
          </Link>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {data?.map((strategy) => (
          <StrategyCard key={strategy.id} strategy={strategy} />
        ))}
      </div>
    </div>
  );
}
