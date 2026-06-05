"use client";

import { useEffect, useState } from "react";
import { DataQualityIssue, DataQualityReport, getDataQuality } from "@/lib/api";

const SEV_STYLES: Record<string, string> = {
  ERROR: "bg-red-100 text-red-700 border-red-200",
  WARN: "bg-amber-100 text-amber-800 border-amber-200",
  INFO: "bg-slate-100 text-slate-600 border-slate-200",
};

export default function DataQualityPanel({
  sessionId,
  reloadKey,
}: {
  sessionId: string;
  reloadKey: number;
}) {
  const [report, setReport] = useState<DataQualityReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await getDataQuality(sessionId);
        if (!cancelled) setReport(r);
      } catch (e: any) {
        if (!cancelled) setError(e.message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, reloadKey]);

  if (error) return <p className="p-3 text-red-600 text-sm">{error}</p>;
  if (!report) return null;
  const { summary, issues } = report;

  return (
    <div className="p-3 text-sm border-t">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between"
      >
        <h3 className="uppercase text-xs text-slate-500 tracking-wide">
          Data quality
        </h3>
        <span className="flex gap-1 text-xs">
          {summary.errors > 0 && (
            <span className="px-1.5 rounded border bg-red-100 text-red-700 border-red-200">
              {summary.errors} err
            </span>
          )}
          {summary.warnings > 0 && (
            <span className="px-1.5 rounded border bg-amber-100 text-amber-800 border-amber-200">
              {summary.warnings} warn
            </span>
          )}
          {summary.infos > 0 && (
            <span className="px-1.5 rounded border bg-slate-100 text-slate-600 border-slate-200">
              {summary.infos} info
            </span>
          )}
          {issues.length === 0 && (
            <span className="px-1.5 rounded border bg-emerald-100 text-emerald-700 border-emerald-200">
              all clean
            </span>
          )}
        </span>
      </button>

      {open && issues.length > 0 && (
        <ul className="mt-2 space-y-1 max-h-72 overflow-auto pr-1">
          {issues.map((i, idx) => (
            <IssueRow key={idx} issue={i} />
          ))}
        </ul>
      )}
    </div>
  );
}

function IssueRow({ issue }: { issue: DataQualityIssue }) {
  return (
    <li className="border rounded px-2 py-1.5">
      <div className="flex items-center gap-2">
        <span
          className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${
            SEV_STYLES[issue.severity] || ""
          }`}
        >
          {issue.severity}
        </span>
        <span className="font-mono text-xs text-slate-700">
          {issue.table}
          {issue.column ? `.${issue.column}` : ""}
        </span>
        <span className="ml-auto text-xs text-slate-400">
          {issue.count.toLocaleString()}
        </span>
      </div>
      <p className="mt-0.5 text-xs text-slate-600">{issue.message}</p>
      {issue.sample && issue.sample.length > 0 && (
        <p className="mt-0.5 text-[11px] text-slate-400 font-mono truncate">
          e.g. {issue.sample.slice(0, 3).map(String).join(", ")}
        </p>
      )}
    </li>
  );
}
