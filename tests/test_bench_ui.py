import importlib.util
import sys
from pathlib import Path


def load_bench_ui():
    module_name = "bench_ui_under_test"
    module_path = Path(__file__).resolve().parents[1] / "bench-ui.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class FakeScreen:
    def addstr(self, *args):
        pass

    def attron(self, *args):
        pass

    def attroff(self, *args):
        pass


def make_ui(module):
    ui = module.TUI.__new__(module.TUI)
    ui.stdscr = FakeScreen()
    ui.config = module.Config.from_dict({
        "models": [
            {"id": "m1", "omlx": "org/m1"},
            {"id": "m2", "omlx": "org/m2"},
        ],
        "agents": [],
        "backends": [],
        "iterations": 1,
        "warmup": 0,
        "prompt": "hello",
    })
    ui.tab_index = 0
    ui.tabs = ["models", "agents", "backends", "iterations", "warmup", "prompt"]
    ui.selected_model_idx = 0
    ui.available_models = []
    ui.selected_agent_idx = 0
    ui.available_agents = ["pi", "opencode"]
    ui.selected_backend_idx = 0
    ui.available_backends = ["ollama", "lmstudio", "omlx"]
    ui.editing_prompt = False
    ui.prompt_cursor = 0
    ui.prompt_offset = 0
    ui.status_message = ""
    ui.error_message = ""
    return ui


def test_global_save_key_reaches_save_and_run():
    module = load_bench_ui()
    ui = make_ui(module)
    called = []
    ui.save_and_run = lambda: called.append(True) or True

    assert ui.handle_key(ord("s")) is True
    assert called == [True]


def test_down_key_selects_model_instead_of_changing_tabs():
    module = load_bench_ui()
    ui = make_ui(module)

    assert ui.handle_key(module.curses.KEY_DOWN) is False

    assert ui.tab_index == 0
    assert ui.selected_model_idx == 1


def test_agent_toggle_uses_agent_selection_index_not_model_index():
    module = load_bench_ui()
    ui = make_ui(module)
    ui.tab_index = 1
    ui.selected_model_idx = 5
    ui.selected_agent_idx = 0

    assert ui.handle_key(ord(" ")) is False

    assert ui.config.agents == ["pi"]


def test_draw_content_calls_agent_and_backend_drawers_with_matching_signatures(monkeypatch):
    module = load_bench_ui()
    monkeypatch.setattr(module.curses, "color_pair", lambda n: n)
    ui = make_ui(module)

    ui.tab_index = 1
    ui.draw_content(0, 80, 24)
    ui.tab_index = 2
    ui.draw_content(0, 80, 24)


def test_arrow_keys_adjust_iterations_and_warmup():
    module = load_bench_ui()
    ui = make_ui(module)

    ui.tab_index = 3
    ui.handle_key(module.curses.KEY_RIGHT)
    assert ui.config.iterations == 2
    ui.handle_key(module.curses.KEY_LEFT)
    assert ui.config.iterations == 1

    ui.tab_index = 4
    ui.handle_key(module.curses.KEY_RIGHT)
    assert ui.config.warmup == 1
    ui.handle_key(module.curses.KEY_LEFT)
    assert ui.config.warmup == 0


def test_escape_exits_prompt_edit_mode_without_exiting_app():
    module = load_bench_ui()
    ui = make_ui(module)
    ui.editing_prompt = True

    assert ui.handle_key(27) is False
    assert ui.editing_prompt is False
