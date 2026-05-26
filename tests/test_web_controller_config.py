import json
import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

from ai_bench.web_controller import (
    RunRequest,
    RunRequestValidationError,
    WebController,
    build_bench_command,
    build_run_config,
    validate_run_request,
    write_generated_config,
)


AVAILABLE_CONFIG = {
    "models": [
        {
            "id": "qwen3-1.7b",
            "ollama": "qwen3:1.7b",
            "lmstudio": "lmstudio-community/Qwen3-1.7B-GGUF",
        },
        {
            "id": "qwen3-coder-next",
            "lmstudio": "lmstudio-community/Qwen3-Coder-Next-MLX-4bit",
            "omlx": "Qwen3-Coder-Next-MLX-4bit",
            "omlx_hf": "lmstudio-community/Qwen3-Coder-Next-MLX-4bit",
        },
    ],
    "agents": ["pi", "opencode", "direct"],
    "backends": ["ollama", "lmstudio", "omlx"],
    "iterations": 3,
    "warmup": 1,
    "prompt": "Build a page.",
}


def test_validate_run_request_accepts_known_models_agents_and_backends():
    request = RunRequest(
        models=["qwen3-1.7b"],
        agents=["pi", "direct"],
        backends=["ollama"],
        iterations=2,
        warmup=1,
        prompt="Build a page.",
    )

    validate_run_request(
        request,
        AVAILABLE_CONFIG,
        known_agents={"pi", "opencode", "direct"},
        known_backends={"ollama", "lmstudio", "omlx"},
    )


@pytest.mark.parametrize(
    ("req", "message"),
    [
        (
            RunRequest(
                models=[],
                agents=["pi"],
                backends=["ollama"],
                iterations=1,
                warmup=0,
                prompt="Build a page.",
            ),
            "model",
        ),
        (
            RunRequest(
                models=["missing-model"],
                agents=["pi"],
                backends=["ollama"],
                iterations=1,
                warmup=0,
                prompt="Build a page.",
            ),
            "missing-model",
        ),
        (
            RunRequest(
                models=["qwen3-1.7b"],
                agents=["unknown-agent"],
                backends=["ollama"],
                iterations=1,
                warmup=0,
                prompt="Build a page.",
            ),
            "unknown-agent",
        ),
        (
            RunRequest(
                models=["qwen3-1.7b"],
                agents=["pi"],
                backends=["unknown-backend"],
                iterations=1,
                warmup=0,
                prompt="Build a page.",
            ),
            "unknown-backend",
        ),
        (
            RunRequest(
                models=["qwen3-1.7b"],
                agents=["pi"],
                backends=["ollama"],
                iterations=0,
                warmup=0,
                prompt="Build a page.",
            ),
            "iterations",
        ),
        (
            RunRequest(
                models=["qwen3-1.7b"],
                agents=["pi"],
                backends=["ollama"],
                iterations=1,
                warmup=-1,
                prompt="Build a page.",
            ),
            "warmup",
        ),
        (
            RunRequest(
                models=["qwen3-1.7b"],
                agents=["pi"],
                backends=["ollama"],
                iterations=1,
                warmup=0,
                prompt="   ",
            ),
            "prompt",
        ),
    ],
)
def test_validate_run_request_rejects_invalid_inputs(req, message):
    with pytest.raises(RunRequestValidationError, match=message):
        validate_run_request(
            req,
            AVAILABLE_CONFIG,
            known_agents={"pi", "opencode", "direct"},
            known_backends={"ollama", "lmstudio", "omlx"},
        )


def test_build_run_config_filters_models_and_preserves_backend_aliases():
    request = RunRequest(
        models=["qwen3-coder-next"],
        agents=["pi"],
        backends=["lmstudio", "omlx"],
        iterations=5,
        warmup=2,
        prompt="Build a richer page.",
    )

    config = build_run_config(request, AVAILABLE_CONFIG)

    assert config == {
        "models": [
            {
                "id": "qwen3-coder-next",
                "lmstudio": "lmstudio-community/Qwen3-Coder-Next-MLX-4bit",
                "omlx": "Qwen3-Coder-Next-MLX-4bit",
                "omlx_hf": "lmstudio-community/Qwen3-Coder-Next-MLX-4bit",
            }
        ],
        "agents": ["pi"],
        "backends": ["lmstudio", "omlx"],
        "iterations": 5,
        "warmup": 2,
        "prompt": "Build a richer page.",
    }


