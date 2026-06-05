"""Quick CLI smoke-test that asks a question through the SSE /ask endpoint."""
from __future__ import annotations

import json
import sys

import httpx


def main(session_id: str, question: str, base: str = "http://localhost:8000") -> None:
    url = f"{base}/sessions/{session_id}/ask"
    print(f"POST {url}")
    print(f"Q: {question}\n")
    with httpx.Client(timeout=httpx.Timeout(300.0)) as client:
        with client.stream(
            "POST",
            url,
            json={"question": question},
            headers={"Accept": "text/event-stream"},
        ) as r:
            r.raise_for_status()
            event = None
            for line in r.iter_lines():
                if not line:
                    event = None
                    continue
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    raw = line.split(":", 1)[1].strip()
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        data = raw
                    if event == "text_delta":
                        sys.stdout.write(data.get("delta", "") if isinstance(data, dict) else str(data))
                        sys.stdout.flush()
                    else:
                        print(f"[{event}] {json.dumps(data, default=str)[:400]}")


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else "3d534d4c0d1e"
    q = sys.argv[2] if len(sys.argv) > 2 else "What are the top 5 suppliers by total revenue?"
    main(sid, q)
