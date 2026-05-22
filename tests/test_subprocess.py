import os
import sys
from bench import run_agent_streamed


class TestRunAgentStreamed:
    def test_stdout_and_exit_zero(self):
        result = run_agent_streamed(
            [sys.executable, "-c", "print('hello')"],
            env=os.environ.copy(),
            total_timeout=10,
        )
        assert result["rc"] == 0
        assert "hello" in result["stdout"]
        assert result["wall_s"] >= 0
        assert result["end_reason"] in ("exit", "killed")

    def test_stderr_and_nonzero_exit(self):
        result = run_agent_streamed(
            [sys.executable, "-c", "import sys; sys.stderr.write('err\\n'); sys.exit(42)"],
            env=os.environ.copy(),
            total_timeout=10,
        )
        assert result["rc"] == 42
        assert "err" in result["stderr"]

    def test_timeout_kills_process(self):
        result = run_agent_streamed(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            env=os.environ.copy(),
            total_timeout=2,
        )
        assert result["wall_s"] < 5

    def test_ttft_recorded(self):
        result = run_agent_streamed(
            [sys.executable, "-c", "import sys; sys.stdout.write('A')"],
            env=os.environ.copy(),
            total_timeout=10,
        )
        assert result["ttft_s"] is not None
        assert result["ttft_s"] >= 0

    def test_env_variables_passed(self):
        env = os.environ.copy()
        env["BENCH_TEST_VAR"] = "works"
        result = run_agent_streamed(
            [sys.executable, "-c", "import os; print(os.environ['BENCH_TEST_VAR'])"],
            env=env,
            total_timeout=10,
        )
        assert result["rc"] == 0
        assert "works" in result["stdout"]
