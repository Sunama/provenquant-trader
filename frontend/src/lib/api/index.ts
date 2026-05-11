import { api } from "./client";
import type {
  Strategy,
  Position,
  PositionStats,
  ExchangeAccount,
  WatchedAsset,
  Kline,
  StrategyClassInfo,
  IndicatorSeries,
  TradeHistory,
} from "@/lib/types";

// ── Strategies ─────────────────────────────────────────────

export const strategies = {
  list: () => api.get<Strategy[]>("/strategies/"),
  get: (id: string) => api.get<Strategy>(`/strategies/${id}`),
  create: (body: unknown) => api.post<{ id: string }>("/strategies/", body),
  update: (id: string, body: unknown) => api.put<{ id: string }>(`/strategies/${id}`, body),
  delete: (id: string) => api.delete<void>(`/strategies/${id}`),
  toggle: (id: string) => api.patch<{ id: string; enabled: boolean }>(`/strategies/${id}/toggle`),
  classes: () => api.get<StrategyClassInfo[]>("/strategies/classes"),
  schema: (classPath: string) =>
    api.get<{ id: string; parameter_schema: unknown[]; subscriptions_template: unknown[] }>(
      `/strategies/schema?class_path=${encodeURIComponent(classPath)}`
    ),
  indicators: (strategyId: string, params: { symbol: string; timeframe: string; limit?: number }) => {
    const q = new URLSearchParams(
      Object.fromEntries(
        Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)])
      )
    );
    return api.get<IndicatorSeries[]>(`/strategies/${strategyId}/indicators?${q}`);
  },
  validateSymbol: (params: { symbol: string; exchange: string; market_type: string }) => {
    const q = new URLSearchParams(params);
    return api.get<{ symbol: string; base_asset: string; quote_asset: string } | null>(
      `/strategies/validate-symbol?${q}`
    );
  },
};

// ── Positions ─────────────────────────────────────────────

export const positions = {
  list: (params?: { open_only?: boolean; strategy_id?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.open_only) q.set("open_only", "true");
    if (params?.strategy_id) q.set("strategy_id", params.strategy_id);
    if (params?.limit) q.set("limit", String(params.limit));
    return api.get<Position[]>(`/positions/?${q}`);
  },
  get: (id: number) => api.get<Position>(`/positions/${id}`),
  stats: (strategyId?: string) =>
    api.get<PositionStats>(`/positions/stats${strategyId ? `?strategy_id=${strategyId}` : ""}`),
};

// ── Exchange Accounts ─────────────────────────────────────

export const exchangeAccounts = {
  list: () => api.get<ExchangeAccount[]>("/exchange-accounts/"),
  get: (id: string) => api.get<ExchangeAccount>(`/exchange-accounts/${id}`),
  create: (body: unknown) => api.post<ExchangeAccount>("/exchange-accounts/", body),
  update: (id: string, body: unknown) => api.put<ExchangeAccount>(`/exchange-accounts/${id}`, body),
  delete: (id: string) => api.delete<void>(`/exchange-accounts/${id}`),
};

// ── Watched Assets ────────────────────────────────────────

export const watchedAssets = {
  list: () => api.get<WatchedAsset[]>("/watched-assets/"),
  create: (body: unknown) => api.post<WatchedAsset>("/watched-assets/", body),
  update: (id: number, body: unknown) => api.put<WatchedAsset>(`/watched-assets/${id}`, body),
  delete: (id: number) => api.delete<void>(`/watched-assets/${id}`),
};

// ── Market Data ───────────────────────────────────────────

export const marketData = {
  klines: (params: { symbol: string; timeframe: string; exchange?: string; market_type?: string; limit?: number }) => {
    const q = new URLSearchParams(
      Object.fromEntries(
        Object.entries(params).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)])
      )
    );
    return api.get<Kline[]>(`/market-data/klines?${q}`);
  },
  orderbook: (symbol: string, exchange = "binance", market_type = "futures") =>
    api.get<{ bids: number[][]; asks: number[][]; time: number | null }>(
      `/market-data/orderbook?symbol=${symbol}&exchange=${exchange}&market_type=${market_type}`
    ),
};

// ── Trade History ─────────────────────────────────────────

export const tradeHistory = {
  list: (params?: { strategy_id?: string; symbol?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.strategy_id) q.set("strategy_id", params.strategy_id);
    if (params?.symbol) q.set("symbol", params.symbol);
    if (params?.limit) q.set("limit", String(params.limit));
    return api.get<TradeHistory[]>(`/trade-history/?${q}`);
  },
};

// ── Trades / Balance ──────────────────────────────────────

export const trades = {
  balance: () => api.get<{ balance: number }>("/trades/balance"),
};

// ── Settings ──────────────────────────────────────────────

export const appSettings = {
  getProvenQuant: () => api.get<{ api_url: string; api_key_preview: string }>("/settings/provenquant"),
  updateProvenQuant: (body: { api_url: string; api_key: string }) =>
    api.put<{ status: string }>("/settings/provenquant", body),
  systemStatus: () => api.get<{ redis_connected: boolean; db_connected: boolean }>("/settings/system"),
};
