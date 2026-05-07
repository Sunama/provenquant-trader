"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Plus, Trash2, GripVertical } from "lucide-react";
import { toast } from "sonner";
import { strategies, exchangeAccounts } from "@/lib/api";
import type { Strategy, StrategyAsset, StrategyExchangeRef, ParameterSchema } from "@/lib/types";

interface Props {
  initial?: Strategy;
}

const MARKET_TYPES = ["futures", "spot", "options"];
const TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"];
const EXCHANGES = ["binance", "bybit", "okx"];

function ParameterInput({ schema, value, onChange }: { schema: ParameterSchema; value: unknown; onChange: (v: unknown) => void }) {
  const current = value ?? schema.default;
  if (schema.type === "bool") {
    return (
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={!!current} onChange={(e) => onChange(e.target.checked)} className="h-4 w-4" />
        <span className="text-sm">{schema.description || schema.name}</span>
      </label>
    );
  }
  return (
    <div>
      <label className="block text-xs text-muted-foreground mb-1">{schema.name} ({schema.type})</label>
      <input
        type="number"
        min={schema.min}
        max={schema.max}
        step={schema.type === "float" ? "any" : "1"}
        value={current as number}
        onChange={(e) => onChange(schema.type === "int" ? parseInt(e.target.value) : parseFloat(e.target.value))}
        className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
      />
      {schema.description && <p className="mt-0.5 text-xs text-muted-foreground">{schema.description}</p>}
    </div>
  );
}

