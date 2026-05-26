#!/usr/bin/env python3
"""
config-editor.py - Interactive config editor for AI-Bench

A simpler, more user-friendly config editor that guides you through
setting up your benchmark configuration step by step.
"""

import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.resolve()
DEFAULT_CONFIG_PATH = ROOT / "bench.config.json"
DEFAULT_CONFIG = {
    "models": [
        {"id": "qwen3-1.7b", "ollama": "qwen3:1.7b", "omlx": "Qwen/Qwen2-1.5B"}
    ],
    "agents": ["pi"],
    "backends": ["ollama"],
    "iterations": 1,
    "warmup": 0,
    "prompt": "Write a simple hello world program."
}


def print_header(title: str) -> None:
    """Print a header with decorative borders."""
    width = 60
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width + "\n")


def print_status(message: str) -> None:
    """Print a status message."""
    print(f"  ✓ {message}")


def print_error(message: str) -> None:
    """Print an error message."""
    print(f"  ✗ {message}")


def print_option(num: int, text: str, selected: bool = False) -> None:
    """Print a menu option."""
    marker = "»" if selected else " "
    print(f"  [{marker}] {num}. {text}")


def input_choice(prompt: str, choices: list[str], default: Optional[str] = None) -> str:
    """Get a choice from the user."""
    choices_lower = [c.lower() for c in choices]
    while True:
        response = input(f"  {prompt}: ").strip().lower()
        if not response and default:
            return default
        if response in choices_lower:
            return response
        print(f"  Please choose from: {', '.join(choices)}")


def input_int(prompt: str, min_val: int = 0, max_val: Optional[int] = None, default: int = 0) -> int:
    """Get an integer from the user."""
    while True:
        response = input(f"  {prompt} (default: {default}): ").strip()
        if not response:
            return default
        try:
            val = int(response)
            if min_val is not None and val < min_val:
                print(f"  Value must be >= {min_val}")
                continue
            if max_val is not None and val > max_val:
                print(f"  Value must be <= {max_val}")
                continue
            return val
        except ValueError:
            print("  Please enter a valid integer")


