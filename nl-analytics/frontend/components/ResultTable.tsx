"use client";

import { ResultPayload } from "@/lib/api";

export default function ResultTable({ data }: { data: ResultPayload }) {
  if (!data.rows.length) {
    return <p className="text-sm text-slate-500">No rows.</p>;
  }
  return (
    <div className="overflow-auto max-h-[400px] border rounded">
      <table className="text-xs w-full">
        <thead className="bg-slate-100 sticky top-0">
          <tr>
            {data.columns.map((c) => (
              <th key={c} className="text-left px-2 py-1 font-medium border-b">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, i) => (
            <tr key={i} className={i % 2 ? "bg-slate-50" : ""}>
              {row.map((v, j) => (
                <td key={j} className="px-2 py-1 border-b font-mono">
                  {v === null || v === undefined ? (
                    <span className="text-slate-400">NULL</span>
                  ) : (
                    String(v)
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="text-[10px] text-slate-500 px-2 py-1">
        Showing {data.rows.length} of {data.total_rows} rows
      </div>
    </div>
  );
}
