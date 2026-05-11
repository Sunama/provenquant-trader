export interface StrategyAsset {
  leg_num: number;
  role: string;
  symbol: string;
  exchange: string;
  timeframe: string;
  market_type: "spot" | "futures" | "options";
  tick_process: boolean;
  subscribe_depth: boolean;
  exchange_account_num: number;
  base_asset?: string;
  quote_asset?: string;
  description?: string;
}

export interface StrategyExchangeRef {
  exchange_num: number;
  exchange_account_id: string;
  description?: string;
}

export interface ParameterSchema {
  name: string;
  type: "bool" | "int" | "float" | "str";
  default: unknown;
  min?: number;
  max?: number;
  description?: string;
}

export type SignalAction =
  | "buy"
  | "sell"
  | "open_long"
  | "close_long"
  | "open_short"
  | "close_short";

export interface SignalDefinition {
  name: string;
  leg_num: number;
  exchange_num: number;
  market_type: string;
  execute: SignalAction;
  amount: number;
}

export interface Strategy {
  id: string;
  name: string;
  strategy_class: string;
  description?: string;
  enabled: boolean;
  is_paper: boolean;
  params: Record<string, unknown>;
  parameters_schema?: ParameterSchema[];
  signal_definitions?: SignalDefinition[];
  assets: StrategyAsset[];
  exchange_accounts: StrategyExchangeRef[];
  created_at?: string;
  updated_at?: string;
}

export interface Position {
  id: number;
  strategy_id: string;
  symbol: string;
  side: string;
  entry_price: number;
  entry_time: string;
  size: number;
  exit_price?: number;
  exit_time?: string;
  exit_reason?: string;
  pnl?: number;
  pnl_pct?: number;
  is_open: boolean;
  created_at?: string;
}

export interface PositionStats {
  total_trades: number;
  total_pnl: number;
  win_rate: number;
  wins: number;
}

export interface ExchangeAccount {
  id: string;
  name: string;
  exchange: string;
  is_paper: boolean;
  description?: string;
  api_key_preview?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface DefaultSubscription {
  symbol: string;
  exchange: string;
  timeframe: string;
  market_type: "spot" | "futures" | "options";
  tick_process: boolean;
  role?: string;
  subscribe_depth?: boolean;
  description: string;
}

export interface StrategyClassInfo {
  class_path: string;
  id: string | null;
  parameter_schema: ParameterSchema[];
  default_subscriptions: DefaultSubscription[];
}

export interface WatchedAsset {
  id: number;
  symbol: string;
  exchange: string;
  market_type: string;
  enabled: boolean;
  timeframes: string[];
  base_asset?: string;
  quote_asset?: string;
}

export interface Kline {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface IndicatorPoint {
  time: number;   // unix ms
  value: number;
}

export interface IndicatorSeries {
  name: string;
  plot: "on_chart" | "oscillator";
  color: string;
  data: IndicatorPoint[];
}

export interface TradeHistory {
  id: string;
  strategy_id?: string;
  occurred_at: string;
  trade_type: string;
  symbol: string;
  base_asset: string;
  quote_asset: string;
  bought_asset: string;
  sold_asset: string;
  bought_qty: number;
  sold_qty: number;
  exchange_rate: number;
  fee: number;
  fee_asset: string;
  exchange: string;
  market_type: string;
  created_at?: string;
}

// WebSocket message types
export type WsMessageType =
  | "tick"
  | "live_tick"
  | "signal"
  | "execution"
  | "position_update"
  | "balance_update"
  | "pong";

export interface WsMessage<T = Record<string, unknown>> {
  type: WsMessageType;
  ts: number;
  payload: T;
}

export interface TickPayload {
  symbol: string;
  timeframe: string;
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  is_closed?: boolean;
}

export interface SignalPayload {
  strategy_id: string;
  config_id: string;
  execute: string;
  leg_num: string;
  exchange_num: string;
  market_type: string;
  amount: string;
  price: string;
  tp_pct?: string;
  sl_pct?: string;
  ts: string;
}

export interface ExecutionPayload {
  action: "open" | "close";
  strategy_id: string;
  symbol: string;
  side: string;
  price: string;
  size: string;
  position_id: string;
  reason?: string;
  pnl?: string;
  pnl_pct?: string;
}