def test_build_run_config_drops_model_aliases_for_unselected_backends():
    request = RunRequest(
        models=["qwen3-1.7b"],
        agents=["direct"],
        backends=["ollama"],
        iterations=1,
        warmup=0,
        prompt="Build a page.",
    )

    config = build_run_config(request, AVAILABLE_CONFIG)

    assert config["models"] == [{"id": "qwen3-1.7b", "ollama": "qwen3:1.7b"}]


def test_build_run_config_can_use_web_selected_model_entries():
    request = RunRequest(
        models=["qwen3-4b"],
        agents=["direct"],
        backends=["ollama", "lmstudio"],
        iterations=1,
        warmup=0,
        prompt="Build a page.",
        model_entries=[
            {
                "id": "qwen3-4b",
                "ollama": "qwen3:4b",
                "lmstudio": "mlx-community/Qwen3-4B-4bit",
            }
        ],
    )

    config = build_run_config(request, {"models": []})

    assert config["models"] == [
        {
            "id": "qwen3-4b",
            "ollama": "qwen3:4b",
            "lmstudio": "mlx-community/Qwen3-4B-4bit",
        }
    ]


def test_validate_run_request_accepts_web_selected_model_entries():
    request = RunRequest(
        models=["qwen3-4b"],
        agents=["direct"],
        backends=["ollama"],
        iterations=1,
        warmup=0,
        prompt="Build a page.",
        model_entries=[{"id": "qwen3-4b", "ollama": "qwen3:4b"}],
    )

    validate_run_request(
        request,
        {"models": []},
        known_agents={"direct"},
        known_backends={"ollama"},
    )


def test_write_generated_config_uses_run_scoped_directory(tmp_path):
    config = {"models": [], "agents": [], "backends": [], "iterations": 1, "warmup": 0, "prompt": "x"}

    path = write_generated_config(root=tmp_path, run_id="20260522-143012", config=config)

    assert path == tmp_path / ".bench-web" / "runs" / "20260522-143012" / "bench.config.json"
    assert json.loads(path.read_text()) == config


def test_build_bench_command_uses_argv_list_and_skip_install_by_default(tmp_path):
    command = build_bench_command(
        python_executable=Path("/usr/bin/python3"),
        root=tmp_path,
        config_path=tmp_path / "config.json",
        skip_install=True,
    )

    assert command == [
        "/usr/bin/python3",
        "-u",
        "-m",
        "ai_bench.cli",
        "--config",
        str(tmp_path / "config.json"),
        "--progress-json",
        "--skip-install",
    ]


def test_build_bench_command_can_allow_installs_when_requested(tmp_path):
    command = build_bench_command(
        python_executable=Path("/usr/bin/python3"),
        root=tmp_path,
        config_path=tmp_path / "config.json",
        skip_install=False,
    )

    assert "--skip-install" not in command
    assert "--progress-json" in command


def test_detect_returns_structured_agents_and_backends(monkeypatch, tmp_path):
    fake_bench = types.SimpleNamespace(
        AGENTS={
            "pi": {
                "is_installed": lambda: True,
                "desc": "Lightweight AI pair-programming agent",
                "supports_backends": ["ollama", "lmstudio", "omlx"],
            },
            "opencode": {
                "is_installed": lambda: False,
                "desc": "Open-source coding agent",
                "supports_backends": ["ollama", "lmstudio", "omlx"],
            },
            "direct": {
                "is_installed": lambda: True,
                "desc": "Raw backend API",
                "supports_backends": ["ollama"],
            },
        },
        have_ollama=lambda: True,
        have_lmstudio=lambda: False,
        have_omlx=lambda: True,
        _list_ollama_installed=lambda: [{"id": "qwen3:1.7b", "size": "1.4 GB"}],
        _list_lmstudio_installed=lambda: [],
        _list_omlx_installed=lambda: [{"id": "Qwen3-Coder-Next-MLX-4bit", "size": "2.8 GB"}],
    )
    monkeypatch.setitem(sys.modules, "bench", fake_bench)

    controller = WebController(
        root=tmp_path,
        results_dir=tmp_path / "results",
        python_executable=Path("/usr/bin/python3"),
    )

    detection = controller.detect()

    assert detection["agents"] == [
        {
            "id": "pi",
            "name": "pi",
            "desc": "Lightweight AI pair-programming agent",
            "status": "installed",
            "version": "",
            "supports_backends": ["ollama", "lmstudio", "omlx"],
        },
        {
            "id": "direct",
            "name": "Direct",
            "desc": "Raw backend API",
            "status": "installed",
            "version": "built-in",
            "supports_backends": ["ollama"],
        },
    ]
    assert detection["backends"] == [
        {
            "id": "ollama",
            "name": "Ollama",
            "desc": "Ollama backend",
            "status": "installed",
            "version": "",
        },
        {
            "id": "omlx",
            "name": "oMLX",
            "desc": "oMLX backend",
            "status": "installed",
            "version": "",
        },
    ]
    assert detection["models"] == [
        {"backend": "ollama", "id": "qwen3:1.7b", "size": "1.4 GB"},
        {"backend": "omlx", "id": "Qwen3-Coder-Next-MLX-4bit", "size": "2.8 GB"},
    ]


