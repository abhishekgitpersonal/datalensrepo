"use client";

import { useCallback, useRef, useState } from "react";
import { uploadFiles } from "@/lib/api";

export default function UploadPanel({
  sessionId,
  onChanged,
}: {
  sessionId: string;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const handleFiles = useCallback(
    async (fileList: FileList | File[]) => {
      const all = Array.from(fileList);
      const csvs = all.filter((f) => f.name.toLowerCase().endsWith(".csv"));
      const rejected = all.length - csvs.length;
      if (!csvs.length) {
        setMsg(
          rejected
            ? `No CSV files selected (${rejected} non-CSV file${rejected === 1 ? "" : "s"} ignored)`
            : "No files selected",
        );
        return;
      }
      setBusy(true);
      setMsg(rejected ? `Uploading ${csvs.length}, ignored ${rejected} non-CSV…` : `Uploading ${csvs.length}…`);
      try {
        const res = await uploadFiles(sessionId, csvs);
        const u = res.uploaded.length;
        const s = res.skipped.length;
        setMsg(
          `Uploaded ${u} file${u === 1 ? "" : "s"}` +
            (s
              ? `, skipped ${s} (${res.skipped.map((x: any) => x.reason || x.name).join("; ")})`
              : "") +
            (rejected ? `, ignored ${rejected} non-CSV` : ""),
        );
        onChanged();
      } catch (e: any) {
        setMsg(`Error: ${e.message}`);
      } finally {
        setBusy(false);
      }
    },
    [sessionId, onChanged],
  );

  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length) handleFiles(files);
    // Reset so selecting the same file twice still fires change.
    e.target.value = "";
  };

  const onDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (!busy) setDragActive(true);
  };

  const onDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (busy) return;
    const files = e.dataTransfer?.files;
    if (files && files.length) handleFiles(files);
  };

  const openPicker = () => {
    if (busy) return;
    inputRef.current?.click();
  };

  return (
    <div className="p-3 border-b">
      <div
        onClick={openPicker}
        onDragOver={onDragOver}
        onDragEnter={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            openPicker();
          }
        }}
        className={
          "border-2 border-dashed rounded-md p-4 text-center text-sm select-none " +
          (dragActive
            ? "border-blue-500 bg-blue-50"
            : "border-slate-300 hover:bg-slate-50") +
          (busy ? " opacity-60 cursor-not-allowed" : " cursor-pointer")
        }
      >
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv,application/vnd.ms-excel"
          multiple
          onChange={onInputChange}
          className="hidden"
        />
        {busy ? (
          <span>Uploading…</span>
        ) : dragActive ? (
          <span>Drop CSV files here</span>
        ) : (
          <span>Drag CSV files here, or click to choose</span>
        )}
      </div>
      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={openPicker}
          disabled={busy}
          className="text-xs px-2 py-1 border rounded hover:bg-slate-50 disabled:opacity-60"
        >
          Choose files…
        </button>
        {msg && <p className="text-xs text-slate-600">{msg}</p>}
      </div>
    </div>
  );
}
