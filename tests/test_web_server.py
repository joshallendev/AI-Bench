from pathlib import Path
from types import SimpleNamespace
import json
import io
from email.message import Message

import pytest

from ai_bench.web_server import (
    DEFAULT_UI_ENTRY,
    WebServerConfig,
    create_handler,
    validate_server_config,
)


def test_create_handler_binds_controller_and_static_root(tmp_path):
    controller = object()
    handler = create_handler(controller, tmp_path)
    assert handler.controller is controller
    assert handler.static_root == tmp_path


def test_root_serves_current_web_ui(tmp_path):
    ui = tmp_path / DEFAULT_UI_ENTRY
    ui.write_text("<!doctype html><title>v2</title>", encoding="utf-8")
    (tmp_path / "ember-sidebar.html").write_text("<!doctype html><title>v1</title>", encoding="utf-8")

    handler_cls = create_handler(object(), tmp_path)
    handler = object.__new__(handler_cls)
    handler.wfile = io.BytesIO()
    handler.responses = []
    handler.send_response = lambda status: handler.responses.append(("status", status))
    handler.send_header = lambda key, value: handler.responses.append((key, value))
    handler.end_headers = lambda: handler.responses.append(("end", None))

    handler._serve_static("/")

    assert ("status", 200) in handler.responses
    assert b"<title>v2</title>" in handler.wfile.getvalue()


def test_legacy_web_ui_path_serves_current_web_ui(tmp_path):
    ui = tmp_path / DEFAULT_UI_ENTRY
    ui.write_text("<!doctype html><title>v2</title>", encoding="utf-8")
    (tmp_path / "ember-sidebar.html").write_text("<!doctype html><title>v1</title>", encoding="utf-8")

    handler_cls = create_handler(object(), tmp_path)
    handler = object.__new__(handler_cls)
    handler.wfile = io.BytesIO()
    handler.responses = []
    handler.send_response = lambda status: handler.responses.append(("status", status))
    handler.send_header = lambda key, value: handler.responses.append((key, value))
    handler.end_headers = lambda: handler.responses.append(("end", None))

    handler._serve_static("/ember-sidebar.html")

    assert ("status", 200) in handler.responses
    assert b"<title>v2</title>" in handler.wfile.getvalue()


def test_validate_server_config_rejects_multicast_by_default(tmp_path):
    config = WebServerConfig(
        host="224.0.0.1",
        port=8765,
        root=tmp_path,
        results_dir=tmp_path / "results",
        python_executable=Path("/usr/bin/python3"),
    )

    with pytest.raises(ValueError, match="requires --allow-non-loopback"):
        validate_server_config(config)


def test_validate_server_config_allows_loopback_by_default(tmp_path):
    config = WebServerConfig(
        host="127.0.0.1",
        port=8765,
        root=tmp_path,
        results_dir=tmp_path / "results",
        python_executable=Path("/usr/bin/python3"),
    )

    validate_server_config(config)


def test_validate_server_config_allows_localhost_by_default(tmp_path):
    config = WebServerConfig(
        host="localhost",
        port=8765,
        root=tmp_path,
        results_dir=tmp_path / "results",
        python_executable=Path("/usr/bin/python3"),
    )

    validate_server_config(config)


def test_validate_server_config_rejects_arbitrary_hostnames(tmp_path):
    config = WebServerConfig(
        host="example.com",
        port=8765,
        root=tmp_path,
        results_dir=tmp_path / "results",
        python_executable=Path("/usr/bin/python3"),
    )

    with pytest.raises(ValueError, match="Invalid host"):
        validate_server_config(config)


def test_start_run_response_includes_planned_total_over_http(tmp_path):
    class Controller:
        def start_run(self, req):
            return SimpleNamespace(
                run_id="run-1",
                status="running",
                config_path=tmp_path / "config.json",
                planned_total=8,
            )

    handler_cls = create_handler(Controller(), tmp_path)
    handler = object.__new__(handler_cls)
    body = json.dumps({
        "models": ["m1"],
        "agents": ["pi"],
        "backends": ["ollama"],
        "iterations": 1,
        "warmup": 0,
        "prompt": "x",
    }).encode()
    headers = Message()
    headers["Content-Length"] = str(len(body))
    handler.path = "/api/runs"
    handler.headers = headers
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.responses = []
    handler.send_response = lambda status: handler.responses.append(("status", status))
    handler.send_header = lambda key, value: handler.responses.append((key, value))
    handler.end_headers = lambda: handler.responses.append(("end", None))

    handler._route("POST")

    payload = json.loads(handler.wfile.getvalue().decode())

    assert payload["planned_total"] == 8
