"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Pencil, Check, X } from "lucide-react";
import { toast } from "sonner";
import { watchedAssets, strategies } from "@/lib/api";
import type { WatchedAsset } from "@/lib/types";
import { cn } from "@/lib/utils";

const TIMEFRAME_OPTIONS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"];
const MARKET_TYPES = ["futures", "spot", "options"];
const EXCHANGES = ["binance", "bybit", "okx"];

interface AssetFormState {
  symbol: string;
  exchange: string;
  market_type: string;
  timeframes: string[];
  enabled: boolean;
}

const defaultForm = (): AssetFormState => ({
  symbol: "",
  exchange: "binance",
  market_type: "futures",
  timeframes: ["1h"],
  enabled: true,
});

function TimeframeChips({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  const toggle = (tf: string) =>
    onChange(selected.includes(tf) ? selected.filter((t) => t !== tf) : [...selected, tf]);

  return (
    <div className="flex flex-wrap gap-1.5">
      {TIMEFRAME_OPTIONS.map((tf) => (
        <button
          key={tf}
          type="button"
          onClick={() => toggle(tf)}
          className={cn(
            "rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors",
            selected.includes(tf)
              ? "bg-primary text-primary-foreground"
              : "bg-secondary text-secondary-foreground hover:bg-secondary/80"
          )}
        >
          {tf}
        </button>
      ))}
    </div>
  );
}

function AssetForm({
  initial,
  onSubmit,
  onCancel,
  loading,
}: {
  initial: AssetFormState;
  onSubmit: (v: AssetFormState) => void;
  onCancel: () => void;
  loading: boolean;
}) {
  const [form, setForm] = useState(initial);
  const [symbolError, setSymbolError] = useState<string | null>(null);
  const [validating, setValidating] = useState(false);

  async function validateAndSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSymbolError(null);
    setValidating(true);
    try {
      const info = await strategies.validateSymbol({
        symbol: form.symbol,
        exchange: form.exchange,
        market_type: form.market_type,
      });
      if (!info) {
        setSymbolError(`Symbol "${form.symbol}" not found on ${form.exchange} ${form.market_type}`);
        return;
      }
    } catch {
      setSymbolError("Could not validate symbol — check your connection");
      return;
    } finally {
      setValidating(false);
    }
    onSubmit(form);
  }

  return (
    <form onSubmit={validateAndSubmit} className="rounded-lg border bg-card p-5 space-y-4">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Symbol *</label>
          <input
            required
            value={form.symbol}
            onChange={(e) => { setForm((f) => ({ ...f, symbol: e.target.value.toLowerCase() })); setSymbolError(null); }}
            placeholder="btcusdt"
            className={cn(
              "w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring font-mono",
              symbolError && "border-destructive focus:ring-destructive"
            )}
          />
          {symbolError && <p className="mt-1 text-xs text-destructive">{symbolError}</p>}
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Exchange</label>
          <select
            value={form.exchange}
            onChange={(e) => setForm((f) => ({ ...f, exchange: e.target.value }))}
            className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          >
            {EXCHANGES.map((ex) => <option key={ex} value={ex}>{ex}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Market Type</label>
          <select
            value={form.market_type}
            onChange={(e) => setForm((f) => ({ ...f, market_type: e.target.value }))}
            className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          >
            {MARKET_TYPES.map((mt) => <option key={mt} value={mt}>{mt}</option>)}
          </select>
        </div>
      </div>

      <div>
        <label className="block text-xs text-muted-foreground mb-2">Timeframes</label>
        <TimeframeChips selected={form.timeframes} onChange={(v) => setForm((f) => ({ ...f, timeframes: v }))} />
        {form.timeframes.length === 0 && (
          <p className="mt-1 text-xs text-destructive">Select at least one timeframe</p>
        )}
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.enabled}
          onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
        />
        Enabled (actively fetch data)
      </label>

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={loading || validating || form.timeframes.length === 0}
          className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
        >
          <Check className="h-3.5 w-3.5" />
          {validating ? "Validating…" : loading ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="flex items-center gap-1.5 rounded-md border px-4 py-1.5 text-sm font-medium hover:bg-accent"
        >
          <X className="h-3.5 w-3.5" />
          Cancel
        </button>
      </div>
    </form>
  );
}

function WatchedAssetRow({
  asset,
  onEdit,
  onDelete,
  onToggle,
}: {
  asset: WatchedAsset;
  onEdit: () => void;
  onDelete: () => void;
  onToggle: () => void;
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-lg border bg-card p-4">
      <div className="space-y-1.5 min-w-0">
        <div className="flex items-center gap-2">
          <button
            onClick={onToggle}
            className={cn(
              "h-2.5 w-2.5 rounded-full flex-shrink-0 transition-colors",
              asset.enabled ? "bg-green-500" : "bg-muted-foreground"
            )}
            title={asset.enabled ? "Enabled — click to disable" : "Disabled — click to enable"}
          />
          <span className="font-semibold font-mono uppercase">{asset.symbol}</span>
          <span className="text-xs text-muted-foreground">
            {asset.exchange} · {asset.market_type}
          </span>
          {(asset.base_asset || asset.quote_asset) && (
            <span className="text-xs text-muted-foreground">
              ({asset.base_asset}/{asset.quote_asset})
            </span>
          )}
        </div>
        <div className="flex flex-wrap gap-1">
          {asset.timeframes.map((tf) => (
            <span key={tf} className="rounded-full bg-secondary px-2 py-0.5 text-xs font-medium">
              {tf}
            </span>
          ))}
        </div>
      </div>
      <div className="flex items-center gap-1 flex-shrink-0">
        <button
          onClick={onEdit}
          className="rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
          title="Edit"
        >
          <Pencil className="h-4 w-4" />
        </button>
        <button
          onClick={onDelete}
          className="rounded-md p-2 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
          title="Delete"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

export default function WatchedAssetsPage() {
  const qc = useQueryClient();
  const [showAdd, setShowAdd] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["watched-assets"],
    queryFn: () => watchedAssets.list(),
  });

  const createMutation = useMutation({
    mutationFn: (body: AssetFormState) => watchedAssets.create(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["watched-assets"] });
      setShowAdd(false);
      toast.success("Asset added");
    },
    onError: (e: unknown) => {
      const msg = (e as { detail?: string })?.detail ?? String(e);
      toast.error(msg);
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Partial<AssetFormState> }) =>
      watchedAssets.update(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["watched-assets"] });
      setEditingId(null);
      toast.success("Asset updated");
    },
    onError: (e: unknown) => {
      const msg = (e as { detail?: string })?.detail ?? String(e);
      toast.error(msg);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => watchedAssets.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["watched-assets"] });
      toast.success("Asset removed");
    },
  });

  function handleDelete(asset: WatchedAsset) {
    if (confirm(`Remove ${asset.symbol.toUpperCase()} from watched assets?`)) {
      deleteMutation.mutate(asset.id);
    }
  }

  function handleToggle(asset: WatchedAsset) {
    updateMutation.mutate({ id: asset.id, body: { enabled: !asset.enabled } });
  }

  const editingAsset = data?.find((a) => a.id === editingId);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Watched Assets</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Assets that the data fetcher subscribes to independently of strategies.
          </p>
        </div>
        {!showAdd && (
          <button
            onClick={() => setShowAdd(true)}
            className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            <Plus className="h-4 w-4" />
            Add Asset
          </button>
        )}
      </div>

      {showAdd && (
        <AssetForm
          initial={defaultForm()}
          onSubmit={(body) => createMutation.mutate(body)}
          onCancel={() => setShowAdd(false)}
          loading={createMutation.isPending}
        />
      )}

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}

      {!isLoading && data?.length === 0 && (
        <div className="rounded-lg border border-dashed p-10 text-center">
          <p className="text-muted-foreground">No watched assets yet.</p>
          <button
            onClick={() => setShowAdd(true)}
            className="mt-2 text-sm font-medium text-primary"
          >
            Add your first asset →
          </button>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {data?.map((asset) =>
          editingId === asset.id && editingAsset ? (
            <div key={asset.id} className="sm:col-span-2 lg:col-span-3">
              <AssetForm
                initial={{
                  symbol: editingAsset.symbol,
                  exchange: editingAsset.exchange,
                  market_type: editingAsset.market_type,
                  timeframes: editingAsset.timeframes,
                  enabled: editingAsset.enabled,
                }}
                onSubmit={(body) => updateMutation.mutate({ id: asset.id, body })}
                onCancel={() => setEditingId(null)}
                loading={updateMutation.isPending}
              />
            </div>
          ) : (
            <WatchedAssetRow
              key={asset.id}
              asset={asset}
              onEdit={() => setEditingId(asset.id)}
              onDelete={() => handleDelete(asset)}
              onToggle={() => handleToggle(asset)}
            />
          )
        )}
      </div>
    </div>
  );
}
