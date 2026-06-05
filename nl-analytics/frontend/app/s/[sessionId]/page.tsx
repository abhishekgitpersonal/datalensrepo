"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import UploadPanel from "@/components/UploadPanel";
import SchemaPanel from "@/components/SchemaPanel";
import ChatPanel from "@/components/ChatPanel";
import DataQualityPanel from "@/components/DataQualityPanel";
import { getSchema, getSession, SchemaResp, SessionSummary } from "@/lib/api";

export default function SessionPage() {
  const params = useParams<{ sessionId: string }>();
  const sessionId = params.sessionId;
  const [session, setSession] = useState<SessionSummary | null>(null);
  const [schema, setSchema] = useState<SchemaResp | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  async function reload() {
    try {
      const [s, sc] = await Promise.all([
        getSession(sessionId),
        getSchema(sessionId).catch((e) => {
          setSchemaError(e.message);
          return { tables: [], relationships: [] } as SchemaResp;
        }),
      ]);
      setSession(s);
      setSchema(sc);
    } catch (e: any) {
      setSchemaError(e.message);
    }
  }

  useEffect(() => {
    reload();
  }, [sessionId, reloadKey]);

  return (
    <div className="h-screen flex flex-col">
      <header className="border-b bg-white px-4 py-2 flex items-center gap-4">
        <Link href="/" className="text-sm text-slate-500 hover:underline">
          ← Sessions
        </Link>
        <h1 className="font-medium truncate">{session?.name ?? sessionId}</h1>
        <span className="text-xs text-slate-500 ml-auto">
          {schema ? `${schema.tables.length} tables` : "…"}
        </span>
      </header>

      <div className="flex-1 grid grid-cols-[320px_1fr] overflow-hidden">
        <aside className="border-r bg-white flex flex-col overflow-hidden">
          <UploadPanel
            sessionId={sessionId}
            onChanged={() => setReloadKey((k) => k + 1)}
          />
          <div className="flex-1 overflow-auto">
            <SchemaPanel
              sessionId={sessionId}
              schema={schema}
              error={schemaError}
              onChanged={() => setReloadKey((k) => k + 1)}
            />
            <DataQualityPanel sessionId={sessionId} reloadKey={reloadKey} />
          </div>
        </aside>

        <main className="overflow-hidden">
          <ChatPanel sessionId={sessionId} hasTables={(schema?.tables.length ?? 0) > 0} />
        </main>
      </div>
    </div>
  );
}
