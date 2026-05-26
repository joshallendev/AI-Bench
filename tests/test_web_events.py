import json

from ai_bench.web_events import encode_sse, parse_bench_progress_line


def test_parse_bench_progress_line_reads_prefixed_json_events():
    event = parse_bench_progress_line(
        'AI_BENCH_EVENT {"type":"iteration_start","label":"pi+ollama+qwen3","done":2,"total":9}'
    )

    assert event == {
        "type": "iteration_start",
        "label": "pi+ollama+qwen3",
        "done": 2,
        "total": 9,
    }


def test_parse_bench_progress_line_ignores_unrecognized_lines():
    assert parse_bench_progress_line("plain human log line") is None


def test_parse_bench_progress_line_recognizes_legacy_starting_log():
    event = parse_bench_progress_line("•     [3/12] starting pi+ollama+qwen3 timed iter-1")

    assert event == {
        "type": "iteration_start",
        "label": "pi+ollama+qwen3",
        "done": 2,
        "total": 12,
        "phase": "timed",
        "iteration": 1,
    }


def test_parse_bench_progress_line_recognizes_legacy_results_path():
    event = parse_bench_progress_line("• Wrote /tmp/ai-bench/results/20260522-143012/results.json")

    assert event == {
        "type": "results",
        "results_path": "/tmp/ai-bench/results/20260522-143012/results.json",
    }


def test_parse_bench_progress_line_reads_results_json_event():
    event = parse_bench_progress_line(
        'AI_BENCH_EVENT {"type":"results","results_path":"/tmp/results.json"}'
    )
    assert event == {
        "type": "results",
        "results_path": "/tmp/results.json",
    }


def test_encode_sse_serializes_event_name_and_json_data():
    encoded = encode_sse({"type": "run_start", "done": 0}, event_name="progress")

    assert encoded.startswith(b"event: progress\n")
    assert encoded.endswith(b"\n\n")
    payload_line = encoded.decode().splitlines()[1]
    assert payload_line.startswith("data: ")
    assert json.loads(payload_line.removeprefix("data: ")) == {"type": "run_start", "done": 0}
