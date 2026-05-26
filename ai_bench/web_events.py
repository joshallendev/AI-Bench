import json
import re


def parse_bench_progress_line(line: str):
    """Parse one `ai-bench --progress-json` line or selected legacy log lines."""
    if not line:
        return None

    # Prefixed JSON event: AI_BENCH_EVENT {"type":...}
    prefix = "AI_BENCH_EVENT "
    if line.startswith(prefix):
        try:
            return json.loads(line[len(prefix):])
        except json.JSONDecodeError:
            return None

    # Legacy: [3/12] starting pi+ollama+qwen3 timed iter-1
    m = re.search(
        r'\[(\d+)/(\d+)\]\s+starting\s+(\S+)\s+(\w+)\s+iter-(\d+)',
        line,
    )
    if m:
        done = int(m.group(1)) - 1
        total = int(m.group(2))
        return {
            "type": "iteration_start",
            "label": m.group(3),
            "done": done,
            "total": total,
            "phase": m.group(4),
            "iteration": int(m.group(5)),
        }

    # Legacy: Wrote /path/results.json
    m = re.search(r'Wrote\s+(.+?/results\.json)\s*$', line)
    if m:
        return {"type": "results", "results_path": m.group(1)}

    return None


def encode_sse(event: dict, *, event_name: str = "message") -> bytes:
    """Encode a JSON-safe event as SSE bytes."""
    data = json.dumps(event)
    return f"event: {event_name}\ndata: {data}\n\n".encode()
