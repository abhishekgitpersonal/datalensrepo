"use client";

import { useState } from "react";
import { deleteTable, SchemaResp } from "@/lib/api";

export default function SchemaPanel({
  sessionId,
  schema,
  error,
  onChanged,
}: {
  sessionId: string;
  schema: SchemaResp | null;
  error: string | null;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState<Record<string, boolean>>({});

  async function remove(table: string) {
    if (!confirm(`Remove table "${table}"?`)) return;
    await deleteTable(sessionId, table);
    onChanged();
  }

  if (error) return <p className="p-3 text-red-600 text-sm">{error}</p>;
  if (!schema) return <p className="p-3 text-slate-500 text-sm">Loading schema…</p>;

  return (
    <div className="p-3 text-sm">
      <h3 className="uppercase text-xs text-slate-500 tracking-wide mb-2">Tables</h3>
      {schema.tables.length === 0 ? (
        <p className="text-slate-500">No tables yet. Upload CSVs above.</p>
      ) : (
        <ul className="space-y-1">
          {schema.tables.map((t) => (
            <li key={t.name} className="border rounded">
              <div className="flex items-center px-2 py-1.5 bg-slate-50">
                <button
                  onClick={() => setOpen((o) => ({ ...o, [t.name]: !o[t.name] }))}
                  className="font-mono font-medium text-left flex-1"
                >
                  {open[t.name] ? "▾" : "▸"} {t.name}
                </button>
                <span className="text-xs text-slate-500 mr-2">
                  {t.row_count.toLocaleString()} rows · {t.col_count} cols
                </span>
                <button
                  onClick={() => remove(t.name)}
                  className="text-xs text-red-600 hover:underline"
                  title="Remove table"
                >
                  ✕
                </button>
              </div>
              {open[t.name] && (
                <ul className="px-3 py-2 text-xs text-slate-700 space-y-0.5">
                  {t.columns.map((c) => (
                    <li key={c.name} className="flex justify-between">
                      <span className="font-mono">{c.name}</span>
                      <span className="text-slate-400">{c.type}</span>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}

      {schema.relationships.length > 0 && (
        <>
          <h3 className="uppercase text-xs text-slate-500 tracking-wide mt-4 mb-2">
            Detected relationships
          </h3>
          <ul className="space-y-1 text-xs">
            {schema.relationships.map((r, i) => (
              <li key={i} className="font-mono text-slate-700">
                {r.from_table}.{r.from_column} → {r.to_table}.{r.to_column}{" "}
                <span className="text-slate-400">({r.confidence})</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
