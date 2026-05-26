import importlib.util
import sys
from pathlib import Path


def load_config_editor():
    module_name = "config_editor_under_test"
    module_path = Path(__file__).resolve().parents[1] / "config-editor.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_load_config_returns_deep_copy_of_default_when_file_missing(monkeypatch, tmp_path):
    module = load_config_editor()
    monkeypatch.setattr(module, "DEFAULT_CONFIG_PATH", tmp_path / "missing.json")

    config = module.load_config()
    config["models"].append({"id": "extra"})

    assert module.DEFAULT_CONFIG["models"] == [
        {"id": "qwen3-1.7b", "ollama": "qwen3:1.7b", "omlx": "Qwen/Qwen2-1.5B"}
    ]
