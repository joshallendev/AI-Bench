import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    name: str
    status: Literal["completed", "failed", "cancelled", "running"]
    timestamp: str
    path: Path | None
    results_path: Path | None
    cpu: str | None
    models: list[str]
    agents: list[str]
    backends: list[str]
    iterations: int | None
    warmup: int | None
    combo_count: int
    fastest_wall_s: float | None
    peak_throughput_tok_s: float | None


def load_results(results_path: Path) -> dict:
    """Read and validate one results file."""
    return json.loads(results_path.read_text())


def summarize_results(results_path: Path) -> RunSummary:
    """Read one `results.json` and compute a compact dashboard summary."""
    data = load_results(results_path)
    cfg = data.get("config", {})
    combos = data.get("combos", [])

    models = [m.get("id", "") for m in cfg.get("models", [])]
    agents = cfg.get("agents", [])
    backends = cfg.get("backends", [])

    fastest_wall = None
    peak_tp = None
    for combo in combos:
        s = combo.get("summary") or {}
        w = s.get("wall_s_median")
        if w is not None and (fastest_wall is None or w < fastest_wall):
            fastest_wall = w
        t = s.get("throughput_tok_per_s_mean_est")
        if t is not None and (peak_tp is None or t > peak_tp):
            peak_tp = t

    name = f"{models[0]} x {'/'.join(agents)}" if models else ""

    run_id = Path(results_path).parent.name
    return RunSummary(
        run_id=run_id,
        name=name,
        status="completed",
        timestamp=data.get("timestamp", run_id),
        path=results_path.parent,
        results_path=results_path,
        cpu=data.get("cpu"),
        models=models,
        agents=agents,
        backends=backends,
        iterations=cfg.get("iterations"),
        warmup=cfg.get("warmup"),
        combo_count=len(combos),
        fastest_wall_s=fastest_wall,
        peak_throughput_tok_s=peak_tp,
    )


def discover_runs(results_dir: Path) -> list[RunSummary]:
    """Scan `results_dir/*/results.json` and return newest runs first."""
    summaries = []
    if not results_dir.is_dir():
        return summaries
    for run_dir in results_dir.iterdir():
        if not run_dir.is_dir():
            continue
        results_json = run_dir / "results.json"
        if not results_json.is_file():
            continue
        try:
            summaries.append(summarize_results(results_json))
        except Exception:
            continue
    summaries.sort(key=lambda s: s.timestamp, reverse=True)
    return summaries


def dashboard_payload(results: dict, run_dir: Path | None = None) -> dict:
    """Transform raw results into the shape expected by the web UI."""
    cfg = results.get("config", {})
    combos = results.get("combos", [])

    summary = summarize_dashboard(results, combos)
    matrix = []
    for combo in combos:
        s = combo.get("summary") or {}
        matrix.append({
            "model": combo.get("model_id", ""),
            "agent": combo.get("agent", ""),
            "backend": combo.get("backend", ""),
            "wall_s": s.get("wall_s_median"),
            "throughput_tok_s": s.get("throughput_tok_per_s_mean_est"),
            "ttft_s": s.get("ttft_s_mean"),
        })

    # Leaderboard sorted by throughput descending.
    leaderboard = sorted(
        [
            {
                "agent": c.get("agent"),
                "model": c.get("model_id"),
                "wall_s": (c.get("summary") or {}).get("wall_s_median"),
                "throughput_tok_s": (c.get("summary") or {}).get(
                    "throughput_tok_per_s_mean_est"
                ),
                "ttft_s": (c.get("summary") or {}).get("ttft_s_mean"),
            }
            for c in combos
        ],
        key=lambda x: x.get("throughput_tok_s") or 0,
        reverse=True,
    )

    return {
        "summary": summary,
        "matrix": matrix,
        "leaderboard": leaderboard,
        "prompt": cfg.get("prompt", ""),
        "raw_outputs": raw_output_manifest(results, run_dir) if run_dir else [],
    }


def raw_output_manifest(results: dict, run_dir: Path) -> list[dict]:
    """Return metadata for raw iteration output files referenced by a results file."""
    outputs = []
    root = run_dir.resolve()
    for combo_index, combo in enumerate(results.get("combos", [])):
        iterations = combo.get("iterations")
        if iterations is None:
            iterations = combo.get("iters", [])
        for item_index, item in enumerate(iterations):
            output_file = item.get("output_file")
            if not output_file:
                continue
            try:
                path = (root / str(output_file)).resolve()
                path.relative_to(root)
            except (OSError, ValueError):
                continue
            if not path.is_file():
                continue
            outputs.append({
                "index": len(outputs),
                "combo_index": combo_index,
                "item_index": item_index,
                "label": combo.get("label", ""),
                "agent": combo.get("agent", ""),
                "backend": combo.get("backend", ""),
                "model": combo.get("model_id", ""),
                "iteration": item.get("iter"),
                "output_file": str(output_file),
            })
    return outputs


def raw_output_at(
    results: dict,
    run_dir: Path,
    index: int,
    *,
    max_chars: int = 200_000,
) -> dict:
    """Return one raw iteration output by manifest index."""
    manifest = raw_output_manifest(results, run_dir)
    if index < 0 or index >= len(manifest):
        raise IndexError(f"Raw output index out of range: {index}")
    item = manifest[index]
    root = run_dir.resolve()
    path = (root / str(item["output_file"])).resolve()
    path.relative_to(root)
    text = path.read_text(errors="replace")
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]
    return {
        **item,
        "text": text,
        "truncated": truncated,
    }


def raw_outputs(results: dict, run_dir: Path, *, max_chars: int = 200_000) -> list[dict]:
    """Return raw iteration output text referenced by a results file."""
    return [
        raw_output_at(results, run_dir, item["index"], max_chars=max_chars)
        for item in raw_output_manifest(results, run_dir)
    ]


def summarize_dashboard(results: dict, combos: list) -> dict:
    """Extract a compact summary from raw results data."""
    run_id = results.get("timestamp", "")

    fastest_wall = None
    peak_throughput = None
    best_ttft = None
    for combo in combos:
        s = combo.get("summary") or {}
        w = s.get("wall_s_median")
        if w is not None and (fastest_wall is None or w < fastest_wall):
            fastest_wall = w
        throughput = s.get("throughput_tok_per_s_mean_est")
        if throughput is not None and (
            peak_throughput is None or throughput > peak_throughput
        ):
            peak_throughput = throughput
        ttft = s.get("ttft_s_mean")
        if ttft is not None and (best_ttft is None or ttft < best_ttft):
            best_ttft = ttft

    return {
        "run_id": run_id,
        "fastest_wall_s": fastest_wall,
        "peak_throughput": peak_throughput,
        "best_ttft": best_ttft,
        "combo_count": len(combos),
    }
