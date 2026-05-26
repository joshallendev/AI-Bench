from pathlib import Path

import pytest

from ai_bench.web_process import BenchmarkProcessManager, ProcessEvent


class FakeProcess:
    def __init__(self, pid=1234):
        self.pid = pid
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.stdout = []
        self.stderr = []

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            raise TimeoutError("still running")
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9


def test_process_manager_start_records_running_status(tmp_path):
    created = []

    def popen_factory(argv, **kwargs):
        created.append((argv, kwargs))
        return FakeProcess(pid=9876)

    manager = BenchmarkProcessManager(root=tmp_path, popen_factory=popen_factory)

    status = manager.start(
        run_id="20260522-143012",
        argv=["python3", "bench.py"],
        config_path=tmp_path / "config.json",
    )

    assert status.run_id == "20260522-143012"
    assert status.status == "running"
    assert status.pid == 9876
    assert status.config_path == tmp_path / "config.json"
    assert created[0][0] == ["python3", "bench.py"]
    assert created[0][1]["cwd"] == str(tmp_path)
    assert created[0][1]["text"] is True
    assert created[0][1]["start_new_session"] is True


def test_process_manager_rejects_concurrent_runs(tmp_path):
    manager = BenchmarkProcessManager(
        root=tmp_path,
        popen_factory=lambda argv, **kwargs: FakeProcess(),
    )
    manager.start(run_id="one", argv=["python3", "bench.py"], config_path=tmp_path / "one.json")

    with pytest.raises(RuntimeError, match="already active"):
        manager.start(run_id="two", argv=["python3", "bench.py"], config_path=tmp_path / "two.json")


def test_process_manager_stop_current_marks_run_cancelled(tmp_path):
    process = FakeProcess()
    manager = BenchmarkProcessManager(root=tmp_path, popen_factory=lambda argv, **kwargs: process)
    manager.start(run_id="one", argv=["python3", "bench.py"], config_path=tmp_path / "one.json")

    status = manager.stop_current(timeout_s=0)

    assert process.terminated is True
    assert status.status == "cancelled"
    assert status.returncode == -15


def test_apply_event_to_status_updates_progress_total():
    process = FakeProcess()
    manager = BenchmarkProcessManager(root=Path("root"), popen_factory=lambda argv, **kwargs: process)
    manager.start(run_id="one", argv=["python3", "bench.py"], config_path=Path("one.json"))

    manager._apply_event_to_status({"type": "plan", "total_runs": 18})

    status = manager.current_status()
    assert status.progress_total == 18


def test_apply_event_to_status_updates_progress_done():
    process = FakeProcess()
    manager = BenchmarkProcessManager(root=Path("root"), popen_factory=lambda argv, **kwargs: process)
    manager.start(run_id="one", argv=["python3", "bench.py"], config_path=Path("one.json"))

    manager._apply_event_to_status({"type": "plan", "total_runs": 12})
    manager._apply_event_to_status({"type": "iteration_start", "label": "pi+ollama+qwen3", "done": 3, "total": 12})

    status = manager.current_status()
    assert status.progress_done == 3
    assert status.progress_total == 12
    assert status.last_log == "pi+ollama+qwen3"


def test_apply_event_to_status_updates_results_path():
    process = FakeProcess()
    manager = BenchmarkProcessManager(root=Path("root"), popen_factory=lambda argv, **kwargs: process)
    manager.start(run_id="one", argv=["python3", "bench.py"], config_path=Path("one.json"))

    manager._apply_event_to_status({"type": "results", "results_path": "/tmp/results.json"})

    status = manager.current_status()
    assert status.results_path == Path("/tmp/results.json")


def test_apply_event_to_status_noop_when_no_current():
    manager = BenchmarkProcessManager(root=Path("root"))
    manager._apply_event_to_status({"type": "plan", "total_runs": 9})
    assert manager.current_status() is None


def test_process_manager_poll_marks_completed_run(tmp_path):
    process = FakeProcess()
    manager = BenchmarkProcessManager(root=tmp_path, popen_factory=lambda argv, **kwargs: process)
    manager.start(run_id="one", argv=["python3", "bench.py"], config_path=Path("one.json"))
    process.returncode = 0

    status = manager.poll()

    assert status.status == "completed"
    assert status.returncode == 0


def test_iter_events_yields_final_status_after_stdout_closes(tmp_path):
    process = FakeProcess()
    process.stdout = [
        'AI_BENCH_EVENT {"type":"plan","total_runs":1}\n',
    ]
    process.returncode = 1
    manager = BenchmarkProcessManager(root=tmp_path, popen_factory=lambda argv, **kwargs: process)
    manager.start(run_id="one", argv=["python3", "bench.py"], config_path=Path("one.json"))

    events = list(manager.iter_events())

    assert [event.type for event in events] == ["plan", "status"]
    assert events[-1].payload == {
        "type": "status",
        "status": "failed",
        "returncode": 1,
    }


def test_results_path_not_lost_when_status_updated_concurrently(tmp_path):
    """_update_status must not race with _apply_event_to_status(results)."""
    import threading
    process = FakeProcess()
    manager = BenchmarkProcessManager(root=tmp_path, popen_factory=lambda argv, **kw: process)
    manager.start(run_id="race", argv=["python3", "bench.py"], config_path=Path("c.json"))

    barrier = threading.Barrier(2)
    results = []

    def apply_results():
        barrier.wait()
        manager._apply_event_to_status({"type": "results", "results_path": "/tmp/r.json"})

    def poll_done():
        barrier.wait()
        process.returncode = 0
        results.append(manager.poll())

    t1 = threading.Thread(target=apply_results)
    t2 = threading.Thread(target=poll_done)
    t1.start(); t2.start()
    t1.join(); t2.join()

    # results_path must survive regardless of which thread won
    assert manager.current_status().results_path == Path("/tmp/r.json")


