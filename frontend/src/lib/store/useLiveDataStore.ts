"use client";

import { create } from "zustand";
import type { SignalPayload, ExecutionPayload, TickPayload } from "@/lib/types";

const MAX_ITEMS = 50;

interface LiveDataState {
  recentSignals: SignalPayload[];
  recentExecutions: ExecutionPayload[];
  lastBalance: number | null;
  latestTicks: Record<string, TickPayload>;  // "slug:timeframe" → latest tick

  addSignal: (s: SignalPayload) => void;
  addExecution: (e: ExecutionPayload) => void;
  setBalance: (b: number) => void;
  updateTick: (t: TickPayload) => void;
}

export const useLiveDataStore = create<LiveDataState>((set) => ({
  recentSignals: [],
  recentExecutions: [],
  lastBalance: null,
  latestTicks: {},

  addSignal: (s) =>
    set((state) => ({
      recentSignals: [s, ...state.recentSignals].slice(0, MAX_ITEMS),
    })),

  addExecution: (e) =>
    set((state) => ({
      recentExecutions: [e, ...state.recentExecutions].slice(0, MAX_ITEMS),
    })),

  setBalance: (b) => set({ lastBalance: b }),

  updateTick: (t) =>
    set((state) => ({
      latestTicks: {
        ...state.latestTicks,
        [`${t.asset_slug}:${t.timeframe}`]: t,
      },
    })),
}));
