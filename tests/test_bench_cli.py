import bench


def test_viewer_path_uses_existing_cwd_viewer(monkeypatch, tmp_path):
    viewer = tmp_path / "viewer.html"
    viewer.write_text("<html></html>")
    monkeypatch.setattr(bench, "ROOT", tmp_path)
    monkeypatch.setattr(bench, "SOURCE_ROOT", tmp_path / "missing")

    assert bench.viewer_path() == viewer


def test_viewer_path_returns_none_when_viewer_is_not_available(monkeypatch, tmp_path):
    monkeypatch.setattr(bench, "ROOT", tmp_path / "cwd")
    monkeypatch.setattr(bench, "SOURCE_ROOT", tmp_path / "source")

    assert bench.viewer_path() is None
