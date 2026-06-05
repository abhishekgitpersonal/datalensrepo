export const API =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type SessionSummary = {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  file_count: number;
  message_count: number;
};

export type ColumnInfo = { name: string; type: string };
export type TableInfo = {
  name: string;
  row_count: number;
  col_count: number;
  columns: ColumnInfo[];
  sample_rows: Record<string, unknown>[];
};
export type Relationship = {
  from_table: string;
  from_column: string;
  to_table: string;
  to_column: string;
  confidence: number;
};
export type SchemaResp = { tables: TableInfo[]; relationships: Relationship[] };

export type ResultPayload = {
  columns: string[];
  rows: unknown[][];
  total_rows: number;
};

export type ChartSpec = { data: unknown[]; layout: Record<string, unknown> };

export type Message = {
  id: number;
  role: "user" | "assistant";
  question?: string | null;
  sql?: string | null;
  text?: string | null;
  chart_spec?: ChartSpec | null;
  result_preview?: ResultPayload | null;
  row_count?: number | null;
  error?: string | null;
  created_at: string;
};

export async function listSessions(): Promise<SessionSummary[]> {
  const r = await fetch(`${API}/sessions`, { cache: "no-store" });
  if (!r.ok) throw new Error("Failed to list sessions");
  return r.json();
}

export async function createSession(name = "New session"): Promise<SessionSummary> {
  const r = await fetch(`${API}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!r.ok) throw new Error("Failed to create session");
  return r.json();
}

export async function deleteSession(id: string): Promise<void> {
  const r = await fetch(`${API}/sessions/${id}`, { method: "DELETE" });
  if (!r.ok && r.status !== 204) throw new Error("Failed to delete session");
}

export async function getSession(id: string): Promise<SessionSummary> {
  const r = await fetch(`${API}/sessions/${id}`, { cache: "no-store" });
  if (!r.ok) throw new Error("Session not found");
  return r.json();
}

export async function getSchema(id: string): Promise<SchemaResp> {
  const r = await fetch(`${API}/sessions/${id}/schema`, { cache: "no-store" });
  if (!r.ok) throw new Error("Failed to load schema");
  return r.json();
}

export async function getHistory(id: string): Promise<Message[]> {
  const r = await fetch(`${API}/sessions/${id}/history`, { cache: "no-store" });
  if (!r.ok) throw new Error("Failed to load history");
  return r.json();
}

export async function uploadFiles(
  id: string,
  files: File[],
): Promise<{ uploaded: any[]; skipped: any[] }> {
  const fd = new FormData();
  for (const f of files) fd.append("files", f, f.name);
  const r = await fetch(`${API}/sessions/${id}/upload`, {
    method: "POST",
    body: fd,
  });
  if (!r.ok) {
    const body = await r.text().catch(() => "");
    throw new Error(`Upload failed (${r.status}): ${body || r.statusText}`);
  }
  return r.json();
}

export async function deleteTable(id: string, table: string): Promise<void> {
  const r = await fetch(`${API}/sessions/${id}/files/${table}`, {
    method: "DELETE",
  });
  if (!r.ok) throw new Error("Failed to delete table");
}

export type DataQualityIssue = {
  table: string;
  column: string | null;
  issue_type: string;
  severity: "ERROR" | "WARN" | "INFO";
  count: number;
  message: string;
  sample: unknown[] | null;
};

export type DataQualityReport = {
  summary: { errors: number; warnings: number; infos: number };
  issues: DataQualityIssue[];
};

export async function getDataQuality(id: string): Promise<DataQualityReport> {
  const r = await fetch(`${API}/sessions/${id}/data_quality`, { cache: "no-store" });
  if (!r.ok) throw new Error("Failed to load data quality report");
  return r.json();
}

/** SSE-style streaming for /ask. Parses `event:` and `data:` lines. */
export async function* askStream(
  sessionId: string,
  question: string,
  signal?: AbortSignal,
): AsyncGenerator<{ event: string; data: any }, void, unknown> {
  const res = await fetch(`${API}/sessions/${sessionId}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ question }),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`Ask failed: ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  // SSE frames may be separated by either "\n\n" or "\r\n\r\n" depending on
  // the server (sse_starlette uses CRLF). Match both.
  const FRAME_SEP = /\r?\n\r?\n/;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let m: RegExpExecArray | null;
    while ((m = FRAME_SEP.exec(buf)) !== null) {
      const frame = buf.slice(0, m.index);
      buf = buf.slice(m.index + m[0].length);
      const ev = parseFrame(frame);
      if (ev) yield ev;
    }
  }
}

function parseFrame(frame: string): { event: string; data: any } | null {
  let event = "message";
  const dataLines: string[] = [];
  // Lines may end with \r — split on \r?\n.
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return null;
  const raw = dataLines.join("\n");
  try {
    return { event, data: JSON.parse(raw) };
  } catch {
    return { event, data: raw };
  }
}
