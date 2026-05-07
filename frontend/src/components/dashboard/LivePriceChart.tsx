"use client";

import dynamic from "next/dynamic";

const LivePriceChartInner = dynamic(() => import("./LivePriceChartInner"), { ssr: false });

export function LivePriceChart({ assetSlug, timeframe }: { assetSlug: string; timeframe: string }) {
  return <LivePriceChartInner assetSlug={assetSlug} timeframe={timeframe} />;
}
