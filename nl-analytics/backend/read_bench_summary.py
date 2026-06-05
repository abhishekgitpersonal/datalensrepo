import json
from pathlib import Path

p = Path(r"C:\Users\abhishnair\bench_results_all_questions.json")
if not p.exists():
    print("missing")
    raise SystemExit(0)

d = json.loads(p.read_text(encoding="utf-8"))
rows = d.get("results", [])
total_done = len(rows)
ok = sum(1 for r in rows if r.get("ok"))
acc = round((ok * 100.0 / total_done), 2) if total_done else 0.0

print(f"done={total_done}")
print(f"ok={ok}")
print(f"acc={acc}")
if rows:
    last = max(rows, key=lambda r: r.get("idx", 0))
    print(f"last_idx={last.get('idx')}")
    print(f"last_q={last.get('question')}")
    print(f"last_status={last.get('status')}")
    err = last.get("error")
    if err:
        print(f"last_error={err[:220]}")

buckets = {}
for r in rows:
    if r.get("ok"):
        continue
    b = r.get("error_bucket", "unknown")
    buckets[b] = buckets.get(b, 0) + 1
print("fail_buckets=" + json.dumps(buckets, ensure_ascii=True))
