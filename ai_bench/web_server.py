import json
import re
import mimetypes
from urllib.parse import parse_qs, urlparse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Iterator

from ai_bench.web_controller import WebController
from ai_bench import package_static_dir


DEFAULT_UI_ENTRY = "bench-web.html"


@dataclass(frozen=True)
class WebServerConfig:
    host: str
    port: int
    root: Path
    results_dir: Path
    python_executable: Path
    static_root: Path | None = None
    allow_non_loopback: bool = False


def validate_server_config(config: WebServerConfig) -> None:
    """Raise ValueError when the server config is unsafe or unusable."""
    import ipaddress

    host = config.host.strip().lower()
    if host in ("localhost", "localhost."):
        return

    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError(f"Invalid host: {config.host!r}")

    if addr.is_loopback:
        return

    if not config.allow_non_loopback:
        raise ValueError(
            f"Binding to {config.host} requires --allow-non-loopback. "
            "Only loopback addresses are allowed by default."
        )


def create_handler(
    controller: WebController,
    static_root: Path,
) -> type[BaseHTTPRequestHandler]:
    """Create a request handler class bound to a controller instance."""
    bound_controller = controller
    bound_static_root = static_root

    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, data: object, status: int = 200) -> None:
            body = json.dumps(data, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, code: int, msg: str) -> None:
            self._send_json({"error": msg}, status=code)

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length", 0))
            return self.rfile.read(length)

        def _route(self, method: str) -> None:
            parsed_url = urlparse(self.path)
            path = parsed_url.path.rstrip("/") or "/"
            query = parse_qs(parsed_url.query)

            # API routes
            if path == "/api/health":
                if method == "GET":
                    self._send_json(Handler.controller.health())  # type: ignore
                else:
                    self._send_error(405, "Method not allowed")
                return

            if path == "/api/config":
                if method == "GET":
                    self._send_json(Handler.controller.get_config())  # type: ignore
                elif method == "PUT":
                    body = self._read_body()
                    try:
                        cfg = json.loads(body)
                        result = Handler.controller.save_config(cfg)  # type: ignore
                        self._send_json(result)
                    except Exception as e:
                        self._send_error(400, str(e))
                else:
                    self._send_error(405, "Method not allowed")
                return

            if path == "/api/detect":
                if method == "GET":
                    self._send_json(Handler.controller.detect())  # type: ignore
                else:
                    self._send_error(405, "Method not allowed")
                return

            if path == "/api/models/installed":
                if method == "GET":
                    self._send_json(Handler.controller.installed_models())  # type: ignore
                else:
                    self._send_error(405, "Method not allowed")
                return

            if path == "/api/models/search":
                if method == "GET":
                    try:
                        backend = (query.get("backend") or [""])[0]
                        q = (query.get("q") or [""])[0]
                        self._send_json(Handler.controller.search_models(backend, q))  # type: ignore
                    except Exception as e:
                        self._send_error(400, str(e))
                else:
                    self._send_error(405, "Method not allowed")
                return

            if path == "/api/models/preflight":
                if method == "POST":
                    try:
                        data = json.loads(self._read_body())
                        result = Handler.controller.preflight_selection(data)  # type: ignore
                        self._send_json(result)
                    except Exception as e:
                        self._send_error(400, str(e))
                else:
                    self._send_error(405, "Method not allowed")
                return

            if path == "/api/runs":
                if method == "GET":
                    self._send_json(Handler.controller.list_runs())  # type: ignore
                elif method == "POST":
                    body = self._read_body()
                    try:
                        from ai_bench.web_controller import RunRequest
                        data = json.loads(body)
                        req = RunRequest(
                            models=data["models"],
                            agents=data["agents"],
                            backends=data["backends"],
                            iterations=data.get("iterations", 3),
                            warmup=data.get("warmup", 1),
                            prompt=data.get("prompt", ""),
                            skip_install=data.get("skip_install", True),
                            model_entries=data.get("model_entries"),
                        )
                        resp = Handler.controller.start_run(req)  # type: ignore
                        self._send_json({
                            "run_id": resp.run_id,
                            "status": resp.status,
                            "config_path": str(resp.config_path),
                            "planned_total": resp.planned_total,
                        })
                    except Exception as e:
                        self._send_error(400, str(e))
                else:
                    self._send_error(405, "Method not allowed")
                return

            # /api/runs/current/stop
            if path == "/api/runs/current/stop":
                if method == "POST":
                    try:
                        result = Handler.controller.stop_current_run()  # type: ignore
                        self._send_json(result)
                    except Exception as e:
                        self._send_error(400, str(e))
                else:
                    self._send_error(405, "Method not allowed")
                return

            # /api/runs/{run_id}/results
            m = re.match(r"^/api/runs/([^/]+)/results$", path)
            if m:
                run_id = m.group(1)
                if method == "GET":
                    try:
                        result = Handler.controller.get_results(run_id)  # type: ignore
                        self._send_json(result)
                    except KeyError:
                        self._send_error(404, f"Run {run_id} not found")
                else:
                    self._send_error(405, "Method not allowed")
                return

            # /api/runs/{run_id}/raw-output?index=N
            m = re.match(r"^/api/runs/([^/]+)/raw-output$", path)
            if m:
                run_id = m.group(1)
                if method == "GET":
                    try:
                        index = int((query.get("index") or ["0"])[0])
                        result = Handler.controller.get_raw_output(run_id, index)  # type: ignore
                        self._send_json(result)
                    except ValueError as e:
                        self._send_error(400, str(e))
                    except (KeyError, IndexError):
                        self._send_error(404, f"Raw output for run {run_id} not found")
                else:
                    self._send_error(405, "Method not allowed")
                return

            # /api/runs/{run_id}/config
            m = re.match(r"^/api/runs/([^/]+)/config$", path)
            if m:
                run_id = m.group(1)
                if method == "GET":
                    try:
                        result = Handler.controller.get_run_config(run_id)  # type: ignore
                        self._send_json(result)
                    except ValueError as e:
                        self._send_error(400, str(e))
                    except KeyError:
                        self._send_error(404, f"Run {run_id} config not found")
                else:
                    self._send_error(405, "Method not allowed")
                return

            # /api/runs/{run_id}
            m = re.match(r"^/api/runs/([^/]+)$", path)
            if m:
                run_id = m.group(1)
                if method == "GET":
                    try:
                        result = Handler.controller.get_run(run_id)  # type: ignore
                        self._send_json(result)
                    except KeyError:
                        self._send_error(404, f"Run {run_id} not found")
                elif method == "DELETE":
                    try:
                        Handler.controller.delete_run(run_id)  # type: ignore
                        self._send_json({"ok": True})
                    except ValueError as e:
                        self._send_error(400, str(e))
                    except RuntimeError as e:
                        self._send_error(409, str(e))
                    except KeyError:
                        self._send_error(404, f"Run {run_id} not found")
                else:
                    self._send_error(405, "Method not allowed")
                return

            # /api/events - SSE stream
            if path == "/api/events":
                if method == "GET":
                    self._stream_events()
                else:
                    self._send_error(405, "Method not allowed")
                return

            # Static file serving
            self._serve_static(path)

        def _stream_events(self) -> None:
            from ai_bench.web_events import encode_sse

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            try:
                for event in Handler.controller.event_stream():  # type: ignore
                    self.wfile.write(encode_sse(event, event_name="message"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _serve_static(self, path: str) -> None:
            if path in {"/", "/ember-sidebar.html"}:
                path = f"/{DEFAULT_UI_ENTRY}"

            try:
                static_root = Handler.static_root.resolve()  # type: ignore
                file_path = (static_root / path[1:]).resolve()
                file_path.relative_to(static_root)
            except (ValueError, OSError):
                self._send_error(403, "Forbidden")
                return

            if not file_path.is_file():
                self._send_error(404, "Not found")
                return

            content = file_path.read_bytes()
            ctype, _ = mimetypes.guess_type(str(file_path))
            if not ctype:
                ctype = "application/octet-stream"

            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self) -> None:
            self._route("GET")

        def do_POST(self) -> None:
            self._route("POST")

        def do_PUT(self) -> None:
            self._route("PUT")

        def do_DELETE(self) -> None:
            self._route("DELETE")

        def log_message(self, format: str, *args: object) -> None:
            pass

    Handler.controller = bound_controller
    Handler.static_root = bound_static_root
    return Handler


def serve(config: WebServerConfig) -> None:
    """Run the HTTP server until interrupted."""
    import socketserver

    from ai_bench.web_process import BenchmarkProcessManager
    from ai_bench.web_controller import WebController

    controller = WebController(
        root=config.root,
        results_dir=config.results_dir,
        python_executable=config.python_executable,
        process_manager=BenchmarkProcessManager(root=config.root),
    )

    handler = create_handler(controller, config.static_root or package_static_dir())

    class ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
        daemon_threads = True
        allow_reuse_address = True

    server = ThreadingTCPServer(
        (config.host, config.port),
        handler,
        bind_and_activate=False,
    )
    server.server_bind()
    server.server_activate()

    print(f"AI-Bench web controller listening on http://{config.host}:{config.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()
