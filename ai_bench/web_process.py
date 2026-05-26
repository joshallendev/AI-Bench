import os
import queue
import signal
import subprocess
import threading
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class RunStatus:
    run_id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    pid: int | None
    config_path: Path
    results_path: Path | None
    started_at: str
    finished_at: str | None = None
    returncode: int | None = None
    progress_done: int = 0
    progress_total: int = 0
    last_log: str = ""
    log_path: Path | None = None


@dataclass(frozen=True)
class ProcessEvent:
    run_id: str
    type: str
    payload: dict[str, object]


class BenchmarkProcessManager:
    def __init__(
        self,
        *,
        root: Path,
        popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._root = root
        self._popen = popen_factory
        self._clock = clock or datetime.now
        self._process: subprocess.Popen[str] | None = None
        self._current: RunStatus | None = None
        self._subscribers: list[queue.SimpleQueue[ProcessEvent]] = []
        self._subscribers_lock = threading.Lock()
        self._recent_events: deque[ProcessEvent] = deque(maxlen=500)
        self._condition = threading.Condition(threading.RLock())
        self._final_event_emitted = False
        self._stdout_thread: threading.Thread | None = None

    def start(
        self,
        *,
        run_id: str,
        argv: list[str],
        config_path: Path,
        env: Mapping[str, str] | None = None,
    ) -> RunStatus:
        """Start a benchmark. Raise RuntimeError if one is already active."""
        if self._current is not None and self._current.status == "running":
            raise RuntimeError(
                f"A benchmark is already active (run_id={self._current.run_id})"
            )

        now = self._clock().isoformat()
        log_path = self._root / ".bench-web" / "runs" / run_id / "bench.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("")
        self._process = self._popen(
            argv,
            cwd=str(self._root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            env=dict(os.environ, **env) if env else None,
        )

        self._current = RunStatus(
            run_id=run_id,
            status="running",
            pid=self._process.pid,
            config_path=config_path,
            results_path=None,
            started_at=now,
            log_path=log_path,
        )
        self._recent_events.clear()
        self._final_event_emitted = False
        self._stdout_thread = _start_reader_thread(
            self._process.stdout,
            log_path=log_path,
            on_line=self._handle_stdout_line,
            prefix="",
        )
        _start_reader_thread(
            self._process.stderr,
            log_path=log_path,
            on_line=lambda line: self._handle_log_line(line, stream="stderr"),
            prefix="[stderr] ",
        )
        return self._current

    def stop_current(self, *, timeout_s: float = 5.0) -> RunStatus:
        """Terminate the active process group and return the updated status."""
        if self._current is None or self._process is None:
            raise RuntimeError("No active run to stop")

        proc = self._process
        killed = False
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            killed = True
        except (ProcessLookupError, OSError):
            pass
        if not killed:
            proc.terminate()

        if timeout_s > 0:
            try:
                proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                killed2 = False
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    killed2 = True
                except (ProcessLookupError, OSError):
                    pass
                if not killed2:
                    proc.kill()
                proc.wait(timeout=5)

        return self._update_status(proc.returncode, "cancelled")

    def current_status(self) -> RunStatus | None:
        """Return the current active or last known run status."""
        return self._current

    def _subscribe(self, *, replay_recent: bool = False) -> queue.SimpleQueue[ProcessEvent]:
        """Allocate a new per-subscriber queue and register it."""
        q: queue.SimpleQueue[ProcessEvent] = queue.SimpleQueue()
        with self._subscribers_lock:
            if replay_recent:
                for event in self._recent_events:
                    if self._current and event.run_id == self._current.run_id:
                        q.put(event)
            self._subscribers.append(q)
        return q

    def _unsubscribe(self, q: queue.SimpleQueue[ProcessEvent]) -> None:
        """Deregister a subscriber queue (idempotent)."""
        with self._subscribers_lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def _broadcast(self, event: ProcessEvent) -> None:
        """Put event into every registered subscriber queue and wake waiters."""
        with self._subscribers_lock:
            self._recent_events.append(event)
            for q in self._subscribers:
                q.put(event)
        with self._condition:
            self._condition.notify_all()

    def iter_events(self) -> Iterator[ProcessEvent]:
        """Yield parsed events from a dedicated per-subscriber queue; safe for concurrent callers."""
        if self._process is None:
            return
        q = self._subscribe(replay_recent=True)
        try:
            while True:
                with self._condition:
                    while q.empty():
                        status = self.poll()
                        if status and status.status != "running":
                            break
                        self._condition.wait(timeout=0.25)
                try:
                    yield q.get_nowait()
                except queue.Empty:
                    return  # process finished and queue is drained
        finally:
            self._unsubscribe(q)


    def poll(self) -> RunStatus | None:
        """Refresh process completion state and return current status."""
        if self._current is None or self._process is None:
            return self._current

        rc = self._process.poll()
        if rc is not None:
            if self._stdout_thread and self._stdout_thread.is_alive():
                self._stdout_thread.join(timeout=0.05)
            if self._stdout_thread and self._stdout_thread.is_alive():
                return self._current
            status = "completed" if rc == 0 else "failed"
            return self._update_status(rc, status)

        return self._current

    def _apply_event_to_status(self, event: dict[str, object]) -> None:
        """Update current RunStatus fields from a parsed progress event."""
        if self._current is None:
            return

        etype = event.get("type", "")
        payload = event

        # Update progress_total from plan events
        if etype == "plan":
            with self._condition:
                self._current = replace(
                    self._current,
                    progress_done=self._current.progress_done,
                    progress_total=int(payload.get("total_runs", self._current.progress_total)),
                    last_log=payload.get("label", self._current.last_log) or self._current.last_log,
                )
            return

        # Update progress_done from iteration events
        if etype in ("iteration_start", "iteration_complete"):
            with self._condition:
                done = payload.get("done", self._current.progress_done)
                total = payload.get("total", self._current.progress_total)
                self._current = replace(
                    self._current,
                    progress_done=int(done),
                    progress_total=int(total) if total else self._current.progress_total,
                    last_log=payload.get("label", self._current.last_log) or self._current.last_log,
                )
            return

        # Update results_path from results events
        if etype == "results":
            rpath = payload.get("results_path")
            with self._condition:
                self._current = replace(
                    self._current,
                    results_path=Path(rpath) if rpath else self._current.results_path,
                    last_log=payload.get("label", self._current.last_log) or self._current.last_log,
                )
            return

        # For any other event type, just update last_log if there's a label
        label = payload.get("label", "")
        if label:
            with self._condition:
                self._current = replace(
                    self._current,
                    last_log=str(label),
                )

    def _update_status(
        self,
        returncode: int | None,
        status: str,
    ) -> RunStatus:
        now = self._clock().isoformat()
        final_event = None
        with self._condition:
            self._current = replace(
                self._current,
                status=status,  # type: ignore
                finished_at=now,
                returncode=returncode,
            )
            if not self._final_event_emitted:
                self._final_event_emitted = True
                final_event = ProcessEvent(
                    run_id=self._current.run_id,
                    type="status",
                    payload={
                        "type": "status",
                        "status": self._current.status,
                        "returncode": self._current.returncode,
                    },
                )
        if final_event:
            self._broadcast(final_event)
        return self._current

    def _handle_stdout_line(self, line: str) -> None:
        """Parse one stdout line into status and SSE events."""
        from ai_bench.web_events import parse_bench_progress_line

        clean_line = line.rstrip()
        parsed = parse_bench_progress_line(clean_line)
        if not parsed:
            if not clean_line.startswith("AI_BENCH_EVENT "):
                self._handle_log_line(line, stream="stdout")
            return
        if not self._current:
            return

        self._apply_event_to_status(parsed)
        self._broadcast(ProcessEvent(
            run_id=self._current.run_id,
            type=parsed.get("type", "message"),
            payload=parsed,
        ))

    def _handle_log_line(self, line: str, *, stream: str) -> None:
        """Broadcast one human-readable process output line."""
        if not self._current:
            return
        text = line.rstrip("\n")
        if not text:
            return
        self._broadcast(ProcessEvent(
            run_id=self._current.run_id,
            type="log",
            payload={
                "type": "log",
                "stream": stream,
                "line": text,
            },
        ))


def _drain_fd(fd: object) -> None:
    """Consume all remaining lines from *fd* so the child can't block on a full pipe."""
    try:
        for _ in fd:  # type: ignore[unused-ignore]
            pass
    except Exception:
        pass


def _start_reader_thread(
    fd: object,
    *,
    log_path: Path,
    on_line: Callable[[str], None] | None,
    prefix: str,
) -> threading.Thread:
    """Drain a child stream in the background and append it to the run log."""
    thread = threading.Thread(
        target=_read_fd_to_log,
        args=(fd, log_path, on_line, prefix),
        daemon=True,
    )
    thread.start()
    return thread


def _read_fd_to_log(
    fd: object,
    log_path: Path,
    on_line: Callable[[str], None] | None,
    prefix: str,
) -> None:
    try:
        with log_path.open("a") as log:
            for line in fd:  # type: ignore[unused-ignore]
                log.write(prefix + line)
                log.flush()
                if on_line:
                    on_line(line)
    except Exception:
        pass
