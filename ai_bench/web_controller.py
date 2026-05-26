import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


class RunRequestValidationError(ValueError):
    """Raised when a browser run request cannot become a valid bench config."""
    pass


RUN_ID_RE = re.compile(r"^\d{8}-\d{6}(?:-\d{6})?$")


@dataclass(frozen=True)
class RunRequest:
    models: list[str]
    agents: list[str]
    backends: list[str]
    iterations: int
    warmup: int
    prompt: str
    skip_install: bool = True
    model_entries: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class RunStartResponse:
    run_id: str
    status: str
    config_path: Path
    planned_total: int


def validate_run_request(
    request: RunRequest,
    available_config: dict[str, Any],
    known_agents: set[str],
    known_backends: set[str],
    agent_registry: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Raise RunRequestValidationError if the request is invalid."""
    if not request.models:
        raise RunRequestValidationError("At least one model is required")

    # Extract known model IDs from available config
    model_entries = request.model_entries or available_config.get("models", [])
    known_models = {
        m["id"] for m in model_entries if isinstance(m, dict) and isinstance(m.get("id"), str)
    }
    for model in request.models:
        if model not in known_models:
            raise RunRequestValidationError(f"Unknown model: {model}")

    for agent in request.agents:
        if agent not in known_agents:
            raise RunRequestValidationError(f"Unknown agent: {agent}")

    for backend in request.backends:
        if backend not in known_backends:
            raise RunRequestValidationError(f"Unknown backend: {backend}")

    if request.iterations < 1:
        raise RunRequestValidationError("iterations must be >= 1")

    if request.warmup < 0:
        raise RunRequestValidationError("warmup must be >= 0")

    if not request.prompt.strip():
        raise RunRequestValidationError("prompt must not be empty")

    # NEW: combo-level validation
    if agent_registry:
        from ai_bench.combos import planned_combos
        model_entries = request.model_entries or available_config.get("models", [])
        combos = planned_combos(
            models=[m for m in model_entries if m.get("id") in set(request.models)],
            agents=request.agents,
            backends=request.backends,
            agent_registry=agent_registry,
        )
        if not combos:
            raise RunRequestValidationError(
                "No valid combinations after filtering. "
                "Check that selected models have aliases for selected backends "
                "and that selected agents support the selected backends."
            )


def build_run_config(
    request: RunRequest,
    available_config: dict[str, Any],
) -> dict[str, Any]:
    """Build the exact config dict consumed by `ai-bench --config`."""
    model_ids = set(request.models)
    model_entries = (
        request.model_entries
        if request.model_entries is not None
        else available_config.get("models", [])
    )

    # Build lookup from backend -> set of alias keys
    # backend keys are things like "ollama", "lmstudio", "omlx", "omlx_hf"
    backend_to_keys = {
        "ollama": {"ollama"},
        "lmstudio": {"lmstudio"},
        "omlx": {"omlx", "omlx_hf"},
    }

    selected_backend_keys = set()
    for backend in request.backends:
        selected_backend_keys.add(backend)
        selected_backend_keys.update(backend_to_keys.get(backend, set()))

    # Filter models and strip alias keys for unselected backends
    filtered_models = []
    for m in model_entries:
        if not isinstance(m, dict):
            continue
        if m.get("id") not in model_ids:
            continue
        filtered = {"id": m["id"]}
        for k, v in m.items():
            if k == "id":
                continue
            if k in selected_backend_keys:
                filtered[k] = v
        filtered_models.append(filtered)

    return {
        "models": filtered_models,
        "agents": request.agents,
        "backends": request.backends,
        "iterations": request.iterations,
        "warmup": request.warmup,
        "prompt": request.prompt,
    }


def write_generated_config(
    *,
    root: Path,
    run_id: str,
    config: dict[str, Any],
) -> Path:
    """Write `.bench-web/runs/{run_id}/bench.config.json` and return its path."""
    out_dir = root / ".bench-web" / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    config_path = out_dir / "bench.config.json"
    config_path.write_text(json.dumps(config, indent=2))
    return config_path


def validate_run_id(run_id: str) -> str:
    """Return a safe run id or raise ValueError."""
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError(f"Invalid run id: {run_id!r}")
    return run_id


def build_bench_command(
    *,
    python_executable: Path,
    root: Path,
    config_path: Path,
    skip_install: bool,
    progress_json: bool = True,
) -> list[str]:
    """Return the subprocess argv for a benchmark run."""
    cmd = [
        str(python_executable),
        "-u",
        "-m",
        "ai_bench.cli",
        "--config",
        str(config_path),
    ]
    if progress_json:
        cmd.append("--progress-json")
    if skip_install:
        cmd.append("--skip-install")
    return cmd


def preflight_selection(data: dict[str, object], bench_module: Any) -> dict[str, object]:
    """Validate a pending web run selection before it launches."""
    _bench = bench_module
    model_entries = data.get("model_entries")
    agents = data.get("agents") or []
    backends = data.get("backends") or []
    allow_download = not bool(data.get("skip_install", True))
    issues: list[dict[str, object]] = []

    if not isinstance(model_entries, list) or not model_entries:
        issues.append({"level": "error", "message": "Select at least one model."})
    if not isinstance(agents, list) or not agents:
        issues.append({"level": "error", "message": "Select at least one agent."})
    if not isinstance(backends, list) or not backends:
        issues.append({"level": "error", "message": "Select at least one backend."})

    backend_checks = {
        "ollama": (_bench.have_ollama, _bench.have_ollama_model),
        "lmstudio": (_bench.have_lmstudio, _bench.have_lmstudio_model),
        "omlx": (_bench.have_omlx, _bench.have_omlx_model),
    }
    for backend in backends if isinstance(backends, list) else []:
        if backend not in backend_checks:
            issues.append({"level": "error", "message": f"Unknown backend: {backend}"})
            continue
        have_backend, have_model = backend_checks[backend]
        if not have_backend():
            issues.append({
                "level": "error",
                "backend": backend,
                "message": f"{backend} is not installed or not available.",
            })
            continue
        for entry in model_entries if isinstance(model_entries, list) else []:
            if not isinstance(entry, dict) or backend not in entry:
                continue
            alias = str(entry[backend])
            if have_model(alias):
                continue
            level = "warning" if allow_download else "error"
            action = "will be downloaded before the run" if allow_download else "is not installed"
            issues.append({
                "level": level,
                "backend": backend,
                "model": entry.get("id", alias),
                "alias": alias,
                "message": f"{alias} {action} for {backend}.",
            })

    # After backend/model availability checks:
    if isinstance(agents, list) and isinstance(backends, list):
        bench_agents = getattr(_bench, "AGENTS", {})
        for agent in agents:
            agent_info = bench_agents.get(agent, {})
            supported = agent_info.get("supports_backends", [])
            for backend in backends:
                if backend not in supported:
                    issues.append({
                        "level": "error",
                        "agent": agent,
                        "backend": backend,
                        "message": f"{agent} does not support the {backend} backend.",
                    })

    ok = not any(issue.get("level") == "error" for issue in issues)
    return {"ok": ok, "issues": issues}


class WebController:
    def __init__(
        self,
        *,
        root: Path,
        results_dir: Path,
        python_executable: Path,
        process_manager: Any = None,  # BenchmarkProcessManager | None
    ) -> None:
        """Create the controller for one repo checkout."""
        self._root = root
        self._results_dir = results_dir
        self._python_executable = python_executable
        self._process_manager = process_manager

    def health(self) -> dict[str, object]:
        """Return a small JSON-safe health payload."""
        return {
            "status": "ok",
            "root": str(self._root),
            "results_dir": str(self._results_dir),
        }

    def get_config(self) -> dict[str, object]:
        """Read the current `bench.config.json` or return benchmark defaults."""
        cfg_path = self._root / "bench.config.json"
        if cfg_path.exists():
            try:
                return json.loads(cfg_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {
            "models": [],
            "agents": ["pi", "direct"],
            "backends": ["ollama"],
            "iterations": 3,
            "warmup": 1,
            "prompt": _DEFAULT_PROMPT,
        }

    def save_config(self, config: dict[str, object]) -> dict[str, object]:
        """Validate and persist `bench.config.json`."""
        cfg_path = self._root / "bench.config.json"
        cfg_path.write_text(json.dumps(config, indent=2))
        return config

    def detect(self) -> dict[str, object]:
        """Return installed agents, backends, and local models."""
        _bench = self._bench_module()

        agent_labels = {
            "direct": "Direct",
            "pi": "pi",
            "opencode": "opencode",
        }
        agents = [
            {
                "id": name,
                "name": agent_labels.get(name, name),
                "desc": info.get("desc", name),
                "status": "installed",
                "version": "built-in" if name == "direct" else "",
                "supports_backends": list(info.get("supports_backends", [])),
            }
            for name, info in _bench.AGENTS.items()
            if info["is_installed"]()
        ]

        backend_labels = {
            "ollama": "Ollama",
            "lmstudio": "LM Studio",
            "omlx": "oMLX",
        }
        backends = []
        for name in ["ollama", "lmstudio", "omlx"]:
            fn = getattr(_bench, f"have_{name}", None)
            if fn and fn():
                backends.append({
                    "id": name,
                    "name": backend_labels.get(name, name),
                    "desc": f"{backend_labels.get(name, name)} backend",
                    "status": "installed",
                    "version": "",
                })

        models = []
        if _bench.have_ollama():
            for m in _bench._list_ollama_installed():
                models.append({"backend": "ollama", **m})
        if _bench.have_lmstudio():
            for m in _bench._list_lmstudio_installed():
                models.append({"backend": "lmstudio", **m})
        if _bench.have_omlx():
            for m in _bench._list_omlx_installed():
                models.append({"backend": "omlx", **m})

        return {
            "agents": agents,
            "backends": backends,
            "models": models,
        }

    def installed_models(self) -> dict[str, object]:
        """Return installed models in the same shape used by the web picker."""
        _bench = self._bench_module()
        backends = {
            "ollama": _bench._list_ollama_installed() if _bench.have_ollama() else [],
            "lmstudio": _bench._list_lmstudio_installed() if _bench.have_lmstudio() else [],
            "omlx": _bench._list_omlx_installed() if _bench.have_omlx() else [],
        }
        return {
            "backends": {
                backend: [self._catalog_item(backend, item, source="installed") for item in items]
                for backend, items in backends.items()
            }
        }

    def search_models(self, backend: str, query: str) -> dict[str, object]:
        """Search remote model catalogs for a backend."""
        _bench = self._bench_module()
        query = query.strip()
        if backend not in {"ollama", "lmstudio", "omlx"}:
            raise ValueError(f"Unknown backend: {backend}")
        if not query:
            return {"backend": backend, "query": query, "results": []}
        search_fn = {
            "ollama": _bench._search_ollama,
            "lmstudio": _bench._search_lmstudio_online,
            "omlx": _bench._search_hf_mlx,
        }[backend]
        results = [
            self._catalog_item(backend, item, source="remote")
            for item in search_fn(query)
        ]
        return {"backend": backend, "query": query, "results": results}

    def preflight_selection(self, data: dict[str, object]) -> dict[str, object]:
        """Validate a pending web run selection before it launches."""
        _bench = self._bench_module()
        return preflight_selection(data, _bench)

    def list_runs(self) -> list[dict[str, object]]:
        """Return historical runs plus the current in-memory run, newest first."""
        from ai_bench.web_results import discover_runs

        runs = [
            _summary_to_run(s) for s in discover_runs(self._results_dir)
        ]
        discovered_result_paths = {
            str(r.get("results_path")) for r in runs if r.get("results_path")
        }

        # Include current in-memory process status. Poll first so fast failures
        # do not remain stuck as "running" until an SSE client drains stdout.
        if self._process_manager:
            self._process_manager.poll()
            current = self._process_manager.current_status()
            discovered_ids = {str(r.get("run_id")) for r in runs}
            current_results_path = (
                str(current.results_path) if current and current.results_path else None
            )
            if current and current_results_path in discovered_result_paths:
                for run in runs:
                    if run.get("results_path") == current_results_path:
                        run["run_id"] = current.run_id
                        log_path = getattr(current, "log_path", None)
                        run["log_path"] = str(log_path) if log_path else None
                        if current.status == "running":
                            run["status"] = current.status
                            run["progress_done"] = current.progress_done
                            run["progress_total"] = current.progress_total
                            run["last_log"] = current.last_log
                        break
            if (
                current
                and current.run_id not in discovered_ids
                and current_results_path not in discovered_result_paths
            ):
                log_path = getattr(current, "log_path", None)
                runs.insert(0, {
                    "run_id": current.run_id,
                    "name": f"run-{current.run_id}",
                    "status": current.status,
                    "timestamp": current.run_id,
                    "results_path": str(current.results_path) if current.results_path else None,
                    "models": [],
                    "agents": [],
                    "backends": [],
                    "combo_count": 0,
                    "fastest_wall_s": None,
                    "peak_throughput_tok_s": None,
                    "progress_done": current.progress_done,
                    "progress_total": current.progress_total,
                    "last_log": current.last_log,
                    "log_path": str(log_path) if log_path else None,
                })

        return runs

    def get_run(self, run_id: str) -> dict[str, object]:
        """Return one summarized run or raise KeyError."""
        # Check in-memory first
        if self._process_manager:
            self._process_manager.poll()
            current = self._process_manager.current_status()
            if current and current.run_id == run_id:
                log_path = getattr(current, "log_path", None)
                return {
                    "run_id": current.run_id,
                    "status": current.status,
                    "pid": current.pid,
                    "started_at": current.started_at,
                    "finished_at": current.finished_at,
                    "returncode": current.returncode,
                    "progress_done": current.progress_done,
                    "progress_total": current.progress_total,
                    "config_path": str(current.config_path),
                    "log_path": str(log_path) if log_path else None,
                }

        # Check historical results
        results_path = self._results_dir / run_id / "results.json"
        if results_path.exists():
            from ai_bench.web_results import summarize_results
            summary = summarize_results(results_path)
            return _summary_to_run(summary)

        raise KeyError(f"Run {run_id} not found")

    def get_results(self, run_id: str) -> dict[str, object]:
        """Return raw results data for one completed run."""
        results_path = self._results_path_for_run(run_id)

        from ai_bench.web_results import load_results, dashboard_payload
        raw = load_results(results_path)
        return dashboard_payload(raw, results_path.parent)

    def get_raw_output(self, run_id: str, index: int) -> dict[str, object]:
        """Return one raw output item for a completed run."""
        results_path = self._results_path_for_run(run_id)

        from ai_bench.web_results import load_results, raw_output_at
        raw = load_results(results_path)
        return raw_output_at(raw, results_path.parent, index)

    def _results_path_for_run(self, run_id: str) -> Path:
        """Resolve a run id to its current or historical results path."""
        results_path = None
        if self._process_manager:
            self._process_manager.poll()
            current = self._process_manager.current_status()
            if current and current.run_id == run_id and current.results_path:
                results_path = current.results_path

        if results_path is None:
            results_path = self._results_dir / run_id / "results.json"

        if not results_path.exists():
            raise KeyError(f"Results for run {run_id} not found")
        return results_path

    def get_run_config(self, run_id: str) -> dict[str, Any]:
        """Return the generated bench config for a run."""
        validate_run_id(run_id)
        run_config = self._root / ".bench-web" / "runs" / run_id / "bench.config.json"
        if run_config.exists():
            return json.loads(run_config.read_text())
        results_config = self._results_dir / run_id / "results.json"
        if results_config.exists():
            from ai_bench.web_results import load_results
            cfg = load_results(results_config).get("config")
            if isinstance(cfg, dict):
                return cfg
        raise KeyError(f"No config found for run {run_id}")

    def delete_run(self, run_id: str) -> None:
        """Delete generated web-run files and historical results for a run."""
        validate_run_id(run_id)
        if self._process_manager:
            self._process_manager.poll()
            current = self._process_manager.current_status()
            if current and current.run_id == run_id and current.status == "running":
                raise RuntimeError(f"Run {run_id} is currently active")

        paths = [
            self._root / ".bench-web" / "runs" / run_id,
            self._results_dir / run_id,
        ]
        parents = [
            self._root / ".bench-web" / "runs",
            self._results_dir,
        ]
        existing = []
        for path, parent in zip(paths, parents):
            resolved = path.resolve()
            resolved.relative_to(parent.resolve())
            if resolved.exists():
                existing.append(resolved)
        if not existing:
            raise KeyError(f"Run {run_id} not found")
        for path in existing:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

    def start_run(self, request: RunRequest) -> RunStartResponse:
        """Validate, write a generated config, and launch `ai-bench`."""
        if not self._process_manager:
            raise RuntimeError("No process manager configured")

        config = self.get_config()
        detection = self.detect()
        _bench = self._bench_module()

        validate_run_request(
            request,
            config,
            known_agents=_ids_from_detection(detection.get("agents", [])),
            known_backends=_ids_from_detection(detection.get("backends", [])),
            agent_registry=_bench.AGENTS,
        )

        run_config = build_run_config(request, config)
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        
        # Compute planned total before writing config
        from ai_bench.combos import planned_combos, planned_step_count
        model_entries = run_config["models"]
        combos = planned_combos(
            models=model_entries,
            agents=request.agents,
            backends=request.backends,
            agent_registry=_bench.AGENTS,
        )
        total = planned_step_count(combos, iterations=request.iterations, warmup=request.warmup)

        config_path = write_generated_config(
            root=self._root,
            run_id=run_id,
            config=run_config,
        )

        argv = build_bench_command(
            python_executable=self._python_executable,
            root=self._root,
            config_path=config_path,
            skip_install=request.skip_install,
        )

        self._process_manager.start(
            run_id=run_id,
            argv=argv,
            config_path=config_path,
        )

        return RunStartResponse(
            run_id=run_id,
            status="running",
            config_path=config_path,
            planned_total=total,
        )

    def stop_current_run(self) -> dict[str, object]:
        """Request cancellation of the active benchmark."""
        if not self._process_manager:
            raise RuntimeError("No process manager configured")
        status = self._process_manager.stop_current()
        return {
            "run_id": status.run_id,
            "status": status.status,
        }

    def event_stream(self) -> Iterator[dict[str, object]]:
        """Yield live JSON-safe events for `/api/events`."""
        if not self._process_manager:
            return
        for event in self._process_manager.iter_events():
            yield {
                "run_id": event.run_id,
                "type": event.type,
                **event.payload,
            }

    def _bench_module(self) -> Any:
        """Import benchmark CLI helpers."""
        import sys as _sys

        if "bench" in _sys.modules:
            return _sys.modules["bench"]
        from ai_bench import cli as _bench
        return _bench

    def _catalog_item(
        self,
        backend: str,
        item: dict[str, object],
        *,
        source: str,
    ) -> dict[str, object]:
        """Return a web-safe model catalog item with a run config entry."""
        _bench = self._bench_module()
        model_id = str(item.get("id", ""))
        label = _bench._normalize_label(model_id)
        entry: dict[str, object] = {"id": label}
        if backend == "omlx":
            local_id = str(item.get("id", ""))
            entry["omlx"] = local_id
            entry["omlx_hf"] = item.get("hf_id") or f"mlx-community/{local_id}"
        else:
            entry[backend] = model_id
        return {
            "backend": backend,
            "id": model_id,
            "label": label,
            "size": item.get("size", ""),
            "desc": item.get("desc", ""),
            "source": source,
            "model_entry": entry,
        }


_DEFAULT_PROMPT = (
    "Build a single-page website in plain HTML, CSS, and JavaScript with two buttons. "
    "The first button fetches a random joke from https://icanhazdadjoke.com/ (send header "
    "'Accept: application/json') and displays it on the page. The second button toggles dark "
    "mode by adding/removing a 'dark' CSS class on the body, with appropriate styles for both "
    "modes. Output a single complete HTML file with inline <style> and <script> tags. No build "
    "tools, no frameworks. Output only the HTML, no commentary. Ask no questions and make any "
    "required assumptions yourself."
)


def _summary_to_run(summary: Any) -> dict[str, object]:
    """Convert a RunSummary to a JSON-safe dict for the run list."""
    return {
        "run_id": summary.run_id,
        "name": summary.name,
        "status": summary.status,
        "timestamp": summary.timestamp,
        "results_path": str(summary.results_path) if summary.results_path else None,
        "cpu": summary.cpu,
        "models": summary.models,
        "agents": summary.agents,
        "backends": summary.backends,
        "iterations": summary.iterations,
        "warmup": summary.warmup,
        "combo_count": summary.combo_count,
        "fastest_wall_s": summary.fastest_wall_s,
        "peak_throughput_tok_s": summary.peak_throughput_tok_s,
    }


def _ids_from_detection(items: object) -> set[str]:
    """Return ids from a detection list supporting legacy strings or objects."""
    ids: set[str] = set()
    if not isinstance(items, list):
        return ids
    for item in items:
        if isinstance(item, str):
            ids.add(item)
        elif isinstance(item, dict) and isinstance(item.get("id"), str):
            ids.add(item["id"])
    return ids
