"use client";

import type { WsMessage, WsMessageType } from "@/lib/types";

type Handler<T = unknown> = (payload: T) => void;

class WebSocketClient {
  private ws: WebSocket | null = null;
  private url = "";
  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private subscribers = new Map<WsMessageType, Set<Handler>>();
  private tickSubscriptions = new Set<string>();   // "slug:timeframe"
  private shouldReconnect = true;

  connect(url: string) {
    this.url = url;
    this.shouldReconnect = true;
    this._open();
  }

  disconnect() {
    this.shouldReconnect = false;
    this.ws?.close();
    this.ws = null;
  }

  subscribe<T>(type: WsMessageType, handler: Handler<T>): () => void {
    if (!this.subscribers.has(type)) {
      this.subscribers.set(type, new Set());
    }
    this.subscribers.get(type)!.add(handler as Handler);
    return () => this.subscribers.get(type)?.delete(handler as Handler);
  }

  subscribeTick(assetSlug: string, timeframe: string) {
    const key = `${assetSlug}:${timeframe}`;
    if (this.tickSubscriptions.has(key)) return;
    this.tickSubscriptions.add(key);
    this._send({ type: "subscribe_ticks", payload: { asset_slug: assetSlug, timeframe } });
  }

  unsubscribeTick(assetSlug: string, timeframe: string) {
    const key = `${assetSlug}:${timeframe}`;
    this.tickSubscriptions.delete(key);
    this._send({ type: "unsubscribe_ticks", payload: { asset_slug: assetSlug, timeframe } });
  }

  ping() {
    this._send({ type: "ping", payload: {} });
  }

  get connected() {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  private _open() {
    if (!this.url) return;
    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      this.reconnectDelay = 1000;
      // Re-subscribe ticks on reconnect
      for (const key of this.tickSubscriptions) {
        const [asset_slug, timeframe] = key.split(":");
        this._send({ type: "subscribe_ticks", payload: { asset_slug, timeframe } });
      }
    };

    this.ws.onmessage = (event) => {
      try {
        const msg: WsMessage = JSON.parse(event.data);
        const handlers = this.subscribers.get(msg.type);
        handlers?.forEach((h) => h(msg.payload));
      } catch {}
    };

    this.ws.onclose = () => {
      if (this.shouldReconnect) {
        setTimeout(() => this._open(), this.reconnectDelay);
        this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
      }
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  private _send(msg: unknown) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }
}

export const wsClient = new WebSocketClient();
