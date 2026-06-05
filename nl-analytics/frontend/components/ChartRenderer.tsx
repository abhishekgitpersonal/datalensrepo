"use client";

import dynamic from "next/dynamic";
import type { ChartSpec } from "@/lib/api";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

export default function ChartRenderer({ spec }: { spec: ChartSpec }) {
  return (
    <Plot
      data={spec.data as any}
      layout={{ ...spec.layout, autosize: true } as any}
      useResizeHandler
      style={{ width: "100%", height: "100%" }}
      config={{ displaylogo: false, responsive: true }}
    />
  );
}