def detect_available_models() -> dict[str, list[str]]:
    """Detect available models from each backend."""
    models = {"ollama": [], "lmstudio": [], "omlx": []}
    
    try:
        import urllib.request
        import json as json_mod
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=2) as r:
            data = json_mod.loads(r.read().decode())
            models["ollama"] = [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        pass
    
    try:
        import urllib.request
        import json as json_mod
        req = urllib.request.Request("http://localhost:8000/v1/models")
        with urllib.request.urlopen(req, timeout=2) as r:
            data = json_mod.loads(r.read().decode())
            models["omlx"] = [m.get("id", "") for m in data.get("data", [])]
    except Exception:
        pass
    
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


def load_config() -> dict:
    """Load existing config or return default."""
    if DEFAULT_CONFIG_PATH.exists():
        return json.loads(DEFAULT_CONFIG_PATH.read_text())
    return deepcopy(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    """Save config to file."""
    DEFAULT_CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")
    print_status(f"Config saved to {DEFAULT_CONFIG_PATH}")


def edit_models(config: dict, available: dict[str, list[str]]) -> dict:
    """Interactively edit models."""
    print_header("Models Configuration")
    
    if not available["omlx"]:
        print_error("No oMLX models detected. Starting oMLX server...")
        print("  Try: omlx serve")
        print("  Or load a model in the LM Studio UI\n")
        input("  Press Enter to continue...")
    
    print("Available models from oMLX:")
    for i, model in enumerate(available["omlx"], 1):
        print(f"  {i}. {model}")
    
    if available["ollama"]:
        print("\nAvailable models from Ollama:")
        for i, model in enumerate(available["ollama"], 1):
            print(f"  {i}. {model}")
    
    print("\n" + "-" * 40)
    
    models = config.get("models", [])
    
    while True:
        print("\nCurrent models in config:")
        if models:
            for i, m in enumerate(models, 1):
                print(f"  {i}. {m.get('id', 'unnamed')} (omlx: {m.get('omlx', 'N/A')})")
        else:
            print("  (none)")
        
        print("\nOptions:")
        print("  1. Add new model")
        print("  2. Remove model")
        print("  3. Done")
        
        choice = input("  Choose: ").strip()
        
        if choice == "1":
            # Add new model
            print("\nSelect model to add:")
            
            if available["omlx"]:
                print("\n  From oMLX:")
                for i, model in enumerate(available["omlx"], 1):
                    print(f"    {i}. {model}")
            
            if available["ollama"]:
                print("\n  From Ollama:")
                for i, model in enumerate(available["ollama"], 1):
                    print(f"    {i}. {model}")
            
            # Find next number
            next_num = 1
            if available["omlx"]:
                next_num = len(available["omlx"]) + 1
            
            try:
                num = int(input(f"  Enter number (1-{next_num}): ").strip())
                source = "omlx" if num <= len(available["omlx"]) else "ollama"
                model_alias = available[source][num - 1] if source == "omlx" else available["ollama"][num - 1 - len(available["omlx"])]
                
                model_id = input(f"  Enter display name for this model (e.g., qwen3): ").strip()
                if not model_id:
                    model_id = model_alias.split("/")[-1].split(":")[0]
                
                new_model = {"id": model_id, source: model_alias}
                models.append(new_model)
                print_status(f"Added {model_id}")
            except (ValueError, IndexError):
                print_error("Invalid selection")
        
        elif choice == "2" and models:
            try:
                num = int(input("  Enter model number to remove: ").strip())
                removed = models.pop(num - 1)
                print_status(f"Removed {removed.get('id', 'unnamed')}")
            except (ValueError, IndexError):
                print_error("Invalid selection")
        
        elif choice == "3":
            break
    
    config["models"] = models
    return config


def edit_agents(config: dict) -> dict:
    """Interactively edit agents."""
    print_header("Agents Configuration")
    
    available_agents = ["pi", "opencode"]
    current_agents = config.get("agents", [])
    
    print("Available agents:")
    for agent in available_agents:
        status = "✓" if agent in current_agents else "✗"
        print(f"  [{status}] {agent}")
    
    while True:
        print("\nOptions:")
        print("  1. Toggle pi")
        print("  2. Toggle opencode")
        print("  3. Done")
        
        choice = input("  Choose: ").strip()
        
        if choice == "1":
            if "pi" in current_agents:
                current_agents.remove("pi")
                print_status("Removed pi")
            else:
                current_agents.append("pi")
                print_status("Added pi")
        
        elif choice == "2":
            if "opencode" in current_agents:
                current_agents.remove("opencode")
                print_status("Removed opencode")
            else:
                current_agents.append("opencode")
                print_status("Added opencode")
        
        elif choice == "3":
            break
    
    config["agents"] = current_agents
    return config


def edit_backends(config: dict, available: dict[str, list[str]]) -> dict:
    """Interactively edit backends."""
    print_header("Backends Configuration")
    
    available_backends = ["ollama", "lmstudio", "omlx"]
    current_backends = config.get("backends", [])
    
    # Check availability
    ollama_available = False
    lmstudio_available = False
    omlx_available = False
    
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:11434/api/health", timeout=2)
        ollama_available = True
    except Exception:
        pass
    
    try:
        urllib.request.urlopen("http://127.0.0.1:1234/v1/models", timeout=2)
        lmstudio_available = True
    except Exception:
        pass
    
    try:
        urllib.request.urlopen("http://localhost:8000/health", timeout=2)
        omlx_available = True
    except Exception:
        pass
    
    print("Available backends:")
    for backend in available_backends:
        if backend == "ollama":
            status = "✓" if ollama_available else "✗"
            print(f"  [{status}] ollama")
        elif backend == "lmstudio":
            status = "✓" if lmstudio_available else "✗"
            print(f"  [{status}] lmstudio")
        elif backend == "omlx":
            status = "✓" if omlx_available else "✗"
            print(f"  [{status}] omlx")
    
    while True:
        print("\nOptions:")
        print("  1. Toggle ollama")
        print("  2. Toggle lmstudio")
        print("  3. Toggle omlx")
        print("  4. Done")
        
        choice = input("  Choose: ").strip()
        
        if choice == "1":
            if "ollama" in current_backends:
                current_backends.remove("ollama")
                print_status("Removed ollama")
            else:
                current_backends.append("ollama")
                print_status("Added ollama")
        
        elif choice == "2":
            if "lmstudio" in current_backends:
                current_backends.remove("lmstudio")
                print_status("Removed lmstudio")
            else:
                current_backends.append("lmstudio")
                print_status("Added lmstudio")
        
        elif choice == "3":
            if "omlx" in current_backends:
                current_backends.remove("omlx")
                print_status("Removed omlx")
            else:
                current_backends.append("omlx")
                print_status("Added omlx")
        
        elif choice == "4":
            break
    
    config["backends"] = current_backends
    return config


def edit_iterations(config: dict) -> dict:
    """Interactively edit iterations."""
    print_header("Iterations Configuration")
    
    current = config.get("iterations", 1)
    print(f"Current iterations: {current}")
    print("Iterations are the timed runs that are measured and recorded.")
    
    new_val = input_int("  Enter number of iterations", min_val=1, max_val=100, default=current)
    config["iterations"] = new_val
    
    return config


def edit_warmup(config: dict) -> dict:
    """Interactively edit warmup."""
    print_header("Warmup Configuration")
    
    current = config.get("warmup", 0)
    print(f"Current warmup runs: {current}")
    print("Warmup runs are untimed and used to warm up the model (cold start).")
    
    new_val = input_int("  Enter number of warmup runs", min_val=0, max_val=100, default=current)
    config["warmup"] = new_val
    
    return config


def edit_prompt(config: dict) -> dict:
    """Interactively edit the prompt."""
    print_header("Prompt Configuration")
    
    current = config.get("prompt", "")
    print(f"Current prompt ({len(current)} characters):")
    print("-" * 60)
    if current:
        print(current[:500])
        if len(current) > 500:
            print("...")
    else:
        print("(empty)")
    print("-" * 60)
    
    print("\nOptions:")
    print("  1. Reset to default")
    print("  2. Enter new prompt (paste mode - press Ctrl+D on Mac/Unix or Ctrl+Z on Windows)")
    
    choice = input("  Choose: ").strip()
    
    if choice == "1":
        config["prompt"] = DEFAULT_CONFIG["prompt"]
        print_status("Prompt reset to default")
    elif choice == "2":
        print("\n  Paste your prompt and press Ctrl+D to finish:")
        lines = []
        try:
            while True:
                lines.append(input())
        except EOFError:
            pass
        config["prompt"] = "\n".join(lines)
        print_status(f"Prompt updated ({len(config['prompt'])} characters)")
    
    return config


def preview_config(config: dict) -> None:
    """Preview the final configuration."""
    print_header("Configuration Preview")
    
    print("Models:")
    for m in config.get("models", []):
        print(f"  - {m.get('id', 'unnamed')}")
    
    print("\nAgents:")
    for a in config.get("agents", []):
        print(f"  - {a}")
    
    print("\nBackends:")
    for b in config.get("backends", []):
        print(f"  - {b}")
    
    print(f"\nIterations: {config.get('iterations', 1)}")
    print(f"Warmup: {config.get('warmup', 0)}")
    print(f"Prompt length: {len(config.get('prompt', ''))} characters")
    
    print("\n" + "=" * 60)
    print("Ready to save and run!")
    print("=" * 60)


def main():
    """Main entry point."""
    print_header("AI-Bench Configuration Editor")
    
    print("This tool helps you configure AI-Bench benchmarks interactively.")
    print("You'll be guided through each configuration option step by step.\n")
    
    # Load existing config
    config = load_config()
    
    # Detect available models
    print("Detecting available models...")
    available = detect_available_models()
    
    if not any(available.values()):
        print_error("No models detected. Please:")
        print("  1. Start omlx server: omlx serve")
        print("  2. Or start ollama: ollama serve")
        print("  3. Load a model in LM Studio\n")
        input("Press Enter to continue anyway...")
    
    # Navigate through configuration options
    while True:
        print_header("Configuration Menu")
        
        print(f"Models: {len(config.get('models', []))} selected")
        print(f"Agents: {', '.join(config.get('agents', []))}")
        print(f"Backends: {', '.join(config.get('backends', []))}")
        print(f"Iterations: {config.get('iterations', 1)}")
        print(f"Warmup: {config.get('warmup', 0)}")
        print(f"Prompt: {len(config.get('prompt', ''))} characters")
        
        print("\nOptions:")
        print("  1. Edit models")
        print("  2. Edit agents")
        print("  3. Edit backends")
        print("  4. Edit iterations")
        print("  5. Edit warmup")
        print("  6. Edit prompt")
        print("  7. Preview and save")
        print("  8. Reset to defaults")
        print("  9. Cancel")
        
        choice = input("\nChoose: ").strip()
        
        if choice == "1":
            config = edit_models(config, available)
        elif choice == "2":
            config = edit_agents(config)
        elif choice == "3":
            config = edit_backends(config, available)
        elif choice == "4":
            config = edit_iterations(config)
        elif choice == "5":
            config = edit_warmup(config)
        elif choice == "6":
            config = edit_prompt(config)
        elif choice == "7":
            preview_config(config)
            confirm = input("\nSave and run benchmark? (y/n): ").strip().lower()
            if confirm == "y":
                save_config(config)
                print_status("Running benchmark...")
                import subprocess
                subprocess.run([sys.executable, "-m", "ai_bench.cli", "--skip-install"], cwd=str(ROOT))
                print_status("Benchmark complete!")
            break
        elif choice == "8":
            if input("Reset to defaults? (y/n): ").strip().lower() == "y":
                config = deepcopy(DEFAULT_CONFIG)
                print_status("Reset to defaults")
        elif choice == "9":
            print("Cancelled")
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled")
        sys.exit(0)
