from pathlib import Path

import bench


def test_list_omlx_installed_uses_configured_model_dirs(monkeypatch, tmp_path):
    settings_dir = tmp_path / ".omlx"
    configured_dir = tmp_path / "lmstudio-models"
    model_dir = configured_dir / "mlx-community" / "Qwen3.6-27B-6bit"
    model_dir.mkdir(parents=True)
    (model_dir / "model.safetensors").write_bytes(b"x")
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        f'{{"model": {{"model_dirs": ["{configured_dir}"]}}}}'
    )
    monkeypatch.setattr(bench.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(bench, "_omlx_api_models", lambda: [])

    assert bench._list_omlx_installed() == [
        {
            "id": "Qwen3.6-27B-6bit",
            "hf_id": "mlx-community/Qwen3.6-27B-6bit",
            "size": "0 MB",
        }
    ]


def test_have_omlx_model_checks_configured_model_dirs(monkeypatch, tmp_path):
    settings_dir = tmp_path / ".omlx"
    configured_dir = tmp_path / "models"
    model_dir = configured_dir / "gemma-4-e4b-8bit"
    model_dir.mkdir(parents=True)
    (model_dir / "weights.safetensors").write_bytes(b"x")
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        f'{{"model": {{"model_dirs": ["{configured_dir}"]}}}}'
    )
    monkeypatch.setattr(bench.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(bench, "_omlx_api_models", lambda: [])
    monkeypatch.setattr(bench, "have_omlx", lambda: True)

    assert bench.have_omlx_model("gemma-4-e4b-8bit") is True


def test_have_omlx_model_accepts_huggingface_repo_ids(monkeypatch):
    monkeypatch.setattr(bench, "have_omlx", lambda: True)
    monkeypatch.setattr(
        bench,
        "_list_omlx_installed",
        lambda: [{
            "id": "Qwen3-Coder-Next-MLX-4bit",
            "hf_id": "mlx-community/Qwen3-Coder-Next-MLX-4bit",
            "size": "12 GB",
        }],
    )

    assert bench.have_omlx_model("mlx-community/Qwen3-Coder-Next-MLX-4bit") is True


def test_list_omlx_installed_ignores_configured_gguf_dirs(monkeypatch, tmp_path):
    settings_dir = tmp_path / ".omlx"
    configured_dir = tmp_path / "lmstudio-models"
    model_dir = configured_dir / "lmstudio-community" / "Qwen3.6-27B-GGUF"
    model_dir.mkdir(parents=True)
    (model_dir / "model.gguf").write_bytes(b"x")
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        f'{{"model": {{"model_dirs": ["{configured_dir}"]}}}}'
    )
    monkeypatch.setattr(bench.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(bench, "_omlx_api_models", lambda: [])

    assert bench._list_omlx_installed() == []
