"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import AnswerCard, { AssistantMessage } from "./AnswerCard";
import { askStream, getHistory, Message } from "@/lib/api";

type ThreadItem =
  | { kind: "user"; id: number | string; question: string }
  | { kind: "assistant"; id: number | string; msg: AssistantMessage };

export default function ChatPanel({
  sessionId,
  hasTables,
}: {
  sessionId: string;
  hasTables: boolean;
}) {
  const [thread, setThread] = useState<ThreadItem[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  // Sync guard: setBusy is async, so two rapid clicks can both see busy===false.
  // A ref flips synchronously and reliably blocks the second submit.
  const inFlightRef = useRef(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const stopRequestedRef = useRef(false);

  // Load history on mount / when session changes
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const hist = await getHistory(sessionId);
        if (cancelled) return;
        setThread(hydrate(hist));
      } catch {
        // ignore — empty thread
      }
    })();
    return () => {
      cancelled = true;
      abortRef.current?.abort();
    };
  }, [sessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [thread]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const q = input.trim();
    if (!q || busy || inFlightRef.current) return;
    inFlightRef.current = true;
    setInput("");
    setBusy(true);

    // optimistic user bubble + placeholder assistant card
    const tempUserId = `u-${Date.now()}`;
    const tempAssistantId = `a-${Date.now()}`;
    setThread((t) => [
      ...t,
      { kind: "user", id: tempUserId, question: q },
      {
        kind: "assistant",
        id: tempAssistantId,
        msg: { pending: true, stage: "starting" },
      },
    ]);

    const ac = new AbortController();
    abortRef.current = ac;
    stopRequestedRef.current = false;
    try {
      for await (const ev of askStream(sessionId, q, ac.signal)) {
        setThread((t) =>
          t.map((item) => {
            if (item.kind !== "assistant" || item.id !== tempAssistantId) return item;
            const m = { ...item.msg };
            switch (ev.event) {
              case "user_message":
                // reconcile real id (no-op for now)
                break;
              case "status":
                m.stage = ev.data.stage;
                break;
              case "sql":
                m.sql = ev.data.sql;
                m.stage = "executing";
                break;
              case "result":
                m.result_preview = ev.data;
                m.stage = "charting";
                break;
              case "chart":
                m.chart_spec = ev.data;
                m.stage = "narrating";
                break;
              case "text_delta":
                m.text = (m.text || "") + ev.data.delta;
                break;
              case "text":
                // Final, grounded narration from the backend. Always overwrites
                // any streamed text so hallucinated tokens get corrected.
                m.text = ev.data.text || "";
                break;
              case "warning":
                m.text = (m.text || "") + `\n\n(${ev.data.message})`;
                break;
              case "error":
                m.error = ev.data.message;
                m.sql = ev.data.sql || m.sql;
                m.pending = false;
                m.stage = null;
                break;
              case "done":
                m.pending = false;
                m.stage = null;
                if (ev.data?.id) m.id = ev.data.id;
                break;
            }
            return { ...item, msg: m };
          }),
        );
        if (ev.event === "done" || ev.event === "error") break;
      }
    } catch (e: any) {
      if (e?.name === "AbortError" || stopRequestedRef.current) {
        setThread((t) =>
          t.map((item) =>
            item.kind === "assistant" && item.id === tempAssistantId
              ? {
                  ...item,
                  msg: {
                    ...item.msg,
                    pending: false,
                    stage: null,
                    text: item.msg.text ? `${item.msg.text}\n\nStopped.` : "Stopped.",
                  },
                }
              : item,
          ),
        );
        return;
      }
      setThread((t) =>
        t.map((item) =>
          item.kind === "assistant" && item.id === tempAssistantId
            ? { ...item, msg: { ...item.msg, error: e.message, pending: false } }
            : item,
        ),
      );
    } finally {
      setBusy(false);
      abortRef.current = null;
      stopRequestedRef.current = false;
      inFlightRef.current = false;
    }
  }

  function stopAsk() {
    if (!abortRef.current) return;
    stopRequestedRef.current = true;
    abortRef.current.abort();
    abortRef.current = null;
    setBusy(false);
    inFlightRef.current = false;
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 overflow-auto p-6 space-y-4">
        {thread.length === 0 && (
          <div className="text-sm text-slate-500 max-w-lg">
            {hasTables
              ? "Ask a question about your data, e.g. \"total revenue per supplier\" or \"orders per month\"."
              : "Upload some CSVs in the sidebar to get started."}
          </div>
        )}
        {thread.map((item) =>
          item.kind === "user" ? (
            <div key={item.id} className="flex justify-end">
              <div className="bg-slate-900 text-white rounded-md px-3 py-2 max-w-[80%] text-sm whitespace-pre-wrap">
                {item.question}
              </div>
            </div>
          ) : (
            <div key={item.id} className="max-w-[90%]">
              <AnswerCard msg={item.msg} />
            </div>
          ),
        )}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={submit} className="border-t bg-white p-3 flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={hasTables ? "Ask a question…" : "Upload CSVs first"}
          className="flex-1 border rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-400"
          disabled={!hasTables}
        />
        <button
          type="submit"
          disabled={!hasTables || busy || !input.trim()}
          className="px-4 py-2 bg-slate-900 text-white rounded-md disabled:opacity-40 text-sm"
        >
          {busy ? "…" : "Ask"}
        </button>
        <button
          type="button"
          onClick={stopAsk}
          disabled={!busy}
          className="px-4 py-2 border border-slate-300 text-slate-700 rounded-md disabled:opacity-40 text-sm"
        >
          Stop
        </button>
      </form>
    </div>
  );
}

function hydrate(history: Message[]): ThreadItem[] {
  const out: ThreadItem[] = [];
  for (const m of history) {
    if (m.role === "user") {
      out.push({ kind: "user", id: m.id, question: m.question || "" });
    } else {
      out.push({
        kind: "assistant",
        id: m.id,
        msg: {
          id: m.id,
          text: m.text,
          sql: m.sql,
          chart_spec: m.chart_spec,
          result_preview: m.result_preview,
          error: m.error,
        },
      });
    }
  }
  return out;
}
