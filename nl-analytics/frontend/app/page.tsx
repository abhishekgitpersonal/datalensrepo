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
  const [deleting, setDeleting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      setSessions(await listSessions());
      setSelected(new Set());
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

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function toggleSelectAll() {
    setSelected((prev) => {
      if (prev.size === sessions.length) {
        return new Set();
      }
      return new Set(sessions.map((s) => s.id));
    });
  }

  async function removeSelected() {
    if (selected.size === 0) return;
    if (!confirm(`Delete ${selected.size} selected session(s) and all their data?`)) return;

    setDeleting(true);
    setError(null);
    try {
      const ids = Array.from(selected);
      await Promise.all(ids.map((id) => deleteSession(id)));
      await refresh();
    } catch (e: any) {
      setError(e.message || "Failed to delete selected sessions");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <main className="relative isolate min-h-screen overflow-hidden px-6 py-10 sm:px-8 lg:px-10">
      <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="absolute left-[-8rem] top-[-7rem] h-72 w-72 rounded-full bg-cyan-200/50 blur-3xl" />
        <div className="absolute right-[-5rem] top-24 h-80 w-80 rounded-full bg-amber-200/50 blur-3xl" />
        <div className="absolute bottom-[-8rem] left-1/3 h-96 w-96 rounded-full bg-sky-300/25 blur-3xl" />
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(255,255,255,0.95),_rgba(244,248,252,0.88)_42%,_rgba(231,238,245,0.9)_100%)]" />
      </div>

      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
        <section className="rounded-[2rem] border border-white/70 bg-white/75 p-8 shadow-[0_24px_80px_rgba(15,23,42,0.12)] backdrop-blur xl:p-10">
          <div className="max-w-3xl">
              <div className="inline-flex items-center gap-2 rounded-full border border-slate-200/80 bg-white/80 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.28em] text-slate-500 shadow-sm">
                <span className="h-2 w-2 rounded-full bg-emerald-500" />
                Analytics Workspace
              </div>
              <h1 className="mt-6 max-w-2xl text-5xl font-semibold tracking-[-0.04em] text-slate-950 sm:text-6xl">
                Data Lens
              </h1>
              <p className="mt-4 max-w-2xl text-base leading-7 text-slate-600 sm:text-lg">
                Upload CSV files, explore their structure, ask questions in natural language, and get SQL-backed answers with tables, charts, and grounded explanations.
              </p>

              <div className="mt-8 flex flex-wrap items-center gap-3">
                <button
                  onClick={newSession}
                  disabled={creating}
                  className="inline-flex items-center gap-3 rounded-full bg-slate-950 px-6 py-3 text-sm font-medium text-white shadow-[0_16px_40px_rgba(15,23,42,0.24)] transition hover:-translate-y-0.5 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {creating ? (
                    <>
                      <span className="inline-block h-4 w-4 rounded-full border-2 border-white/80 border-t-transparent animate-spin" />
                      Opening workspace…
                    </>
                  ) : (
                    <>
                      <span className="text-base leading-none">+</span>
                      New session
                    </>
                  )}
                </button>
                <div className="rounded-full border border-slate-200 bg-white/80 px-4 py-3 text-sm text-slate-600 shadow-sm">
                  {loading ? "Refreshing sessions..." : `${sessions.length} workspace${sessions.length === 1 ? "" : "s"} available`}
                </div>
              </div>

              {error && (
                <p className="mt-5 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 shadow-sm">
                  {error}
                </p>
              )}
          </div>
        </section>

        <section className="rounded-[2rem] border border-white/70 bg-white/70 p-6 shadow-[0_18px_60px_rgba(15,23,42,0.1)] backdrop-blur sm:p-8">
          <div className="flex flex-col gap-4 border-b border-slate-200/80 pb-5 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Session Library</p>
              <h2 className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-slate-950">Recent sessions</h2>
            </div>
            {sessions.length > 0 && (
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <button
                  onClick={toggleSelectAll}
                  className="rounded-full border border-slate-200 bg-white px-4 py-2 text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
                >
                  {selected.size === sessions.length ? "Clear all" : "Select all"}
                </button>
                <button
                  onClick={removeSelected}
                  disabled={selected.size === 0 || deleting}
                  className="rounded-full border border-red-200 bg-red-50 px-4 py-2 text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {deleting ? "Deleting..." : `Delete selected (${selected.size})`}
                </button>
              </div>
            )}
          </div>

          <div className="mt-6">
            {loading ? (
              <div className="rounded-[1.5rem] border border-dashed border-slate-300 bg-white/70 px-6 py-10 text-center text-slate-500">
                Loading sessions…
              </div>
            ) : sessions.length === 0 ? (
              <div className="rounded-[1.5rem] border border-dashed border-slate-300 bg-white/70 px-6 py-12 text-center">
                <p className="text-lg font-medium text-slate-900">No sessions yet.</p>
                <p className="mt-2 text-sm text-slate-500">Create a new workspace to start exploring your datasets.</p>
              </div>
            ) : (
              <ul className="grid gap-4">
                {sessions.map((s) => (
                  <li
                    key={s.id}
                    className="group flex flex-col gap-4 rounded-[1.5rem] border border-slate-200/80 bg-white/85 p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-[0_18px_40px_rgba(15,23,42,0.1)] sm:flex-row sm:items-center"
                  >
                    <label className="inline-flex items-center self-start sm:self-center">
                      <input
                        type="checkbox"
                        checked={selected.has(s.id)}
                        onChange={() => toggleSelect(s.id)}
                        className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-400"
                        aria-label={`Select ${s.name}`}
                      />
                    </label>

                    <button
                      onClick={() => router.push(`/s/${s.id}`)}
                      className="flex-1 text-left"
                    >
                      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                        <div>
                          <div className="text-lg font-semibold tracking-[-0.02em] text-slate-950 transition group-hover:text-sky-900">
                            {s.name}
                          </div>
                          <div className="mt-1 text-sm text-slate-500">Updated {s.updated_at}</div>
                        </div>
                        <div className="flex flex-wrap gap-2 text-xs font-medium text-slate-600">
                          <span className="rounded-full bg-slate-100 px-3 py-1">{s.file_count} files</span>
                          <span className="rounded-full bg-sky-50 px-3 py-1 text-sky-700">{s.message_count} messages</span>
                        </div>
                      </div>
                    </button>

                    <button
                      onClick={() => remove(s.id)}
                      className="inline-flex items-center self-start rounded-full px-4 py-2 text-sm font-medium text-red-600 transition hover:bg-red-50 sm:self-center"
                    >
                      Delete
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