def test_installed_models_returns_catalog_entries(monkeypatch, tmp_path):
    fake_bench = types.SimpleNamespace(
        have_ollama=lambda: True,
        have_lmstudio=lambda: True,
        have_omlx=lambda: True,
        _list_ollama_installed=lambda: [{"id": "qwen3:1.7b", "size": "1.4 GB"}],
        _list_lmstudio_installed=lambda: [{"id": "lmstudio-community/Qwen3-1.7B-GGUF", "desc": "gguf"}],
        _list_omlx_installed=lambda: [{"id": "Qwen3-Coder-Next-MLX-4bit", "hf_id": "mlx-community/Qwen3-Coder-Next-MLX-4bit"}],
        _normalize_label=lambda model_id: model_id.lower().replace(":", "-").split("/")[-1],
    )
    monkeypatch.setitem(sys.modules, "bench", fake_bench)
    controller = WebController(
        root=tmp_path,
        results_dir=tmp_path / "results",
        python_executable=Path("/usr/bin/python3"),
    )

    payload = controller.installed_models()

    assert payload["backends"]["ollama"][0]["model_entry"] == {
        "id": "qwen3-1.7b",
        "ollama": "qwen3:1.7b",
    }
    assert payload["backends"]["lmstudio"][0]["model_entry"] == {
        "id": "qwen3-1.7b-gguf",
        "lmstudio": "lmstudio-community/Qwen3-1.7B-GGUF",
    }
    assert payload["backends"]["omlx"][0]["model_entry"] == {
        "id": "qwen3-coder-next-mlx-4bit",
        "omlx": "Qwen3-Coder-Next-MLX-4bit",
        "omlx_hf": "mlx-community/Qwen3-Coder-Next-MLX-4bit",
    }


def test_search_models_uses_backend_catalog_search(monkeypatch, tmp_path):
    fake_bench = types.SimpleNamespace(
        _search_ollama=lambda query: [{"id": f"{query}:latest", "size": "4 GB"}],
        _search_lmstudio_online=lambda query: [],
        _search_hf_mlx=lambda query: [],
        _normalize_label=lambda model_id: model_id.replace(":", "-"),
    )
    monkeypatch.setitem(sys.modules, "bench", fake_bench)
    controller = WebController(
        root=tmp_path,
        results_dir=tmp_path / "results",
        python_executable=Path("/usr/bin/python3"),
    )

    payload = controller.search_models("ollama", "qwen")

    assert payload["results"] == [
        {
            "backend": "ollama",
            "id": "qwen:latest",
            "label": "qwen-latest",
            "size": "4 GB",
            "desc": "",
            "source": "remote",
            "model_entry": {"id": "qwen-latest", "ollama": "qwen:latest"},
        }
    ]


def test_preflight_selection_blocks_missing_without_download_and_warns_with_download(monkeypatch, tmp_path):
    fake_bench = types.SimpleNamespace(
        have_ollama=lambda: True,
        have_lmstudio=lambda: False,
        have_omlx=lambda: True,
        have_ollama_model=lambda model: model == "qwen3:1.7b",
        have_lmstudio_model=lambda model: False,
        have_omlx_model=lambda model: False,
        AGENTS={"direct": {"is_installed": lambda: True, "desc": "", "supports_backends": ["ollama", "lmstudio", "omlx"]}},
    )
    monkeypatch.setitem(sys.modules, "bench", fake_bench)
    controller = WebController(
        root=tmp_path,
        results_dir=tmp_path / "results",
        python_executable=Path("/usr/bin/python3"),
    )
    selection = {
        "model_entries": [{"id": "qwen3-4b", "ollama": "qwen3:4b"}],
        "agents": ["direct"],
        "backends": ["ollama"],
    }

    blocked = controller.preflight_selection({**selection, "skip_install": True})
    allowed = controller.preflight_selection({**selection, "skip_install": False})

    assert blocked["ok"] is False
    assert blocked["issues"][0]["level"] == "error"
    assert allowed["ok"] is True
    assert allowed["issues"][0]["level"] == "warning"


