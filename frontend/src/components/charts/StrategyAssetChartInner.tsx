"use client";

import { useEffect, useRef, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  createChart,
  ColorType,
  type Time,
  type IChartApi,
  type SeriesMarker,
  type ISeriesApi,
  type CandlestickData,
} from "lightweight-charts";
import { marketData, strategies } from "@/lib/api";
import { wsClient } from "@/lib/ws/WebSocketClient";
import type { StrategyAsset, Position, TickPayload, Kline } from "@/lib/types";

const INITIAL_LIMIT = 1000;
const PAGE_LIMIT = 500;
const LOAD_THRESHOLD = 10; // bars from left edge before triggering a fetch

interface Props {
  strategyId: string;
  asset: StrategyAsset;
  positions: Position[];
}

export default function StrategyAssetChartInner({ strategyId, asset, positions }: Props) {
  const mainRef = useRef<HTMLDivElement>(null);
  const oscRefs = useRef<(HTMLDivElement | null)[]>([]);

  const { data: klines } = useQuery({
    queryKey: ["klines", asset.symbol, asset.timeframe],
    queryFn: () => marketData.klines({ symbol: asset.symbol, timeframe: asset.timeframe, limit: INITIAL_LIMIT }),
  });

  const { data: indicatorSeries } = useQuery({
    queryKey: ["indicators", strategyId, asset.symbol, asset.timeframe],
    queryFn: () => strategies.indicators(strategyId, { symbol: asset.symbol, timeframe: asset.timeframe }),
  });

  const oscillators = (indicatorSeries ?? []).filter((s) => s.plot === "oscillator");
  const onChartIndicators = (indicatorSeries ?? []).filter((s) => s.plot === "on_chart");

  // Refs used inside the scroll handler to avoid stale closures
  const candlesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const allBarsRef = useRef<Kline[]>([]);
  const isFetchingRef = useRef(false);
  const hasMoreRef = useRef(true);
  const tzOffsetRef = useRef(0);

  const buildMarkers = useCallback(
    (toLocal: (ms: number) => Time): SeriesMarker<Time>[] => {
      const assetPositions = positions.filter((p) => p.symbol === asset.symbol);
      return assetPositions
        .flatMap((p) => {
          const ms: SeriesMarker<Time>[] = [
            {
              time: toLocal(new Date(p.entry_time!).getTime()),
              position: p.side === "long" ? "belowBar" : "aboveBar",
              color: p.side === "long" ? "#22c55e" : "#ef4444",
              shape: p.side === "long" ? "arrowUp" : "arrowDown",
              text: p.side.toUpperCase(),
            },
          ];
          if (p.exit_time && p.exit_price) {
            ms.push({
              time: toLocal(new Date(p.exit_time).getTime()),
              position: p.side === "long" ? "aboveBar" : "belowBar",
              color: "#9ca3af",
              shape: p.side === "long" ? "arrowDown" : "arrowUp",
              text: `✕ ${p.exit_reason ?? ""}`.trim(),
            });
          }
          return ms;
        })
        .sort((a, b) => (a.time as number) - (b.time as number));
    },
    [positions, asset.symbol]
  );

  useEffect(() => {
    if (!mainRef.current || !klines) return;

    tzOffsetRef.current = -new Date().getTimezoneOffset() * 60;
    const toLocal = (ms: number): Time => (Math.floor(ms / 1000) + tzOffsetRef.current) as Time;

    allBarsRef.current = [...klines];
    hasMoreRef.current = klines.length === INITIAL_LIMIT;

    // ── Main candlestick chart ────────────────────────────────
    const chart = createChart(mainRef.current, {
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#888" },
      grid: { vertLines: { color: "#e5e7eb" }, horzLines: { color: "#e5e7eb" } },
      width: mainRef.current.clientWidth,
      height: 300,
      rightPriceScale: { borderColor: "#e5e7eb", autoScale: true },
      timeScale: { borderColor: "#e5e7eb", timeVisible: true, secondsVisible: false },
    });

    const candles = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });
    candlesRef.current = candles;

    candles.setData(
      klines.map((k) => ({ time: toLocal(k.time), open: k.open, high: k.high, low: k.low, close: k.close }))
    );

    // On-chart indicator overlays (e.g. EMA)
    for (const ind of onChartIndicators) {
      const line = chart.addLineSeries({ color: ind.color, lineWidth: 1 });
      line.setData(ind.data.map((p) => ({ time: toLocal(p.time), value: p.value })));
    }

    candles.setMarkers(buildMarkers(toLocal));
    chart.timeScale().fitContent();

    // ── Lazy-load older bars on scroll ────────────────────────
    const handleRangeChange = () => {
      if (isFetchingRef.current || !hasMoreRef.current) return;
      const range = chart.timeScale().getVisibleLogicalRange();
      if (!range || range.from > LOAD_THRESHOLD) return;

      isFetchingRef.current = true;
      const oldest = allBarsRef.current[0];
      if (!oldest) { isFetchingRef.current = false; return; }

      marketData
        .klines({
          symbol: asset.symbol,
          timeframe: asset.timeframe,
          limit: PAGE_LIMIT,
          end_time: oldest.time, // exclusive upper bound = oldest candle we already have
        })
        .then((older) => {
          if (!older || older.length === 0) {
            hasMoreRef.current = false;
            return;
          }
          hasMoreRef.current = older.length === PAGE_LIMIT;

          // Merge: older bars come before existing ones
          allBarsRef.current = [...older, ...allBarsRef.current];

          const merged: CandlestickData[] = allBarsRef.current.map((k) => ({
            time: toLocal(k.time),
            open: k.open,
            high: k.high,
            low: k.low,
            close: k.close,
          }));

          const currentRange = chart.timeScale().getVisibleLogicalRange();
          candles.setData(merged);
          candles.setMarkers(buildMarkers(toLocal));

          // Preserve scroll position so the view doesn't jump
          if (currentRange) {
            const shift = older.length;
            chart.timeScale().setVisibleLogicalRange({
              from: currentRange.from + shift,
              to: currentRange.to + shift,
            });
          }
        })
        .finally(() => {
          isFetchingRef.current = false;
        });
    };

    chart.timeScale().subscribeVisibleLogicalRangeChange(handleRangeChange);

    // Live ticks
    wsClient.subscribeTick(asset.symbol, asset.timeframe);
    const unsubTick = wsClient.subscribe<TickPayload>("tick", (payload) => {
      if (payload.symbol !== asset.symbol || payload.timeframe !== asset.timeframe) return;
      candles.update({ time: toLocal(payload.time), open: payload.open, high: payload.high, low: payload.low, close: payload.close });
    });
    const unsubLive = wsClient.subscribe<TickPayload>("live_tick", (payload) => {
      if (payload.symbol !== asset.symbol || payload.timeframe !== asset.timeframe) return;
      candles.update({ time: toLocal(payload.time), open: payload.open, high: payload.high, low: payload.low, close: payload.close });
    });

    // ── Oscillator sub-charts ─────────────────────────────────
    const oscCharts: IChartApi[] = [];
    oscillators.forEach((ind, i) => {
      const container = oscRefs.current[i];
      if (!container) return;
      const oscChart = createChart(container, {
        layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#888" },
        grid: { vertLines: { color: "#f0f0f0" }, horzLines: { color: "#f0f0f0" } },
        width: container.clientWidth,
        height: 120,
        rightPriceScale: { autoScale: true },
        timeScale: { visible: false },
      });
      const line = oscChart.addLineSeries({ color: ind.color, lineWidth: 1 });
      line.setData(ind.data.map((p) => ({ time: toLocal(p.time), value: p.value })));
      oscChart.timeScale().fitContent();
      oscCharts.push(oscChart);
    });

    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) oscCharts.forEach((c) => c.timeScale().setVisibleLogicalRange(range));
    });

    const observer = new ResizeObserver(() => {
      if (mainRef.current) chart.applyOptions({ width: mainRef.current.clientWidth });
      oscCharts.forEach((c, i) => {
        const el = oscRefs.current[i];
        if (el) c.applyOptions({ width: el.clientWidth });
      });
    });
    observer.observe(mainRef.current);

    return () => {
      unsubTick();
      unsubLive();
      wsClient.unsubscribeTick(asset.symbol, asset.timeframe);
      observer.disconnect();
      chart.remove();
      oscCharts.forEach((c) => c.remove());
      candlesRef.current = null;
    };
  }, [klines, indicatorSeries, positions, asset.symbol, asset.timeframe, strategyId, onChartIndicators, oscillators, buildMarkers]);

  if (!klines) {
    return <div className="h-[300px] w-full flex items-center justify-center text-sm text-muted-foreground">Loading chart…</div>;
  }

  return (
    <div>
      <div ref={mainRef} className="h-[300px] w-full" />
      {oscillators.map((ind, i) => (
        <div key={i}>
          <p className="text-xs text-muted-foreground px-1 mt-2 mb-0.5">{ind.name}</p>
          <div ref={(el) => { oscRefs.current[i] = el; }} className="h-[120px] w-full" />
        </div>
      ))}
    </div>
  );
}
