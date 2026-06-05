"use client";

import { useState } from "react";
import ChartRenderer from "./ChartRenderer";
import ResultTable from "./ResultTable";
import type { ChartSpec, ResultPayload } from "@/lib/api";

export type AssistantMessage = {
  id?: number;
  text?: string | null;
  sql?: string | null;
  chart_spec?: ChartSpec | null;
  result_preview?: ResultPayload | null;
  error?: string | null;
  pending?: boolean;
  stage?: string | null;
};

const TABS = ["Answer", "Chart", "Table", "SQL"] as const;
type Tab = (typeof TABS)[number];

export default function AnswerCard({ msg }: { msg: AssistantMessage }) {
  const [tab, setTab] = useState<Tab>("Answer");

  if (msg.error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-md p-3 text-sm">
        <div className="font-medium text-red-800">Error</div>
        <div className="text-red-700 whitespace-pre-wrap">{msg.error}</div>
        {msg.sql && (
          <pre className="mt-2 text-xs bg-white p-2 rounded border overflow-auto">
            {msg.sql}
          </pre>
        )}
      </div>
    );
  }

  const hasChart = !!msg.chart_spec;
  const hasTable = !!msg.result_preview;
  const hasSql = !!msg.sql;

  return (
    <div className="bg-white border rounded-md">
      <div className="flex gap-1 border-b px-2 pt-2 text-xs">
        {TABS.map((t) => {
          const disabled =
            (t === "Chart" && !hasChart) ||
            (t === "Table" && !hasTable) ||
            (t === "SQL" && !hasSql);
          return (
            <button
              key={t}
              onClick={() => !disabled && setTab(t)}
              disabled={disabled}
              className={
                "px-2 py-1 rounded-t " +
                (tab === t
                  ? "bg-slate-100 font-medium"
                  : disabled
                    ? "text-slate-300 cursor-not-allowed"
                    : "text-slate-600 hover:bg-slate-50")
              }
            >
              {t}
            </button>
          );
        })}
        {msg.pending && (
          <span className="ml-auto text-[10px] text-slate-400 self-center pr-1">
            {msg.stage ? `${msg.stage}…` : "thinking…"}
          </span>
        )}
      </div>

      <div className="p-3">
        {tab === "Answer" && (
          <div className="whitespace-pre-wrap text-sm leading-relaxed">
            {msg.text || (msg.pending ? <span className="text-slate-400">…</span> : <span className="text-slate-500">(no narration)</span>)}
          </div>
        )}
        {tab === "Chart" && hasChart && (
          <div style={{ height: 400 }}>
            <ChartRenderer spec={msg.chart_spec!} />
          </div>
        )}
        {tab === "Table" && hasTable && <ResultTable data={msg.result_preview!} />}
        {tab === "SQL" && hasSql && (
          <pre className="text-xs bg-slate-900 text-slate-100 p-3 rounded overflow-auto">
            {msg.sql}
          </pre>
        )}
      </div>
    </div>
  );
}