def test_preflight_selection_errors_on_unsupported_agent_backend_pair(monkeypatch, tmp_path):
    fake_bench = types.SimpleNamespace(
        have_ollama=lambda: True,
        have_lmstudio=lambda: True,
        have_omlx=lambda: False,
        have_ollama_model=lambda m: True,
        have_lmstudio_model=lambda m: True,
        have_omlx_model=lambda m: False,
        AGENTS={"opencode": {"is_installed": lambda: True, "desc": "", "supports_backends": ["ollama"]}},
    )
    monkeypatch.setitem(sys.modules, "bench", fake_bench)
    controller = WebController(
        root=tmp_path,
        results_dir=tmp_path / "results",
        python_executable=Path("/usr/bin/python3"),
    )

    result = controller.preflight_selection({
        "model_entries": [{"id": "m1", "ollama": "m1:latest", "lmstudio": "m1-gguf"}],
        "agents": ["opencode"],
        "backends": ["lmstudio"],  # opencode doesn't support lmstudio
        "skip_install": True,
    })

    assert result["ok"] is False
    assert any("does not support" in i["message"] for i in result["issues"])


@dataclass
class FakeRunStatus:
    run_id: str
    status: str
    results_path: Path | None
    progress_done: int = 0
    progress_total: int = 0
    last_log: str = ""
    pid: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    returncode: int | None = None
    config_path: Path | None = None


class FakeProcessManager:
    def __init__(self, status):
        self.status = status
        self.poll_count = 0

    def poll(self):
        self.poll_count += 1

    def current_status(self):
        return self.status


def test_get_results_uses_current_status_results_path_when_run_ids_differ(tmp_path):
    from ai_bench.web_controller import WebController

    actual_results = tmp_path / "results" / "bench-timestamp" / "results.json"
    actual_results.parent.mkdir(parents=True)
    actual_results.write_text(json.dumps({
        "timestamp": "bench-timestamp",
        "config": {"prompt": "hello"},
        "combos": [],
    }))
    status = FakeRunStatus(
        run_id="web-run-id",
        status="completed",
        results_path=actual_results,
        config_path=tmp_path / "bench.config.json",
    )
    controller = WebController(
        root=tmp_path,
        results_dir=tmp_path / "results",
        python_executable=Path("/usr/bin/python3"),
        process_manager=FakeProcessManager(status),
    )

    payload = controller.get_results("web-run-id")

    assert payload["summary"]["run_id"] == "bench-timestamp"
    assert payload["prompt"] == "hello"


def test_list_runs_preserves_current_web_run_id_for_discovered_results(tmp_path):
    from ai_bench.web_controller import WebController

    actual_results = tmp_path / "results" / "bench-timestamp" / "results.json"
    actual_results.parent.mkdir(parents=True)
    actual_results.write_text(json.dumps({
        "timestamp": "bench-timestamp",
        "config": {
            "models": [{"id": "qwen"}],
            "agents": ["pi"],
            "backends": ["ollama"],
        },
        "combos": [],
    }))
    status = FakeRunStatus(
        run_id="web-run-id",
        status="completed",
        results_path=actual_results,
        progress_done=1,
        progress_total=1,
        config_path=tmp_path / "bench.config.json",
    )
    controller = WebController(
        root=tmp_path,
        results_dir=tmp_path / "results",
        python_executable=Path("/usr/bin/python3"),
        process_manager=FakeProcessManager(status),
    )

    runs = controller.list_runs()

    assert len(runs) == 1
    assert runs[0]["run_id"] == "web-run-id"
    assert runs[0]["status"] == "completed"
    assert runs[0]["results_path"] == str(actual_results)
    assert "progress_done" not in runs[0]
    assert "progress_total" not in runs[0]


def test_validate_run_request_raises_when_no_combos_survive_filtering():
    """Model with no alias for selected backend → zero combos → error."""
    request = RunRequest(
        models=["qwen3-coder-next"],   # has no ollama alias
        agents=["pi"],
        backends=["ollama"],
        iterations=1, warmup=0, prompt="x.",
    )
    registry = {"pi": {"supports_backends": ["ollama", "lmstudio", "omlx"]}}

    with pytest.raises(RunRequestValidationError, match="No valid combinations"):
        validate_run_request(
            request, AVAILABLE_CONFIG,
            known_agents={"pi"}, known_backends={"ollama"},
            agent_registry=registry,
        )


def test_validate_run_request_raises_when_agent_does_not_support_backend():
    request = RunRequest(
        models=["qwen3-1.7b"],
        agents=["opencode"],
        backends=["lmstudio"],
        iterations=1, warmup=0, prompt="x.",
    )
    registry = {"opencode": {"supports_backends": ["ollama"]}}  # lmstudio not supported

    with pytest.raises(RunRequestValidationError, match="No valid combinations"):
        validate_run_request(
            request, AVAILABLE_CONFIG,
            known_agents={"opencode"}, known_backends={"lmstudio"},
            agent_registry=registry,
        )


