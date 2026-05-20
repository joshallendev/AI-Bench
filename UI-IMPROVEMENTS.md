# AI-Bench UI Improvements

This document describes the new UI tools added to AI-Bench for easier configuration.

## New Tools

### 1. `config-editor.py` - Interactive Configuration Editor

A user-friendly, step-by-step interactive editor that walks you through configuring AI-Bench.

**Features:**
- Detects available models from oMLX, Ollama, and LM Studio
- Step-by-step configuration guided by prompts
- Easy model selection with visual feedback
- Default values and validation
- Preview before saving
- Direct run option after save

**Usage:**
```bash
python3 config-editor.py
```

**Workflow:**
1. Detects available models from all backends
2. Guides you through selecting models to benchmark
3. Lets you toggle agents (pi, opencode)
4. Lets you toggle backends (ollama, lmstudio, omlx)
5. Configure iterations and warmup counts
6. Edit the prompt (the task for models to solve)
7. Preview configuration
8. Save and optionally run benchmark

### 2. `bench-ui.py` - Full TUI (Terminal User Interface)

A curses-based interface with tabs and keyboard navigation for advanced users.

**Features:**
- Tab-based navigation (Models, Agents, Backends, Iterations, Warmup, Prompt)
- Multi-select with checkboxes for agents and backends
- Model selection with toggle
- Number input controls (+/-) for iterations and warmup
- Multiline prompt editor
- Status messages and error handling
- Direct save & run integration

**Usage:**
```bash
python3 bench-ui.py
```

**Keyboard Controls:**
- `Tab` / `Down` - Next tab
- `Up` - Previous tab
- `Space` / `x` - Toggle selection
- `+` / `-` - Adjust numbers
- `Enter` - Edit prompt
- `ESC` - Cancel prompt editing
- `s` - Save and run
- `q` - Quit
- `r` - Reset to defaults

## Configuration Overview

The `bench.config.json` format:

```json
{
  "models": [
    {
      "id": "qwen3-1.7b",
      "ollama": "qwen3:1.7b",
      "lmstudio": "qwen/qwen3-1.7b",
      "omlx": "Qwen/Qwen2-1.5B"
    }
  ],
  "agents": ["pi", "opencode"],
  "backends": ["ollama", "omlx"],
  "iterations": 3,
  "warmup": 1,
  "prompt": "Build a website with two buttons..."
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `models` | array | List of models to benchmark with per-backend aliases |
| `agents` | array | Which agents to test (pi, opencode) |
| `backends` | array | Which backends to use (ollama, lmstudio, omlx) |
| `iterations` | int | Number of timed runs per combination |
| `warmup` | int | Number of untimed warmup runs |
| `prompt` | string | The task/task prompt for each run |

## Differences from Original

### Before
- Config editing was manual JSON editing
- No model detection or validation
- Error-prone configuration

### After
- Interactive config editors
- Automatic model detection
- Input validation
- Step-by-step guidance
- Preview before saving
- Direct benchmark execution

## Next Steps

1. Run `python3 config-editor.py` to try the interactive editor
2. Or run `python3 bench-ui.py` for the full TUI (requires full terminal)
3. Both tools will detect your available models and guide you through setup

## Example Workflow

**Quick Start (config-editor):**
```bash
$ python3 config-editor.py
# Detects available models
# Guides you through each option
# Press '7' to preview
# Press 'y' to save and run
```

**Full TUI (bench-ui):**
```bash
$ python3 bench-ui.py
# Navigate with arrow keys
# Toggle selections with Space
# Save with 's'
# Quit with 'q'
```

## Troubleshooting

**No models detected:**
- Start oMLX: `omlx serve`
- Start Ollama: `ollama serve`
- Or load models in LM Studio UI

**Import errors:**
```bash
pip install urllib3 requests
```

**Terminal issues:**
The full TUI (`bench-ui.py`) requires a proper terminal. Use `config-editor.py` if you're in an IDE or non-standard environment.