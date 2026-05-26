# Code Review Findings

Branch: `ui-improvements` vs `main` (plus working-tree changes). High-effort review, ranked by severity.

## 1. `ai_bench/cli.py:39` — ROOT now resolves against cwd, breaking installed flow

ROOT was changed from `Path(__file__).parent.resolve()` to `Path.cwd().resolve()`, so `.env` loading, `.bench-state.json` placement, default `bench.config.json` lookup, and the viewer.html pointer all resolve against the user's cwd — silently breaking the documented `pip install + ai-bench` workflow whenever invoked from any directory other than the repo root.

**Failure:** After `pip install -e .`, `cd /tmp && ai-bench` installs Ollama and writes `/tmp/.bench-state.json`; later `cd ~ && ai-bench --cleanup-only` reads an empty state file, so the installed Ollama is never cleaned up. Likewise the repo's `.env` (HF_TOKEN) is not loaded, so gated HuggingFace downloads 401 with no warning.

## 2. `bench-ui.py:425` — `draw_agents` / `draw_backends` signature mismatch

`draw_content` calls `self.draw_agents(y, w, h)` and `self.draw_backends(y, w, h)` but the methods are defined as `def draw_agents(self, y, w)` / `def draw_backends(self, y, w)` — three positional args supplied, two accepted.

**Failure:** User launches `python bench-ui.py` and presses Tab to reach the Agents (or Backends) tab → `TypeError: draw_agents() takes 3 positional arguments but 4 were given` → curses wrapper crashes, terminal left in a bad state.

## 3. `ai_bench/cli.py:275` — `have_lmstudio_model` fallback defeats partial-download guard

`have_lmstudio_model` now falls back to parsing `lms ls` aliases when the on-disk completeness check fails, defeating the explicitly-documented invariant (lines 259–260) that partial downloads with `.part` files must report NOT installed; `_list_lmstudio_installed` has no `.part` awareness.

**Failure:** User cancels a download mid-flight leaving `.part` files in `~/.lmstudio/models/<repo>/`. The fs check fails but `lms ls` still lists the model id, so `have_lmstudio_model` returns `True`; the bench then `lms load`s a corrupt/half-finished model and hangs or errors mid-iteration.

## 4. `ai_bench/cli.py:317` — `have_omlx_model` no longer matches `org/repo` names

`have_omlx_model` compares the configured name against the basename `id` returned by `_list_omlx_installed`, dropping the old `(OMLX_MODEL_DIR / name).exists()` check that matched HuggingFace `org/repo` paths.

**Failure:** Config has `"omlx": "mlx-community/Qwen3-Coder-Next-MLX-4bit"` and the model is already on disk at `~/.omlx/models/mlx-community/Qwen3-Coder-Next-MLX-4bit/`; `have_omlx_model` returns `False` because `_list_omlx_installed` exposes only the basename id; the bench triggers a multi-GB redownload on every run.

## 5. `ai_bench/cli.py:2179` — viewer.html pointer broken after `pip install`

End-of-run log prints `View: open {ROOT}/viewer.html`, but `viewer.html` lives at the repo root and `pyproject.toml` package-data only ships `ai_bench/static/*.html|*.js`, so after `pip install` viewer.html is not bundled and ROOT (now cwd) points at a non-existent file.

**Failure:** User runs `pip install ai-bench` and `ai-bench` from `$HOME`; final log says `View: open /Users/me/viewer.html`, which does not exist — the headline UX (open the dashboard against `results.json`) is broken on every installed deployment.

## 6. `ai_bench/web_process.py:296` — duplicate SSE events for legacy log lines

`_handle_stdout_line` routes a non-`AI_BENCH_EVENT` line to `_handle_log_line` without a `return`, then falls through to `parse_bench_progress_line`, so legacy `[N/M] starting …` lines are emitted as both `log` and `iteration_start` SSE events.

**Failure:** `ai_bench.cli` emits `[2/6] starting pi+ollama+qwen3 timed iter-1`; the SSE stream gets both a `log` event and an `iteration_start` event for the same line; the web UI's progress counter advances twice per iteration, throwing off remaining-time estimates and any totals derived from the stream.

## 7. `bench-ui.py:239` — shared `selected_model_idx` causes IndexError on tab switch

`selected_model_idx` is initialized once at line 118 and shared across Models/Agents/Backends tabs without being reset on tab switch, and `handle_agents_key` / `handle_backends_key` index `available_agents` / `available_backends` on Space with no bounds check.

**Failure:** User has 6 models, presses Down 5× on Models (idx=5), Tab to Agents (2 entries), presses Space → `self.available_agents[5]` → IndexError → curses wrapper crashes.

## 8. `ai_bench/web_server.py:33` — `validate_server_config` rejects `localhost`

`validate_server_config` calls `ipaddress.ip_address(config.host)` to validate the host, which raises `ValueError` for any non-IP string (including `localhost`), causing the server to refuse hostnames it could otherwise bind.

**Failure:** User runs `bench-web --host localhost`; validation raises `ValueError` → server prints `Invalid host: 'localhost'` and exits rc=1, even though `localhost` is a valid loopback alias resolvable to 127.0.0.1/::1.

## 9. `config-editor.py:506` — shallow `DEFAULT_CONFIG.copy()` mutates the default

Reset-to-defaults assigns `config = DEFAULT_CONFIG.copy()` (shallow). `DEFAULT_CONFIG["models"]` is a list; the copied config shares the same list object, so subsequent `config["models"].append(...)` mutates the module-level default.

**Failure:** User chooses option 8 (reset), then option 1 (edit models, add one), then option 8 again expecting the original defaults. The "defaults" now include the previously-added model because the shared list was mutated — reset no longer resets.

## 10. `bench-ui.py:514` — Iterations/Warmup help text advertises keys the handler ignores

`draw_iterations` and `draw_warmup` display the help text `←→: Adjust value`, but `handle_iterations_key` / `handle_warmup_key` only accept `+/-/=`; `KEY_LEFT` / `KEY_RIGHT` are not handled, and `KEY_UP` / `KEY_DOWN` are consumed by tab navigation before reaching the per-tab handlers.

**Failure:** User reads on-screen instruction and presses the right arrow on the Iterations tab → nothing happens; user concludes the TUI is broken and abandons it.