export function StrategyEditor({ initial }: Props) {
  const router = useRouter();
  const isEdit = !!initial;

  const [id, setId] = useState(initial?.id ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [classPath, setClassPath] = useState(initial?.strategy_class ?? "");
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [params, setParams] = useState<Record<string, unknown>>(initial?.params ?? {});
  const [assets, setAssets] = useState<Omit<StrategyAsset, "asset_num">[]>(
    initial?.assets.map(({ asset_num: _, ...a }) => a) ?? []
  );
  const [exchangeRefs, setExchangeRefs] = useState<Omit<StrategyExchangeRef, "exchange_num">[]>(
    initial?.exchange_accounts.map(({ exchange_num: _, ...r }) => r) ?? []
  );

  const { data: classes } = useQuery({
    queryKey: ["strategy-classes"],
    queryFn: () => strategies.classes(),
  });

  const { data: schema } = useQuery({
    queryKey: ["strategy-schema", classPath],
    queryFn: () => strategies.schema(classPath),
    enabled: !!classPath,
  });

  const { data: accounts } = useQuery({
    queryKey: ["exchange-accounts"],
    queryFn: () => exchangeAccounts.list(),
  });

  const mutation = useMutation({
    mutationFn: (body: unknown) =>
      isEdit ? strategies.update(initial.id, body) : strategies.create(body),
    onSuccess: () => {
      toast.success(isEdit ? "Strategy updated" : "Strategy created");
      router.push("/strategies");
    },
    onError: (e) => toast.error(String(e)),
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const body = {
      id,
      strategy_class: classPath,
      description,
      enabled,
      params,
      parameters_schema: schema?.parameter_schema,
      assets: assets.map((a, i) => ({ ...a, asset_num: i })),
      exchange_accounts: exchangeRefs.map((r, i) => ({ ...r, exchange_num: i })),
    };
    mutation.mutate(body);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-8 max-w-2xl">
      {/* Section 1 — Basic Info */}
      <section className="space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Basic Info</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Strategy ID *</label>
            <input
              required
              disabled={isEdit}
              value={id}
              onChange={(e) => setId(e.target.value)}
              placeholder="my-rsi-btc"
              className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-60"
            />
          </div>
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Strategy Class *</label>
            <select
              value={classPath}
              onChange={(e) => {
                const val = e.target.value;
                setClassPath(val);
                if (!isEdit && val) {
                  const cls = classes?.find((c) => c.class_path === val);
                  if (cls?.default_subscriptions?.length) {
                    setAssets(
                      cls.default_subscriptions.map((s) => ({
                        asset_slug: s.asset_slug,
                        exchange: s.exchange,
                        timeframe: s.timeframe,
                        market_type: s.market_type as StrategyAsset["market_type"],
                        tick_process: s.tick_process,
                        description: s.description,
                      }))
                    );
                  }
                }
              }}
              className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="">Select a class…</option>
              {classes?.map((c) => (
                <option key={c.class_path} value={c.class_path}>
                  {c.class_path}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Description</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          <span className="text-sm">Enabled</span>
        </label>
      </section>

      {/* Section 2 — Parameters */}
      {schema && schema.parameter_schema.length > 0 && (
        <section className="space-y-4">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Parameters</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {(schema.parameter_schema as ParameterSchema[]).map((ps) => (
              <ParameterInput
                key={ps.name}
                schema={ps}
                value={params[ps.name]}
                onChange={(v) => setParams((prev) => ({ ...prev, [ps.name]: v }))}
              />
            ))}
          </div>
        </section>
      )}

      {/* Section 3 — Assets */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Assets</h2>
          <button
            type="button"
            onClick={() => setAssets((prev) => [...prev, { asset_slug: "", exchange: "binance", timeframe: "1m", market_type: "futures", tick_process: prev.length === 0 }])}
            className="flex items-center gap-1 text-xs text-primary font-medium hover:underline"
          >
            <Plus className="h-3 w-3" />
            Add Asset
          </button>
        </div>
        {assets.length === 0 && <p className="text-sm text-muted-foreground">Add at least one asset.</p>}
        {assets.map((asset, i) => (
          <div key={i} className="rounded-md border p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono text-muted-foreground">Asset #{i}</span>
              <button type="button" onClick={() => setAssets((prev) => prev.filter((_, j) => j !== i))}>
                <Trash2 className="h-4 w-4 text-destructive" />
              </button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Asset Slug *</label>
                <input
                  required
                  value={asset.asset_slug}
                  onChange={(e) => setAssets((prev) => prev.map((a, j) => j === i ? { ...a, asset_slug: e.target.value } : a))}
                  placeholder="btcusdt"
                  className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Exchange</label>
                <select
                  value={asset.exchange}
                  onChange={(e) => setAssets((prev) => prev.map((a, j) => j === i ? { ...a, exchange: e.target.value } : a))}
                  className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  {EXCHANGES.map((ex) => <option key={ex} value={ex}>{ex}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Timeframe</label>
                <select
                  value={asset.timeframe}
                  onChange={(e) => setAssets((prev) => prev.map((a, j) => j === i ? { ...a, timeframe: e.target.value } : a))}
                  className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  {TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Market Type</label>
                <select
                  value={asset.market_type}
                  onChange={(e) => setAssets((prev) => prev.map((a, j) => j === i ? { ...a, market_type: e.target.value as StrategyAsset["market_type"] } : a))}
                  className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  {MARKET_TYPES.map((mt) => <option key={mt} value={mt}>{mt}</option>)}
                </select>
              </div>
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Description (optional)</label>
              <input
                value={asset.description ?? ""}
                onChange={(e) => setAssets((prev) => prev.map((a, j) => j === i ? { ...a, description: e.target.value } : a))}
                placeholder="e.g. Primary trend asset"
                className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={asset.tick_process}
                onChange={(e) => setAssets((prev) => prev.map((a, j) => j === i ? { ...a, tick_process: e.target.checked } : a))}
              />
              Tick trigger (receiving this asset's tick triggers strategy execution)
            </label>
          </div>
        ))}
      </section>

      {/* Section 4 — Exchange Accounts */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Exchange Accounts</h2>
          <button
            type="button"
            onClick={() => setExchangeRefs((prev) => [...prev, { exchange_account_id: "", description: "" }])}
            className="flex items-center gap-1 text-xs text-primary font-medium hover:underline"
          >
            <Plus className="h-3 w-3" />
            Add Account
          </button>
        </div>
        {exchangeRefs.map((ref, i) => (
          <div key={i} className="rounded-md border p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono text-muted-foreground">Exchange #{i}</span>
              <button type="button" onClick={() => setExchangeRefs((prev) => prev.filter((_, j) => j !== i))}>
                <Trash2 className="h-4 w-4 text-destructive" />
              </button>
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Account *</label>
              <select
                value={ref.exchange_account_id}
                onChange={(e) => setExchangeRefs((prev) => prev.map((r, j) => j === i ? { ...r, exchange_account_id: e.target.value } : r))}
                className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="">Select account…</option>
                {accounts?.map((a) => (
                  <option key={a.id} value={a.id}>{a.name} ({a.exchange})</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Description (optional)</label>
              <input
                value={ref.description ?? ""}
                onChange={(e) => setExchangeRefs((prev) => prev.map((r, j) => j === i ? { ...r, description: e.target.value } : r))}
                placeholder="e.g. Main execution account"
                className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
          </div>
        ))}
      </section>

      <div className="flex gap-3">
        <button
          type="submit"
          disabled={mutation.isPending}
          className="rounded-md bg-primary px-6 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
        >
          {mutation.isPending ? "Saving…" : isEdit ? "Update Strategy" : "Create Strategy"}
        </button>
        <button
          type="button"
          onClick={() => router.back()}
          className="rounded-md border px-6 py-2 text-sm font-medium hover:bg-accent"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
