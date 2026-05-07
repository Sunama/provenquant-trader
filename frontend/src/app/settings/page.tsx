"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Pencil } from "lucide-react";
import { toast } from "sonner";
import { appSettings, exchangeAccounts } from "@/lib/api";
import type { ExchangeAccount } from "@/lib/types";

function ProvenQuantSection() {
  const { data } = useQuery({
    queryKey: ["provenquant-settings"],
    queryFn: () => appSettings.getProvenQuant(),
  });

  const [apiUrl, setApiUrl] = useState("");
  const [apiKey, setApiKey] = useState("");

  const mutation = useMutation({
    mutationFn: () => appSettings.updateProvenQuant({ api_url: apiUrl, api_key: apiKey }),
    onSuccess: () => toast.success("ProvenQuant settings saved"),
    onError: (e) => toast.error(String(e)),
  });

  return (
    <section className="rounded-lg border bg-card p-6 space-y-4">
      <h2 className="text-base font-semibold">ProvenQuant API Integration</h2>
      <div className="space-y-3 max-w-md">
        <div>
          <label className="block text-xs text-muted-foreground mb-1">API URL</label>
          <input
            value={apiUrl}
            onChange={(e) => setApiUrl(e.target.value)}
            placeholder={data?.api_url || "https://api.provenquant.com"}
            className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">API Key</label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={data?.api_key_preview || "Enter API key…"}
            className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>
        <button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
          className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
        >
          {mutation.isPending ? "Saving…" : "Save"}
        </button>
      </div>
    </section>
  );
}

function AccountDialog({
  onClose,
  existing,
}: {
  onClose: () => void;
  existing?: ExchangeAccount;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState(existing?.name ?? "");
  const [exchange, setExchange] = useState(existing?.exchange ?? "binance");
  const [isPaper, setIsPaper] = useState(existing?.is_paper ?? false);
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [description, setDescription] = useState(existing?.description ?? "");

  const mutation = useMutation({
    mutationFn: () => {
      const body = isPaper
        ? { name, exchange, is_paper: true, description }
        : { name, exchange, is_paper: false, api_key: apiKey, api_secret: apiSecret, description };
      return existing
        ? exchangeAccounts.update(existing.id, body)
        : exchangeAccounts.create(body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["exchange-accounts"] });
      toast.success(existing ? "Account updated" : "Account created");
      onClose();
    },
    onError: (e) => toast.error(String(e)),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-md rounded-lg bg-background border p-6 space-y-4">
        <h3 className="text-base font-semibold">{existing ? "Edit Account" : "Add Exchange Account"}</h3>
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Name *</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required
              className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring" />
          </div>
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Exchange *</label>
            <select value={exchange} onChange={(e) => setExchange(e.target.value)}
              className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring">
              <option value="binance">Binance</option>
              <option value="bybit">Bybit</option>
              <option value="okx">OKX</option>
            </select>
          </div>
          <label className="flex items-center gap-2.5 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={isPaper}
              onChange={(e) => setIsPaper(e.target.checked)}
              className="h-4 w-4 rounded border accent-primary"
            />
            <span className="text-sm font-medium">Paper Trade</span>
            <span className="text-xs text-muted-foreground">(ไม่ต้องใช้ API Key)</span>
          </label>
          {!isPaper && (
            <>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">
                  API Key {existing && !existing.is_paper && "(leave blank to keep)"}
                </label>
                <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                  placeholder={existing?.api_key_preview ?? ""}
                  className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring" />
              </div>
              <div>
                <label className="block text-xs text-muted-foreground mb-1">
                  API Secret {existing && !existing.is_paper && "(leave blank to keep)"}
                </label>
                <input type="password" value={apiSecret} onChange={(e) => setApiSecret(e.target.value)}
                  className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring" />
              </div>
            </>
          )}
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Description</label>
            <input value={description} onChange={(e) => setDescription(e.target.value)}
              className="w-full rounded-md border px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring" />
          </div>
        </div>
        <div className="flex gap-3">
          <button onClick={() => mutation.mutate()} disabled={mutation.isPending}
            className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60">
            {mutation.isPending ? "Saving…" : "Save"}
          </button>
          <button onClick={onClose} className="rounded-md border px-4 py-1.5 text-sm font-medium hover:bg-accent">Cancel</button>
        </div>
      </div>
    </div>
  );
}

function ExchangeAccountsSection() {
  const qc = useQueryClient();
  const [dialog, setDialog] = useState<"create" | ExchangeAccount | null>(null);

  const { data } = useQuery({
    queryKey: ["exchange-accounts"],
    queryFn: () => exchangeAccounts.list(),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => exchangeAccounts.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["exchange-accounts"] }); toast.success("Deleted"); },
    onError: (e) => toast.error(String(e)),
  });

  return (
    <section className="rounded-lg border bg-card p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">Exchange Accounts</h2>
        <button onClick={() => setDialog("create")}
          className="flex items-center gap-2 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90">
          <Plus className="h-3 w-3" />
          Add Account
        </button>
      </div>

      {!data || data.length === 0 ? (
        <p className="text-sm text-muted-foreground">No exchange accounts. Add one to enable real trading.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-xs text-muted-foreground">
              <th className="pb-2 text-left font-medium">Name</th>
              <th className="pb-2 text-left font-medium">Exchange</th>
              <th className="pb-2 text-left font-medium">API Key</th>
              <th className="pb-2 text-left font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {data.map((account) => (
              <tr key={account.id} className="border-b last:border-0">
                <td className="py-2 font-medium">{account.name}</td>
                <td className="py-2 capitalize">{account.exchange}</td>
                <td className="py-2 font-mono text-xs text-muted-foreground">
                  {account.is_paper
                    ? <span className="rounded px-1.5 py-0.5 bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300 text-xs font-medium not-italic">Paper</span>
                    : account.api_key_preview}
                </td>
                <td className="py-2">
                  <div className="flex gap-1">
                    <button onClick={() => setDialog(account)}
                      className="rounded p-1 text-muted-foreground hover:bg-accent">
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button onClick={() => { if (confirm("Delete this account?")) deleteMutation.mutate(account.id); }}
                      className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {dialog !== null && (
        <AccountDialog
          onClose={() => setDialog(null)}
          existing={dialog === "create" ? undefined : dialog}
        />
      )}
    </section>
  );
}

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>
      <ProvenQuantSection />
      <ExchangeAccountsSection />
    </div>
  );
}
