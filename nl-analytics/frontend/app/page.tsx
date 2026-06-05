"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  createSession, deleteSession, listSessions, SessionSummary,
} from "@/lib/api";

export default function Home() {
  const router = useRouter();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      setSessions(await listSessions());
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // Warm up the dynamic workspace route so the first navigation isn't
    // blocked by Next.js dev-mode on-demand compilation.
    router.prefetch("/s/placeholder");
  }, [router]);

  async function newSession() {
    setError(null);
    setCreating(true);
    try {
      const s = await createSession("Session " + new Date().toLocaleString());
      router.push(`/s/${s.id}`);
    } catch (e: any) {
      setError(e.message);
      setCreating(false);
    }
  }

  async function remove(id: string) {
    if (!confirm("Delete this session and all its data?")) return;
    await deleteSession(id);
    await refresh();
  }

  return (
    <main className="max-w-3xl mx-auto p-8">
      <header className="mb-8">
        <h1 className="text-3xl font-semibold">NL Analytics</h1>
        <p className="text-slate-600 mt-1">
          Upload CSVs, ask questions in plain English, get tables and charts.
        </p>
      </header>

      <button
        onClick={newSession}
        disabled={creating}
        className="px-4 py-2 bg-slate-900 text-white rounded-md hover:bg-slate-700 disabled:opacity-60 disabled:cursor-not-allowed inline-flex items-center gap-2"
      >
        {creating ? (
          <>
            <span className="inline-block h-3 w-3 rounded-full border-2 border-white border-t-transparent animate-spin" />
            Opening workspace…
          </>
        ) : (
          "+ New session"
        )}
      </button>

      {error && <p className="text-red-600 mt-4">{error}</p>}

      <section className="mt-8">
        <h2 className="text-sm uppercase tracking-wide text-slate-500 mb-3">
          Recent sessions
        </h2>
        {loading ? (
          <p className="text-slate-500">Loading…</p>
        ) : sessions.length === 0 ? (
          <p className="text-slate-500">No sessions yet.</p>
        ) : (
          <ul className="divide-y rounded-md border bg-white">
            {sessions.map((s) => (
              <li key={s.id} className="flex items-center justify-between p-3">
                <button
                  onClick={() => router.push(`/s/${s.id}`)}
                  className="text-left flex-1"
                >
                  <div className="font-medium">{s.name}</div>
                  <div className="text-xs text-slate-500">
                    {s.file_count} files · {s.message_count} messages · updated {s.updated_at}
                  </div>
                </button>
                <button
                  onClick={() => remove(s.id)}
                  className="text-sm text-red-600 hover:underline ml-3"
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
