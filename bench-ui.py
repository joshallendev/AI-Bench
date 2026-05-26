#!/usr/bin/env python3
"""
bench-ui.py - TUI for AI-Bench configuration

Interactive terminal interface for configuring and running AI-Bench benchmarks.
"""

import json
import curses
import sys
from copy import deepcopy
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

ROOT = Path(__file__).parent.resolve()
DEFAULT_CONFIG_PATH = ROOT / "bench.config.json"
DEFAULT_CONFIG = {
    "models": [
        { "id": "qwen3-1.7b", "ollama": "qwen3:1.7b", "omlx": "Qwen/Qwen2-1.5B" }
    ],
    "agents":   ["pi"],
    "backends": ["ollama"],
    "iterations": 1,
    "warmup": 0,
    "prompt": "Write a simple hello world program."
}


# Model detection - check available models from each backend
def detect_models() -> dict[str, list[str]]:
    """Detect available models from each backend."""
    models = {"ollama": [], "lmstudio": [], "omlx": []}
    
    # Check ollama
    try:
        import urllib.request
        import json as json_mod
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=2) as r:
            data = json_mod.loads(r.read().decode())
            models["ollama"] = [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        pass
    
    # Check oMLX
    try:
        import urllib.request
        import json as json_mod
        # Try without auth first
        req = urllib.request.Request("http://localhost:8000/v1/models")
        with urllib.request.urlopen(req, timeout=2) as r:
            data = json_mod.loads(r.read().decode())
            models["omlx"] = [m.get("id", "") for m in data.get("data", [])]
    except Exception:
        pass
    
    # Check LM Studio
    try:
        import urllib.request
        import json as json_mod
        req = urllib.request.Request("http://127.0.0.1:1234/v1/models")
        with urllib.request.urlopen(req, timeout=2) as r:
            data = json_mod.loads(r.read().decode())
            models["lmstudio"] = [m.get("id", "") for m in data.get("data", [])]
    except Exception:
        pass
    
    return models


@dataclass
class Config:
    models: list[dict] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    backends: list[str] = field(default_factory=list)
    iterations: int = 1
    warmup: int = 0
    prompt: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        return cls(
            models=deepcopy(data.get("models", [])),
            agents=deepcopy(data.get("agents", [])),
            backends=deepcopy(data.get("backends", [])),
            iterations=data.get("iterations", 1),
            warmup=data.get("warmup", 0),
            prompt=data.get("prompt", "")
        )
    
    @classmethod
    def load(cls, path: Path) -> "Config":
        if path.exists():
            data = json.loads(path.read_text())
            return cls.from_dict(data)
        return cls.from_dict(DEFAULT_CONFIG)
    
    def save(self, path: Path) -> None:
        data = {
            "models": self.models,
            "agents": self.agents,
            "backends": self.backends,
            "iterations": self.iterations,
            "warmup": self.warmup,
            "prompt": self.prompt
        }
        path.write_text(json.dumps(data, indent=2) + "\n")


class TUI:
    def __init__(self, stdscr, config: Config):
        self.stdscr = stdscr
        self.config = config
        self.models_db = detect_models()
        
        # Navigation state
        self.tab_index = 0
        self.tabs = ["models", "agents", "backends", "iterations", "warmup", "prompt"]
        self.tab_labels = ["Models", "Agents", "Backends", "Iterations", "Warmup", "Prompt"]
        
        # Model selection state
        self.selected_model_idx = 0
        self.available_models = []
        
        # Agent selection state
        self.selected_agent_idx = 0
        self.available_agents = ["pi", "opencode"]
        self.agent_indices = {name: i for i, name in enumerate(self.available_agents)}
        
        # Backend selection state
        self.selected_backend_idx = 0
        self.available_backends = ["ollama", "lmstudio", "omlx"]
        self.backend_indices = {name: i for i, name in enumerate(self.available_backends)}
        
        # Prompt editing
        self.prompt_offset = 0
        self.prompt_cursor = 0
        self.editing_prompt = False
        
        # Messages
        self.status_message = ""
        self.error_message = ""
        
        # Setup colors
        curses.start_color()
        curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)   # selected
        curses.init_pair(2, curses.COLOR_CYAN, curses.COLOR_BLACK)    # header
        curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # tab selected
        curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLACK)   # normal
        curses.init_pair(5, curses.COLOR_RED, curses.COLOR_BLACK)     # error
        curses.init_pair(6, curses.COLOR_MAGENTA, curses.COLOR_BLACK) # button
        
        curses.curs_set(0)  # Hide cursor initially
    
    def run(self):
        """Main TUI loop."""
        self.stdscr.nodelay(False)
        self.stdscr.keypad(True)
        curses.cbreak()
        
        while True:
            self.draw()
            key = self.stdscr.getch()
            if self.handle_key(key):
                break
    
    def handle_key(self, key) -> bool:
        """Handle keyboard input. Returns True if should exit."""
        if self.editing_prompt:
            return self.handle_prompt_input(key)

        if key == ord('q') or key == 27:  # q or ESC
            return True

        if key == ord('s'):
            return self.save_and_run()

        if key == ord('r'):
            self.config = Config.from_dict(DEFAULT_CONFIG)
            self.status_message = "Config reset to defaults"
            return False
        
        # Tab navigation
        if key == ord('\t'):
            self.tab_index = (self.tab_index + 1) % len(self.tabs)
            return False
        
        if key == getattr(curses, "KEY_BTAB", -1):
            self.tab_index = (self.tab_index - 1) % len(self.tabs)
            return False
        
        tab = self.tabs[self.tab_index]
        
        if tab == "models":
            return self.handle_models_key(key)
        elif tab == "agents":
            return self.handle_agents_key(key)
        elif tab == "backends":
            return self.handle_backends_key(key)
        elif tab == "iterations":
            return self.handle_iterations_key(key)
        elif tab == "warmup":
            return self.handle_warmup_key(key)
        elif tab == "prompt":
            if key == ord('\n'):
                self.editing_prompt = True
                self.prompt_cursor = len(self.config.prompt)
                self.prompt_offset = 0
            return False
        
        return False
    
    def handle_models_key(self, key) -> bool:
        """Handle model selection keys."""
        if self.config.models:
            if key == curses.KEY_UP:
                self.selected_model_idx = max(0, self.selected_model_idx - 1)
            elif key == curses.KEY_DOWN:
                self.selected_model_idx = min(len(self.config.models) - 1, self.selected_model_idx + 1)
            elif key in (ord('x'), ord(' ')):
                # Toggle model selection
                if self.selected_model_idx < len(self.config.models):
                    # Get the model at this index
                    model = self.config.models[self.selected_model_idx]
                    # Check if it has omlx alias
                    if "omlx" in model:
                        if model["omlx"] in self.available_models:
                            self.available_models.remove(model["omlx"])
                        else:
                            self.available_models.append(model["omlx"])
            elif key == curses.KEY_PPAGE:
                self.selected_model_idx = max(0, self.selected_model_idx - 5)
            elif key == curses.KEY_NPAGE:
                self.selected_model_idx = min(len(self.config.models) - 1, self.selected_model_idx + 5)
        return False
    
    def handle_agents_key(self, key) -> bool:
        """Handle agent selection keys."""
        if key == curses.KEY_UP:
            self.selected_agent_idx = max(0, self.selected_agent_idx - 1)
        elif key == curses.KEY_DOWN:
            self.selected_agent_idx = min(len(self.available_agents) - 1, self.selected_agent_idx + 1)
        elif key in (ord('x'), ord(' ')):
            if not self.available_agents:
                return False
            self.selected_agent_idx = min(self.selected_agent_idx, len(self.available_agents) - 1)
            agent = self.available_agents[self.selected_agent_idx]
            if agent in self.config.agents:
                self.config.agents.remove(agent)
            else:
                self.config.agents.append(agent)
            self.status_message = f"{'Added' if agent in self.config.agents else 'Removed'} {agent}"
        return False
    
    def handle_backends_key(self, key) -> bool:
        """Handle backend selection keys."""
        if key == curses.KEY_UP:
            self.selected_backend_idx = max(0, self.selected_backend_idx - 1)
        elif key == curses.KEY_DOWN:
            self.selected_backend_idx = min(len(self.available_backends) - 1, self.selected_backend_idx + 1)
        elif key in (ord('x'), ord(' ')):
            if not self.available_backends:
                return False
            self.selected_backend_idx = min(self.selected_backend_idx, len(self.available_backends) - 1)
            backend = self.available_backends[self.selected_backend_idx]
            if backend in self.config.backends:
                self.config.backends.remove(backend)
            else:
                self.config.backends.append(backend)
            self.status_message = f"{'Added' if backend in self.config.backends else 'Removed'} {backend}"
        return False
    
    def handle_iterations_key(self, key) -> bool:
        """Handle iterations input."""
        if key in (ord('+'), ord('='), curses.KEY_RIGHT):
            self.config.iterations += 1
            self.status_message = f"Iterations: {self.config.iterations}"
        elif key in (ord('-'), curses.KEY_LEFT) and self.config.iterations > 1:
            self.config.iterations -= 1
            self.status_message = f"Iterations: {self.config.iterations}"
        return False
    
    def handle_warmup_key(self, key) -> bool:
        """Handle warmup input."""
        if key in (ord('+'), ord('='), curses.KEY_RIGHT):
            self.config.warmup += 1
            self.status_message = f"Warmup: {self.config.warmup}"
        elif key in (ord('-'), curses.KEY_LEFT) and self.config.warmup > 0:
            self.config.warmup -= 1
            self.status_message = f"Warmup: {self.config.warmup}"
        return False
    
    def handle_prompt_input(self, key) -> bool:
        """Handle prompt editing input."""
        prompt = self.config.prompt
        
        if key == 27:  # ESC
            self.editing_prompt = False
            return False
        
        if key == ord('\n') or key == curses.KEY_ENTER:
            # Enter inserts newline
            self.config.prompt = prompt[:self.prompt_cursor] + "\n" + prompt[self.prompt_cursor:]
            self.prompt_cursor += 1
        elif key == curses.KEY_BACKSPACE or key == 127:
            if self.prompt_cursor > 0:
                self.config.prompt = prompt[:self.prompt_cursor-1] + prompt[self.prompt_cursor:]
                self.prompt_cursor -= 1
        elif key == curses.KEY_DC:
            if self.prompt_cursor < len(prompt):
                self.config.prompt = prompt[:self.prompt_cursor] + prompt[self.prompt_cursor+1:]
        elif key == curses.KEY_LEFT:
            if self.prompt_cursor > 0:
                self.prompt_cursor -= 1
        elif key == curses.KEY_RIGHT:
            if self.prompt_cursor < len(prompt):
                self.prompt_cursor += 1
        elif key == curses.KEY_UP:
            # Move up lines (simplified)
            pass
        elif key == curses.KEY_DOWN:
            # Move down lines (simplified)
            pass
        elif key == ord(' '):
            self.config.prompt = prompt[:self.prompt_cursor] + " " + prompt[self.prompt_cursor:]
            self.prompt_cursor += 1
        elif 32 <= key < 127:  # Printable ASCII
            char = chr(key)
            self.config.prompt = prompt[:self.prompt_cursor] + char + prompt[self.prompt_cursor:]
            self.prompt_cursor += 1
        
        # Scroll prompt if needed
        lines = self.config.prompt.split('\n')
        line_idx = len(self.config.prompt[:self.prompt_cursor].split('\n')) - 1
        visible_lines = (curses.LINES - 20) // 2  # Rough estimate
        
        self.editing_prompt = True
        return False
    
    def save_and_run(self) -> bool:
        """Save config and run benchmark."""
        try:
            self.config.save(DEFAULT_CONFIG_PATH)
            self.status_message = "Config saved!"
            
            # Ask to run
            self.draw()
            self.stdscr.addstr(curses.LINES - 2, 2, "Save config and run benchmark? (y/n): ")
            self.stdscr.chgat(-1, curses.A_REVERSE)
            self.stdscr.refresh()
            
            key = self.stdscr.getch()
            if key in (ord('y'), ord('Y')):
                # Run the benchmark CLI
                self.stdscr.clear()
                self.stdscr.refresh()
                curses.nocbreak()
                self.stdscr.keypad(False)
                curses.echo()
                curses.curs_set(1)
                
                import subprocess
                result = subprocess.run(
                    [sys.executable, "-m", "ai_bench.cli", "--skip-install"],
                    cwd=str(ROOT)
                )
                
                curses.cbreak()
                self.stdscr.nodelay(False)
                curses.noecho()
                curses.curs_set(0)
                
                self.status_message = "Benchmark complete!" if result.returncode == 0 else "Benchmark failed!"
                return False
        
        except Exception as e:
            self.error_message = str(e)
        
        self.editing_prompt = False
        return False
    
    def draw(self) -> None:
        """Draw the TUI."""
        self.stdscr.clear()
        h, w = self.stdscr.getmaxyx()
        
        # Draw header
        header = " AI-Bench Configuration Editor "
        self.stdscr.attron(curses.color_pair(2) | curses.A_BOLD)
        self.stdscr.addstr(0, (w - len(header)) // 2, header)
        self.stdscr.attroff(curses.color_pair(2) | curses.A_BOLD)
        
        # Draw tabs
        tab_y = 2
        for i, label in enumerate(self.tab_labels):
            color = 3 if i == self.tab_index else 4
            x = 4 + i * 12
            if x + len(label) < w - 4:
                self.stdscr.attron(curses.color_pair(color) | curses.A_BOLD)
                self.stdscr.addstr(tab_y, x, f"[{label}]")
                self.stdscr.attroff(curses.color_pair(color) | curses.A_BOLD)
        
        # Draw content based on tab
        content_y = 5
        self.draw_content(content_y, w, h)
        
        # Draw footer
        footer_y = h - 2
        self.stdscr.attron(curses.color_pair(6) | curses.A_BOLD)
        self.stdscr.addstr(footer_y, 2, "[s] Save & Run")
        self.stdscr.addstr(footer_y, 20, "[q] Quit")
        self.stdscr.addstr(footer_y, 40, "[r] Reset")
        self.stdscr.attroff(curses.color_pair(6) | curses.A_BOLD)
        
        # Draw status
        if self.status_message:
            self.stdscr.attron(curses.color_pair(1))
            self.stdscr.addstr(footer_y, w - len(self.status_message) - 2, self.status_message)
            self.stdscr.attroff(curses.color_pair(1))
        
        # Draw error
        if self.error_message:
            self.stdscr.attron(curses.color_pair(5))
            self.stdscr.addstr(footer_y - 1, 2, f"Error: {self.error_message}")
            self.stdscr.attroff(curses.color_pair(5))
        
        self.stdscr.refresh()
    
    def draw_content(self, y: int, w: int, h: int) -> None:
        """Draw content area based on current tab."""
        tab = self.tabs[self.tab_index]
        
        if tab == "models":
            self.draw_models(y, w, h)
        elif tab == "agents":
            self.draw_agents(y, w)
        elif tab == "backends":
            self.draw_backends(y, w)
        elif tab == "iterations":
            self.draw_iterations(y, w)
        elif tab == "warmup":
            self.draw_warmup(y, w)
        elif tab == "prompt":
            self.draw_prompt(y, w, h)
    
    def draw_models(self, y: int, w: int, h: int) -> None:
        """Draw models tab."""
        self.stdscr.addstr(y, 2, "Available Models from Detected Backends:")
        y += 2
        
        # Detect models if database is empty
        if not self.available_models:
            self.available_models = self.models_db.get("omlx", [])
        
        # Show models from current config
        if self.config.models:
            for i, model in enumerate(self.config.models):
                model_id = model.get("id", "")
                omlx = model.get("omlx", "")
                
                checked = "✓" if omlx in self.available_models else " "
                x = 4
                self.stdscr.attron(curses.color_pair(1) if i == self.selected_model_idx else curses.color_pair(4))
                self.stdscr.addstr(y + i, x, f"[{checked}] {model_id}")
                if omlx:
                    self.stdscr.addstr(y + i, x + len(model_id) + 6, f" ({omlx})")
                self.stdscr.attroff(curses.color_pair(1) if i == self.selected_model_idx else curses.color_pair(4))
            
            # Show status
            if self.status_message:
                self.stdscr.addstr(y + len(self.config.models) + 1, 2, f"Status: {self.status_message}")
        else:
            self.stdscr.addstr(y + 1, 4, "No models selected. Add models to benchmark.")
        
        # Instructions
        self.stdscr.addstr(h - 4, 2, "↑↓: Select | +/-: Add/Remove | Enter: Add new")
    
    def draw_agents(self, y: int, w: int) -> None:
        """Draw agents tab."""
        self.stdscr.addstr(y, 2, "Available Agents:")
        y += 2
        
        for i, agent in enumerate(self.available_agents):
            checked = "✓" if agent in self.config.agents else " "
            x = 4
            self.stdscr.attron(curses.color_pair(1) if i == self.selected_agent_idx else curses.color_pair(4))
            self.stdscr.addstr(y + i, x, f"[{checked}] {agent}")
            self.stdscr.attroff(curses.color_pair(1) if i == self.selected_agent_idx else curses.color_pair(4))
        
        # Instructions
        self.stdscr.addstr(y + len(self.available_agents) + 2, 2, "↑↓: Select | Space: Toggle selection")
    
    def draw_backends(self, y: int, w: int) -> None:
        """Draw backends tab."""
        self.stdscr.addstr(y, 2, "Available Backends:")
        y += 2
        
        for i, backend in enumerate(self.available_backends):
            checked = "✓" if backend in self.config.backends else " "
            x = 4
            self.stdscr.attron(curses.color_pair(1) if i == self.selected_backend_idx else curses.color_pair(4))
            self.stdscr.addstr(y + i, x, f"[{checked}] {backend}")
            self.stdscr.attroff(curses.color_pair(1) if i == self.selected_backend_idx else curses.color_pair(4))
        
        # Instructions
        self.stdscr.addstr(y + len(self.available_backends) + 2, 2, "↑↓: Select | Space: Toggle selection")
    
    def draw_iterations(self, y: int, w: int) -> None:
        """Draw iterations tab."""
        self.stdscr.addstr(y, 2, "Iterations (timed runs per combination):")
        y += 2
        
        # Display iterations with +/- controls
        box_width = 40
        box_x = (w - box_width) // 2
        self.stdscr.attron(curses.color_pair(4))
        self.stdscr.addstr(y, box_x, "┌" + "─" * (box_width - 2) + "┐")
        self.stdscr.addstr(y + 1, box_x, "│")
        self.stdscr.addstr(y + 1, box_x + 15, f"Iterations: {self.config.iterations}")
        self.stdscr.addstr(y + 1, box_x + box_width - 13, "+")
        self.stdscr.addstr(y + 1, box_x, "│")
        self.stdscr.addstr(y + 2, box_x, "└" + "─" * (box_width - 2) + "┘")
        self.stdscr.attroff(curses.color_pair(4))
        
        self.stdscr.addstr(y + 4, 2, "←→: Adjust value")
    
    def draw_warmup(self, y: int, w: int) -> None:
        """Draw warmup tab."""
        self.stdscr.addstr(y, 2, "Warmup (untimed runs to warm up the model):")
        y += 2
        
        box_width = 40
        box_x = (w - box_width) // 2
        self.stdscr.attron(curses.color_pair(4))
        self.stdscr.addstr(y, box_x, "┌" + "─" * (box_width - 2) + "┐")
        self.stdscr.addstr(y + 1, box_x, "│")
        self.stdscr.addstr(y + 1, box_x + 12, f"Warmup: {self.config.warmup}")
        self.stdscr.addstr(y + 1, box_x + box_width - 10, "+")
        self.stdscr.addstr(y + 1, box_x, "│")
        self.stdscr.addstr(y + 2, box_x, "└" + "─" * (box_width - 2) + "┘")
        self.stdscr.attroff(curses.color_pair(4))
        
        self.stdscr.addstr(y + 4, 2, "←→: Adjust value")
    
    def draw_prompt(self, y: int, w: int, h: int) -> None:
        """Draw prompt editor."""
        self.stdscr.addstr(y, 2, "Prompt (Press Enter to edit, ESC to finish):")
        y += 2
        
        # Show prompt with wrapping
        max_lines = h - y - 4
        lines = self.config.prompt.split('\n')
        
        for i in range(min(len(lines), max_lines)):
            line = lines[i]
            # Simple wrapping
            while len(line) > w - 10:
                self.stdscr.addstr(y + i, 4, line[:w - 10])
                line = line[w - 10:]
                i += 1
                if i >= max_lines:
                    break
            if i < max_lines:
                self.stdscr.addstr(y + i, 4, line)
        
        # Show cursor position
        if self.editing_prompt:
            self.stdscr.attron(curses.color_pair(3))
            self.stdscr.addstr(h - 3, 2, "EDIT MODE - Type to edit, Enter for newline, ESC to finish")
            self.stdscr.attroff(curses.color_pair(3))


def main(stdscr):
    """Main entry point for the TUI."""
    # Load config
    config_path = DEFAULT_CONFIG_PATH
    config = Config.load(config_path)
    
    # Initialize TUI
    ui = TUI(stdscr, config)
    ui.run()


def entry_point():
    """Entry point for the script."""
    if len(sys.argv) > 1 and sys.argv[1] in ("--run", "--benchmark"):
        # Run benchmark directly with config
        import subprocess
        import json
        from pathlib import Path
        
        config_path = DEFAULT_CONFIG_PATH
        if config_path.exists():
            config = Config.load(config_path)
            config.save(config_path)  # Ensure it's saved
        else:
            config = Config.from_dict(DEFAULT_CONFIG)
        
        subprocess.run([sys.executable, "-m", "ai_bench.cli"], cwd=str(ROOT))
        return
    
    # Run TUI
    curses.wrapper(main)


if __name__ == "__main__":
    entry_point()
