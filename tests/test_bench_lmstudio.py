import bench


def test_have_lmstudio_model_accepts_runtime_alias_from_lms_ls(monkeypatch, tmp_path):
    monkeypatch.setattr(bench.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(bench, "_lmstudio_dir_complete", lambda path: False)
    monkeypatch.setattr(
        bench,
        "_list_lmstudio_installed",
        lambda: [{"id": "qwen/qwen3-coder-next", "size": "44.86 GB"}],
    )

    assert bench.have_lmstudio_model("qwen/qwen3-coder-next") is True


def test_have_lmstudio_model_still_rejects_unknown_alias(monkeypatch, tmp_path):
    monkeypatch.setattr(bench.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(bench, "_lmstudio_dir_complete", lambda path: False)
    monkeypatch.setattr(bench, "_list_lmstudio_installed", lambda: [])

    assert bench.have_lmstudio_model("missing/model") is False


def test_have_lmstudio_model_rejects_partial_download_even_when_alias_lists(monkeypatch, tmp_path):
    model_dir = tmp_path / ".lmstudio" / "models" / "qwen" / "qwen3-coder-next"
    model_dir.mkdir(parents=True)
    (model_dir / "model.safetensors.part").write_bytes(b"incomplete")
    monkeypatch.setattr(bench.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        bench,
        "_list_lmstudio_installed",
        lambda: [{"id": "qwen/qwen3-coder-next", "size": "44.86 GB"}],
    )

    assert bench.have_lmstudio_model("qwen/qwen3-coder-next") is False
