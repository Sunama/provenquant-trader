"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type Time,
} from "lightweight-charts";
import { wsClient } from "@/lib/ws/WebSocketClient";
import { marketData } from "@/lib/api";
import type { TickPayload } from "@/lib/types";

interface Props {
  assetSlug: string;
  timeframe: string;
}

export default function LivePriceChartInner({ assetSlug, timeframe }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#888",
      },
      grid: {
        vertLines: { color: "#f0f0f0" },
        horzLines: { color: "#f0f0f0" },
      },
      width: containerRef.current.clientWidth,
      height: 300,
    });

    const series = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    chartRef.current = chart;
    seriesRef.current = series;

    // Load historical klines
    marketData
      .klines({ asset_slug: assetSlug, timeframe, limit: 200 })
      .then((klines) => {
        const data: CandlestickData[] = klines.map((k) => ({
          time: (k.time / 1000) as Time,
          open: k.open,
          high: k.high,
          low: k.low,
          close: k.close,
        }));
        series.setData(data);
        chart.timeScale().fitContent();
      })
      .catch(() => {});

    // Subscribe to live ticks
    wsClient.subscribeTick(assetSlug, timeframe);
    const unsub = wsClient.subscribe<TickPayload>("tick", (payload) => {
      if (payload.asset_slug !== assetSlug || payload.timeframe !== timeframe) return;
      series.update({
        time: (payload.time / 1000) as Time,
        open: payload.open,
        high: payload.high,
        low: payload.low,
        close: payload.close,
      });
    });

    const observer = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    observer.observe(containerRef.current);

    return () => {
      unsub();
      wsClient.unsubscribeTick(assetSlug, timeframe);
      observer.disconnect();
      chart.remove();
    };
  }, [assetSlug, timeframe]);

  return <div ref={containerRef} className="h-[300px] w-full" />;
}
