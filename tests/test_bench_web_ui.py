import subprocess

from ai_bench import package_static_dir
from ai_bench.web_server import DEFAULT_UI_ENTRY


def test_bench_web_ui_node_tests_pass():
    result = subprocess.run(
        ["node", "--test", "tests/bench_web_ui.test.mjs"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_initial_html_does_not_ship_mock_dashboard_data():
    html = (package_static_dir() / DEFAULT_UI_ENTRY).read_text()

    assert '<div class="stat-strip" id="stat-strip"></div>' in html
    assert '<div class="matrix-scroll"></div>' in html
    assert '<tbody id="leaderboard-body"></tbody>' in html
    assert '<div class="prompt-body"></div>' in html
    assert "52.1" not in html
    assert "qwen3 &times; 3 agents" not in html
