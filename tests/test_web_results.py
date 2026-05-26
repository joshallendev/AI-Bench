import json

from ai_bench.web_results import dashboard_payload, discover_runs, load_results, raw_outputs, summarize_results


def write_results(root, run_id, data):
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    path = run_dir / "results.json"
    path.write_text(json.dumps(data))
    return path


def sample_results(timestamp="20260522-143012"):
    return {
        "timestamp": timestamp,
        "platform": "macOS",
        "cpu": "Apple M3 Pro",
        "machine": "arm64",
        "config": {
            "models": [{"id": "qwen3-1.7b", "ollama": "qwen3:1.7b"}],
            "agents": ["direct", "pi"],
            "backends": ["ollama"],
            "iterations": 2,
            "warmup": 1,
            "prompt": "Build a page.",
        },
        "pre_existing": {},
        "combos": [
            {
                "label": "direct+ollama+qwen3-1.7b",
                "agent": "direct",
                "backend": "ollama",
                "model_id": "qwen3-1.7b",
                "summary": {
                    "wall_s_median": 4.2,
                    "throughput_tok_per_s_mean_est": 52.1,
                    "ttft_s_mean": 0.31,
                },
                "iters": [],
            },
            {
                "label": "pi+ollama+qwen3-1.7b",
                "agent": "pi",
                "backend": "ollama",
                "model_id": "qwen3-1.7b",
                "summary": {
                    "wall_s_median": 12.1,
                    "throughput_tok_per_s_mean_est": 31.2,
                    "ttft_s_mean": 1.8,
                },
                "iters": [],
            },
        ],
    }


def test_load_results_reads_json_file(tmp_path):
    path = write_results(tmp_path, "20260522-143012", sample_results())

    assert load_results(path)["timestamp"] == "20260522-143012"


def test_summarize_results_computes_dashboard_metrics(tmp_path):
    path = write_results(tmp_path, "20260522-143012", sample_results())

    summary = summarize_results(path)

    assert summary.run_id == "20260522-143012"
    assert summary.name == "qwen3-1.7b x direct/pi"
    assert summary.status == "completed"
    assert summary.results_path == path
    assert summary.cpu == "Apple M3 Pro"
    assert summary.models == ["qwen3-1.7b"]
    assert summary.agents == ["direct", "pi"]
    assert summary.backends == ["ollama"]
    assert summary.iterations == 2
    assert summary.warmup == 1
    assert summary.combo_count == 2
    assert summary.fastest_wall_s == 4.2
    assert summary.peak_throughput_tok_s == 52.1


def test_discover_runs_returns_newest_first_and_skips_invalid_files(tmp_path):
    write_results(tmp_path, "20260521-090000", sample_results("20260521-090000"))
    write_results(tmp_path, "20260522-143012", sample_results("20260522-143012"))
    bad_dir = tmp_path / "not-a-run"
    bad_dir.mkdir()
    (bad_dir / "results.json").write_text("{not json")

    summaries = discover_runs(tmp_path)

    assert [summary.run_id for summary in summaries] == ["20260522-143012", "20260521-090000"]


def test_dashboard_payload_groups_matrix_and_leaderboard_data():
    payload = dashboard_payload(sample_results())

    assert payload["summary"]["run_id"] == "20260522-143012"
    assert payload["summary"]["fastest_wall_s"] == 4.2
    assert payload["summary"]["peak_throughput"] == 52.1
    assert payload["summary"]["best_ttft"] == 0.31
    assert payload["summary"]["combo_count"] == 2
    assert payload["matrix"] == [
        {
            "model": "qwen3-1.7b",
            "agent": "direct",
            "backend": "ollama",
            "wall_s": 4.2,
            "throughput_tok_s": 52.1,
            "ttft_s": 0.31,
        },
        {
            "model": "qwen3-1.7b",
            "agent": "pi",
            "backend": "ollama",
            "wall_s": 12.1,
            "throughput_tok_s": 31.2,
            "ttft_s": 1.8,
        },
    ]
    assert payload["leaderboard"][0]["agent"] == "direct"
    assert payload["leaderboard"][0]["throughput_tok_s"] == 52.1
    assert payload["leaderboard"][0]["ttft_s"] == 0.31
    assert payload["prompt"] == "Build a page."


def test_raw_outputs_reads_iteration_output_files(tmp_path):
    results = sample_results()
    results["combos"][0]["iters"] = [
        {"iter": 0, "output_file": "direct+ollama+qwen3__iter-0.txt"}
    ]
    (tmp_path / "direct+ollama+qwen3__iter-0.txt").write_text("<html>done</html>")

    assert raw_outputs(results, tmp_path) == [
        {
            "index": 0,
            "combo_index": 0,
            "item_index": 0,
            "label": "direct+ollama+qwen3-1.7b",
            "agent": "direct",
            "backend": "ollama",
            "model": "qwen3-1.7b",
            "iteration": 0,
            "output_file": "direct+ollama+qwen3__iter-0.txt",
            "text": "<html>done</html>",
            "truncated": False,
        }
    ]


def test_raw_outputs_reads_current_iterations_key(tmp_path):
    results = sample_results()
    results["combos"][0].pop("iters")
    results["combos"][0]["iterations"] = [
        {"iter": 0, "output_file": "direct+ollama+qwen3__iter-0.txt"}
    ]
    (tmp_path / "direct+ollama+qwen3__iter-0.txt").write_text("<html>done</html>")

    outputs = raw_outputs(results, tmp_path)

    assert len(outputs) == 1
    assert outputs[0]["text"] == "<html>done</html>"
    assert outputs[0]["iteration"] == 0