def test_two_concurrent_subscribers_each_receive_all_events(tmp_path):
    """Fan-out: both subscribers get all events from when they connect."""
    import threading
    import queue

    process = FakeProcess()
    process.stdout = [
        'AI_BENCH_EVENT {"type":"plan","total_runs":2}\n',
        'AI_BENCH_EVENT {"type":"iteration_complete","done":1,"total":2}\n',
        'AI_BENCH_EVENT {"type":"iteration_complete","done":2,"total":2}\n',
    ]
    process.returncode = 0

    manager = BenchmarkProcessManager(root=tmp_path, popen_factory=lambda argv, **kw: process)
    manager.start(run_id="fan", argv=["python3", "bench.py"], config_path=Path("c.json"))

    # Manually subscribe and collect events to test fan-out
    q1 = manager._subscribe()
    q2 = manager._subscribe()

    # Wait for stdout to complete
    import time
    time.sleep(0.3)

    # Read all events from both queues
    events1 = []
    events2 = []
    
    # Drain q1
    while True:
        try:
            events1.append(q1.get_nowait())
        except queue.Empty:
            break
    
    # Drain q2
    while True:
        try:
            events2.append(q2.get_nowait())
        except queue.Empty:
            break

    # Both queues should have received the same events
    assert [e.type for e in events1] == [e.type for e in events2]
    
    # Both should receive plan and 2 iteration_complete events
    assert len(events1) >= 3
    assert events1[0].type == "plan"
    assert events1[1].type == "iteration_complete"
    assert events1[2].type == "iteration_complete"
    
    manager._unsubscribe(q1)
    manager._unsubscribe(q2)


def test_process_manager_streams_human_readable_stdout_and_stderr_logs(tmp_path):
    import queue

    process = FakeProcess()
    process.stdout = [
        "Plan: 1 combo x 2 runs = 2 total\n",
        'AI_BENCH_EVENT {"type":"plan","total_runs":2}\n',
    ]
    process.stderr = ["warning: slow backend\n"]
    process.returncode = 0

    manager = BenchmarkProcessManager(root=tmp_path, popen_factory=lambda argv, **kw: process)
    q = manager._subscribe()
    manager.start(run_id="logs", argv=["python3", "bench.py"], config_path=Path("c.json"))

    import time
    time.sleep(0.3)

    events = []
    while True:
        try:
            events.append(q.get_nowait())
        except queue.Empty:
            break

    log_events = [event.payload for event in events if event.type == "log"]
    assert {"type": "log", "stream": "stdout", "line": "Plan: 1 combo x 2 runs = 2 total"} in log_events
    assert {"type": "log", "stream": "stderr", "line": "warning: slow backend"} in log_events
    assert all("AI_BENCH_EVENT" not in event["line"] for event in log_events)

    manager._unsubscribe(q)


def test_legacy_progress_line_is_not_also_broadcast_as_log(tmp_path):
    import queue
    import time

    process = FakeProcess()
    process.stdout = ["•     [2/6] starting pi+ollama+qwen3 timed iter-1\n"]
    process.returncode = 0

    manager = BenchmarkProcessManager(root=tmp_path, popen_factory=lambda argv, **kw: process)
    q = manager._subscribe()
    manager.start(run_id="legacy", argv=["python3", "bench.py"], config_path=Path("c.json"))

    time.sleep(0.3)
    events = []
    while True:
        try:
            events.append(q.get_nowait())
        except queue.Empty:
            break

    assert any(event.type == "iteration_start" for event in events)
    assert not any(
        event.type == "log" and "[2/6] starting" in event.payload["line"]
        for event in events
    )
    manager._unsubscribe(q)


def test_late_subscriber_gets_future_events_only(tmp_path):
    """A subscriber that connects after some events are broadcast misses past events."""
    # (This is the expected behaviour for SSE — no replay.)
    process = FakeProcess()
    process.stdout = []
    process.returncode = 0

    manager = BenchmarkProcessManager(root=tmp_path, popen_factory=lambda argv, **kw: process)
    manager.start(run_id="late", argv=["python3", "bench.py"], config_path=Path("c.json"))
    # Emit one event before the subscriber connects
    manager._broadcast(ProcessEvent(run_id="late", type="early", payload={}))

    q = manager._subscribe()
    # The late subscriber's queue should be empty (didn't get "early")
    import queue as _queue
    with pytest.raises(_queue.Empty):
        q.get_nowait()
    manager._unsubscribe(q)


def test_iter_events_replays_recent_events_for_late_sse_subscriber(tmp_path):
    process = FakeProcess()
    process.stdout = ['AI_BENCH_EVENT {"type":"plan","total_runs":2}\n']
    process.returncode = None

    manager = BenchmarkProcessManager(root=tmp_path, popen_factory=lambda argv, **kw: process)
    manager.start(run_id="replay", argv=["python3", "bench.py"], config_path=Path("c.json"))

    import time
    time.sleep(0.2)

    events = manager.iter_events()
    first = next(events)

    assert first.type == "plan"
    assert first.payload["total_runs"] == 2
