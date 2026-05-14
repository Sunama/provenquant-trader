"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { wsClient } from "@/lib/ws/WebSocketClient";
import { useLiveDataStore } from "@/lib/store/useLiveDataStore";
import type { SignalPayload, ExecutionPayload, TickPayload } from "@/lib/types";

interface WsContextValue {
  connected: boolean;
}

const WsContext = createContext<WsContextValue>({ connected: false });

export function WebSocketProvider({ children }: { children: React.ReactNode }) {
  const [connected, setConnected] = useState(false);
  const { addSignal, addExecution, setBalance, updateTick, updateLivePrice } = useLiveDataStore();

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const wsUrl = process.env.NEXT_PUBLIC_WS_URL || `${proto}://${window.location.hostname}:8001/ws`;
    wsClient.connect(wsUrl);

    const unsubSignal = wsClient.subscribe<SignalPayload>("signal", (payload) => {
      addSignal(payload);
      setConnected(true);
    });

    const unsubExec = wsClient.subscribe<ExecutionPayload>("execution", (payload) => {
      addExecution(payload);
    });

    const unsubBalance = wsClient.subscribe<{ balance: string }>("balance_update", (payload) => {
      setBalance(parseFloat(payload.balance));
    });

    const unsubTick = wsClient.subscribe<TickPayload>("tick", (payload) => {
      updateTick(payload);
      updateLivePrice(payload);
      setConnected(true);
    });

    const unsubLiveTick = wsClient.subscribe<TickPayload>("live_tick", (payload) => {
      updateLivePrice(payload);
    });

    const unsubPong = wsClient.subscribe("pong", () => {
      setConnected(true);
    });

    const pingInterval = setInterval(() => {
      wsClient.ping();
    }, 25000);

    return () => {
      unsubSignal();
      unsubExec();
      unsubBalance();
      unsubTick();
      unsubLiveTick();
      unsubPong();
      clearInterval(pingInterval);
      wsClient.disconnect();
    };
  }, [addSignal, addExecution, setBalance, updateTick, updateLivePrice]);

  return <WsContext.Provider value={{ connected }}>{children}</WsContext.Provider>;
}

export const useWsConnection = () => useContext(WsContext);