def test_start_run_response_includes_planned_total(monkeypatch, tmp_path):
    fake_bench = types.SimpleNamespace(
        AGENTS={
            "pi": {"is_installed": lambda: True, "supports_backends": ["ollama"],
                   "desc": "", "direct": False, "build_cmd": lambda *a: ([], {})},
            "direct": {"is_installed": lambda: True, "supports_backends": ["ollama"],
                       "desc": "", "direct": True},
        },
        have_ollama=lambda: True, have_lmstudio=lambda: False, have_omlx=lambda: False,
        have_ollama_model=lambda m: True, have_lmstudio_model=lambda m: False,
        have_omlx_model=lambda m: False,
        _list_ollama_installed=lambda: [], _list_lmstudio_installed=lambda: [],
        _list_omlx_installed=lambda: [],
        _normalize_label=lambda x: x,
    )
    monkeypatch.setitem(sys.modules, "bench", fake_bench)

    class FakeManager:
        def start(self, *, run_id, argv, config_path, env=None):
            pass
        def current_status(self): return None
        def poll(self): pass

    (tmp_path / "bench.config.json").write_text(json.dumps({
        "models": [{"id": "m1", "ollama": "m1:latest"}],
        "agents": ["pi", "direct"], "backends": ["ollama"],
        "iterations": 3, "warmup": 1, "prompt": "x.",
    }))

    controller = WebController(root=tmp_path, results_dir=tmp_path / "results",
                               python_executable=Path("/usr/bin/python3"),
                               process_manager=FakeManager())

    resp = controller.start_run(RunRequest(
        models=["m1"], agents=["pi", "direct"], backends=["ollama"],
        iterations=3, warmup=1, prompt="x.",
        model_entries=[{"id": "m1", "ollama": "m1:latest"}],
    ))

    # 2 agents × 1 model × 1 backend = 2 combos × (3+1) = 8 steps
    assert resp.planned_total == 8


def test_get_run_config_reads_per_run_config_file(tmp_path):
    run_dir = tmp_path / ".bench-web" / "runs" / "20260101-120000"
    run_dir.mkdir(parents=True)
    cfg = {
        "models": [{"id": "m1"}],
        "agents": ["pi"],
        "backends": ["ollama"],
        "iterations": 2,
        "warmup": 0,
        "prompt": "Build it.",
    }
    (run_dir / "bench.config.json").write_text(json.dumps(cfg))

    controller = WebController(
        root=tmp_path,
        results_dir=tmp_path / "results",
        python_executable=Path("/usr/bin/python3"),
    )

    assert controller.get_run_config("20260101-120000") == cfg


def test_get_run_config_raises_key_error_when_no_config_exists(tmp_path):
    controller = WebController(
        root=tmp_path,
        results_dir=tmp_path / "results",
        python_executable=Path("/usr/bin/python3"),
    )

    with pytest.raises(KeyError):
        controller.get_run_config("20260101-000000")


def test_get_run_config_rejects_invalid_run_id(tmp_path):
    controller = WebController(
        root=tmp_path,
        results_dir=tmp_path / "results",
        python_executable=Path("/usr/bin/python3"),
    )

    with pytest.raises(ValueError):
        controller.get_run_config("..")


def test_delete_run_removes_run_dir_and_results_dir(tmp_path):
    run_dir = tmp_path / ".bench-web" / "runs" / "20260101-120000"
    result_dir = tmp_path / "results" / "20260101-120000"
    run_dir.mkdir(parents=True)
    result_dir.mkdir(parents=True)
    (run_dir / "bench.config.json").write_text("{}")
    (result_dir / "results.json").write_text("{}")

    controller = WebController(
        root=tmp_path,
        results_dir=tmp_path / "results",
        python_executable=Path("/usr/bin/python3"),
    )

    controller.delete_run("20260101-120000")

    assert not run_dir.exists()
    assert not result_dir.exists()


def test_delete_run_raises_key_error_for_unknown_run(tmp_path):
    controller = WebController(
        root=tmp_path,
        results_dir=tmp_path / "results",
        python_executable=Path("/usr/bin/python3"),
    )

    with pytest.raises(KeyError):
        controller.delete_run("20260101-000000")


def test_delete_run_rejects_invalid_run_id(tmp_path):
    controller = WebController(
        root=tmp_path,
        results_dir=tmp_path / "results",
        python_executable=Path("/usr/bin/python3"),
    )

    with pytest.raises(ValueError):
        controller.delete_run("..")
