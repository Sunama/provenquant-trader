"use client";

import { useState, FormEvent } from "react";

function resolveBase(): string {
  if (typeof window !== "undefined")
    return `${window.location.protocol}//${window.location.hostname}:8001/api`;
  return "/api";
}

export default function AuthPage() {
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!key.trim()) return;

    setLoading(true);
    setError("");

    try {
      const res = await fetch(`${resolveBase()}/auth/ping`, {
        headers: { Authorization: `Bearer ${key.trim()}` },
      });

      if (res.ok) {
        document.cookie = `api_key=${encodeURIComponent(key.trim())}; path=/; SameSite=Strict`;
        window.location.href = "/";
      } else {
        setError("Invalid API key — check your .env file.");
      }
    } catch {
      setError("Cannot reach the backend. Is it running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex bg-background">
      {/* Left panel — branding */}
      <div className="hidden lg:flex lg:w-2/5 flex-col justify-between border-r bg-muted/40 p-12">
        <div className="text-lg font-bold tracking-tight">ProvenQuant Trader</div>
        <div className="space-y-3">
          <p className="text-2xl font-semibold leading-snug">
            Automated paper trading,<br />at your fingertips.
          </p>
          <p className="text-sm text-muted-foreground">
            Monitor strategies, track positions, and analyse performance — all in one place.
          </p>
        </div>
        <p className="text-xs text-muted-foreground">Self-hosted · Open source</p>
      </div>

      {/* Right panel — form */}
      <div className="flex flex-1 flex-col items-center justify-center px-8 py-12">
        <div className="w-full max-w-sm space-y-8">
          {/* Mobile title */}
          <div className="lg:hidden">
            <p className="text-xl font-bold">ProvenQuant Trader</p>
          </div>

          <div className="space-y-1.5">
            <h1 className="text-xl font-semibold">Sign in</h1>
            <p className="text-sm text-muted-foreground">
              Enter the <code className="rounded bg-muted px-1 py-0.5 text-xs font-mono">API_KEY</code> from your <code className="rounded bg-muted px-1 py-0.5 text-xs font-mono">.env</code> file.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="block text-xs font-medium text-muted-foreground">API Key</label>
              <input
                type="password"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="Paste your key here…"
                autoFocus
                className="w-full rounded-md border bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>

            {error && (
              <p className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading || !key.trim()}
              className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm hover:bg-primary/90 disabled:opacity-60"
            >
              {loading ? "Verifying…" : "Sign in"}
            </button>
          </form>

          <p className="text-xs text-muted-foreground">
            The key is stored in a browser cookie and sent as a Bearer token on every request.
          </p>
        </div>
      </div>
    </div>
  );
}
