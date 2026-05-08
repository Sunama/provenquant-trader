"use client";

import dynamic from "next/dynamic";
import type { StrategyAsset, Position } from "@/lib/types";

const Inner = dynamic(() => import("./StrategyAssetChartInner"), { ssr: false });

interface Props {
  strategyId: string;
  asset: StrategyAsset;
  positions: Position[];
}

export function StrategyAssetChart(props: Props) {
  return <Inner {...props} />;
}
