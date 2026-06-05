from __future__ import annotations

import json
from pathlib import Path

from bench_all_questions import BASE_URL, QUESTIONS, SESSION_ID, ask_once, classify_error

# 1-based indices from the original ordered bank:
# - 5 medium questions: 41-45
# - all hard + very hard questions: 81-120
SELECTED_INDICES = list(range(41, 46)) + list(range(81, 121))

OUT_JSON = Path(r"C:\Users\abhishnair\bench_results_hard_plus5.json")


def selected_questions() -> list[tuple[int, str]]:
    pairs: list[tuple[int, str]] = []
    for idx in SELECTED_INDICES:
        pairs.append((idx, QUESTIONS[idx - 1]))
    return pairs


def main() -> None:
    rows: list[dict] = []

    if OUT_JSON.exists():
        try:
            data = json.loads(OUT_JSON.read_text(encoding="utf-8"))
            existing = data.get("results", [])
            if isinstance(existing, list):
                rows.extend(existing)
        except Exception:
            pass

    done = {r.get("src_idx") for r in rows if isinstance(r, dict)}

    import httpx

    with httpx.Client() as client:
        qs = selected_questions()
        for n, (src_idx, q) in enumerate(qs, start=1):
            if src_idx in done:
                continue

            print(f"[{n:02d}/{len(qs)} | src={src_idx}] {q}", flush=True)
            try:
                res = ask_once(client, q)
            except Exception as e:
                row = {
                    "n": n,
                    "src_idx": src_idx,
                    "question": q,
                    "ok": False,
                    "status": "client_error",
                    "error": str(e),
                    "error_bucket": "other",
                    "sql": None,
                    "elapsed_ms": 0,
                }
            else:
                row = {
                    "n": n,
                    "src_idx": src_idx,
                    "question": res.question,
                    "ok": res.ok,
                    "status": res.status,
                    "error": res.error,
                    "error_bucket": classify_error(res.error),
                    "sql": res.sql,
                    "elapsed_ms": res.elapsed_ms,
                }

            rows.append(row)

            # checkpoint after each question
            OUT_JSON.write_text(
                json.dumps({"summary": {"in_progress": True}, "results": rows}, indent=2),
                encoding="utf-8",
            )

            verdict = "OK" if row["ok"] else f"FAIL ({row['error_bucket']})"
            print(f"    -> {verdict} in {row['elapsed_ms']} ms", flush=True)

    total = len(rows)
    ok = sum(1 for r in rows if r.get("ok"))
    fail = total - ok

    buckets: dict[str, int] = {}
    for r in rows:
        if r.get("ok"):
            continue
        b = r.get("error_bucket", "unknown")
        buckets[b] = buckets.get(b, 0) + 1

    avg_ok = int(sum(r.get("elapsed_ms", 0) for r in rows if r.get("ok")) / max(ok, 1))

    summary = {
        "base_url": BASE_URL,
        "session_id": SESSION_ID,
        "selected_total": total,
        "ok_answers": ok,
        "failed_answers": fail,
        "accuracy_percent": round((ok / max(total, 1)) * 100, 2),
        "avg_elapsed_ms_for_ok": avg_ok,
        "failure_buckets": buckets,
        "source_index_range": {
            "medium_5": [41, 42, 43, 44, 45],
            "hard_and_very_hard": [81, 120],
        },
    }

    OUT_JSON.write_text(json.dumps({"summary": summary, "results": rows}, indent=2), encoding="utf-8")

    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print(f"Saved: {OUT_JSON}")


if __name__ == "__main__":
    main()
