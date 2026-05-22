"""Model presence checks, downloads, and search/list utilities.

Extracted from bench.py for modular access to model-related operations
across Ollama, LM Studio, HuggingFace, and oMLX backends.
"""

import json
import os
import platform
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ai_bench.backends import OLLAMA_MANIFESTS, OMLX_BIN, OMLX_MODEL_DIR, run, which
from ai_bench.log import log, warn

IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"
IS_ARM64 = platform.machine() in ("arm64", "aarch64")
LMSTUDIO_SUPPORTED = IS_MAC and IS_ARM64
OMLX_SUPPORTED = IS_MAC and IS_ARM64
OMLX_VENV_DIR = Path.home() / ".local" / "share" / "omlx-venv"


def have_omlx():
    """Check if oMLX is available (supports OpenAI-compatible API)."""
    if not OMLX_SUPPORTED:
        return False
    if which("omlx") or OMLX_BIN.exists():
        return True
    try:
        urllib.request.urlopen("http://localhost:8000/v1/models", timeout=2)
        return True
    except Exception:
        return False


def have_ollama_model(name):
    # Read manifest directly so this works pre-flight (before the server is up)
    # and matches what _list_ollama_installed() reports.
    if ":" in name:
        family, tag = name.split(":", 1)
    else:
        family, tag = name, "latest"
    return (OLLAMA_MANIFESTS / family / tag).exists()


def _lmstudio_dir_complete(d):
    """Return True only if a model dir is FULLY downloaded — no .part files
    and at least one .safetensors / .gguf weight file present."""
    if not d.is_dir():
        return False
    files = list(d.iterdir())
    if not files:
        return False
    if any(f.name.startswith("downloading_") or f.name.endswith(".part") for f in files):
        return False
    has_weights = any(f.suffix in (".safetensors", ".gguf") for f in files)
    return has_weights


def have_lmstudio_model(name):
    # Filesystem check is the ground truth: LM Studio's `lms ls` renames models
    # (strips publisher + quant suffix) so substring matching there is unreliable.
    # The download lives under ~/.lmstudio/models/<hf_path>/ regardless. We
    # treat partial downloads (any `.part` file present) as NOT present, so the
    # bench doesn't try to load a half-finished model.
    if not name:
        return False
    path = name
    if path.startswith("http"):
        path = path.rstrip("/").split("huggingface.co/")[-1]
    lms_root = Path.home() / ".lmstudio" / "models"
    candidate = lms_root / path
    if _lmstudio_dir_complete(candidate):
        return True
    if lms_root.exists():
        target = path.split("/")[-1].lower()
        for d in lms_root.rglob("*"):
            if d.is_dir() and d.name.lower() == target and _lmstudio_dir_complete(d):
                return True
    return False


def _lmstudio_resolve_api_id(hf_path):
    """Return LM Studio's API model ID for an HF repo path, or None.

    LM Studio assigns a shorter alias (e.g. `qwen3-coder-next-mlx` for
    `lmstudio-community/Qwen3-Coder-Next-MLX-4bit`). Both `lms load` and the
    OpenAI-compatible /v1/* endpoints want that alias, not the HF path.
    """
    try:
        with urllib.request.urlopen("http://127.0.0.1:1234/v1/models", timeout=5) as r:
            data = json.loads(r.read())
        ids = [m.get("id", "") for m in (data.get("data") or []) if m.get("id")]
    except Exception:
        return None
    if not ids:
        return None
    target = hf_path.split("/")[-1].lower()
    for api_id in ids:
        if api_id.lower() == target:
            return api_id
    for api_id in ids:
        api_lower = api_id.lower()
        if target.startswith(api_lower) or api_lower.startswith(target):
            return api_id
    for api_id in ids:
        if api_id.lower() in target or target in api_id.lower():
            return api_id
    return None


def have_omlx_model(name):
    """Check if oMLX model is fully downloaded (has weight files on disk)."""
    if not have_omlx():
        return False
    model_path = OMLX_MODEL_DIR / name
    if not model_path.exists():
        return False
    return any(model_path.glob("*.safetensors")) or any(model_path.glob("*.gguf"))


def _hf_get_chat_template(hf_repo, headers):
    """Fetch chat_template string from a HuggingFace repo's tokenizer_config.json, or None."""
    try:
        url = f"https://huggingface.co/{hf_repo}/resolve/main/tokenizer_config.json"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get("chat_template")
    except Exception:
        return None


def _hf_get_base_model(hf_repo, headers):
    """Return the base_model field from a HuggingFace model card, or None."""
    try:
        url = f"https://huggingface.co/api/models/{hf_repo}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            card = json.loads(r.read()).get("cardData") or {}
        base = card.get("base_model")
        # base_model can be a string or a list
        return (base[0] if isinstance(base, list) else base) or None
    except Exception:
        return None


def _patch_omlx_chat_template(model_dir, hf_repo):
    """Ensure tokenizer_config.json has chat_template.

    Tries hf_repo first; if its tokenizer_config also lacks the template (common
    for third-party quantisations like Outlier-Ai), falls back to the base_model
    repo declared in the HuggingFace model card.
    """
    tc_path = model_dir / "tokenizer_config.json"
    if not tc_path.exists():
        return
    try:
        tc = json.loads(tc_path.read_text())
        if tc.get("chat_template"):
            return
        token = os.environ.get("HF_TOKEN", "")
        headers = {"User-Agent": "agent-bench/1.0"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        log(f"chat_template missing — fetching from {hf_repo}…")
        chat_template = _hf_get_chat_template(hf_repo, headers)

        if not chat_template:
            base_repo = _hf_get_base_model(hf_repo, headers)
            if base_repo:
                log(f"Not found in {hf_repo} — trying base model {base_repo}…")
                chat_template = _hf_get_chat_template(base_repo, headers)

        if not chat_template:
            warn(f"Could not find chat_template for {hf_repo} — oMLX will return 400 on chat requests.")
            return

        tc["chat_template"] = chat_template
        tc_path.write_text(json.dumps(tc, indent=2))
        log("chat_template patched OK.")
    except Exception as e:
        warn(f"Could not patch chat_template: {e}")


def download_omlx_model(name, hf_repo=None):
    """Download an MLX model from HuggingFace into OMLX_MODEL_DIR.

    hf_repo defaults to mlx-community/<name> — the standard convention for
    pre-quantised MLX models on HuggingFace.
    """
    repo = hf_repo or f"mlx-community/{name}"
    dest = OMLX_MODEL_DIR / name
    if dest.exists():
        _patch_omlx_chat_template(dest, repo)
        return
    OMLX_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    log(f"Downloading oMLX model '{repo}' → {dest} …")
    venv_python = OMLX_VENV_DIR / "bin" / "python"
    python = str(venv_python) if venv_python.exists() else shutil.which("python3")
    run([
        python, "-c",
        f"from huggingface_hub import snapshot_download; "
        f"snapshot_download(repo_id={repo!r}, local_dir={str(dest)!r})",
    ])
    _patch_omlx_chat_template(dest, repo)


def _fmt_size(size_bytes):
    if not size_bytes:
        return ""
    gb = size_bytes / 1e9
    return f"{gb:.1f} GB" if gb >= 1 else f"{size_bytes / 1e6:.0f} MB"


def _list_ollama_installed():
    """Return locally pulled Ollama models by reading manifests directly.

    Reads ~/.ollama/models/manifests/registry.ollama.ai/library/ so it works
    even when the Ollama server isn't running yet.
    """
    if not OLLAMA_MANIFESTS.exists():
        return []
    results = []
    for family_dir in sorted(OLLAMA_MANIFESTS.iterdir()):
        if not family_dir.is_dir():
            continue
        for tag_file in sorted(family_dir.iterdir()):
            if not tag_file.is_file():
                continue
            model_id = f"{family_dir.name}:{tag_file.name}"
            size = ""
            try:
                manifest = json.loads(tag_file.read_text())
                total = sum(layer.get("size", 0) for layer in manifest.get("layers", []))
                size = _fmt_size(total) if total else ""
            except Exception:
                pass
            results.append({"id": model_id, "size": size})
    return results


def _search_ollama(term):
    """Search Ollama by scraping the library page for all tag variants + sizes.

    Heuristic: the first whitespace-separated word is the family slug. Try it
    verbatim first; if that returns nothing and the term has multiple words,
    retry with the first two words concatenated (handles "llama 3" → "llama3").
    Any remaining words are treated as a substring filter on the tag.
    """
    parts = term.lower().strip().replace("_", "-").split()
    if not parts:
        return []

    def _fetch(family, tag_filter=""):
        try:
            req = urllib.request.Request(
                f"https://ollama.com/library/{family}",
                headers={"User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=6) as r:
                html = r.read().decode("utf-8", errors="ignore")
            tag_pat = re.compile(rf'{re.escape(family)}:[a-zA-Z0-9._-]+')
            size_pat = re.compile(r'(\d+\.?\d*)\s*(GB|MB)')
            seen = {}
            for m in tag_pat.finditer(html):
                tag = m.group(0)
                if tag in seen:
                    continue
                ctx = html[m.start(): m.start() + 400]
                sm = size_pat.search(ctx)
                seen[tag] = f"{sm.group(1)} {sm.group(2)}" if sm else ""
            tags = sorted(seen.keys())
            if tag_filter:
                tags = [t for t in tags if tag_filter in t.lower()]
            return [{"id": t, "size": seen.get(t, "")} for t in tags]
        except Exception:
            return []

    first_results = _fetch(parts[0], " ".join(parts[1:]))
    if first_results:
        return first_results
    if len(parts) >= 2:
        joined = parts[0] + parts[1]
        return _fetch(joined, " ".join(parts[2:]))
    return []


def _list_lmstudio_installed():
    """Return locally downloaded LM Studio models from `lms ls`."""
    if not which("lms"):
        return []
    try:
        rc, out, _ = run(["lms", "ls"], capture=True, check=False)
        if rc != 0:
            return []
        results = []
        for line in out.splitlines():
            # lms ls rows look like: "qwen/qwen3-1.7b (1 variant)  1.7B  qwen3  1.14 GB  Local"
            parts = line.split()
            if not parts or parts[0].startswith(("LLM", "EMBED", "You ", "─")):
                continue
            model_id = parts[0].rstrip("*")  # strip any trailing marker
            if "/" not in model_id and "." not in model_id:
                continue  # skip header-like lines
            # Extract size — look for "X.XX GB" or "X MB" pattern
            size = ""
            for i, p in enumerate(parts):
                if p in ("GB", "MB") and i > 0:
                    size = f"{parts[i-1]} {p}"
                    break
            results.append({"id": model_id, "size": size, "desc": "installed"})
        return results
    except Exception:
        return []


def _hf_fetch_model_info(hf_id):
    """Fetch the full HuggingFace model API payload, or {} on failure."""
    headers = {"User-Agent": "agent-bench/1.0"}
    token = os.environ.get("HF_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(
            f"https://huggingface.co/api/models/{hf_id}",
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=4) as r:
            return json.loads(r.read()) or {}
    except Exception:
        return {}


def _search_lmstudio_online(term):
    """Search HuggingFace for models downloadable via `lms get`.

    Searches both GGUF and (on Apple Silicon) MLX repos, since LM Studio
    supports both formats. Filters out repos that have neither a .gguf nor
    .safetensors file. `desc` notes the format + file count so the user can
    tell e.g. a single-file GGUF from a multi-quant repo.
    """
    try:
        tags_to_search = ["gguf"]
        if LMSTUDIO_SUPPORTED:
            tags_to_search.append("mlx")

        all_ids = []
        seen = set()
        for tag in tags_to_search:
            params = urllib.parse.urlencode({
                "search": term, "tags": tag,
                "sort": "downloads", "limit": 15,
            })
            req = urllib.request.Request(
                f"https://huggingface.co/api/models?{params}",
                headers={"User-Agent": "agent-bench/1.0"},
            )
            try:
                with urllib.request.urlopen(req, timeout=6) as r:
                    items = json.loads(r.read())
            except Exception:
                continue
            for m in items:
                mid = m.get("id") or m.get("modelId", "")
                if mid and mid not in seen:
                    seen.add(mid)
                    all_ids.append(mid)

        with ThreadPoolExecutor(max_workers=8) as pool:
            infos = list(pool.map(_hf_fetch_model_info, all_ids))
        results = []
        for hf_id, info in zip(all_ids, infos):
            siblings = info.get("siblings") or []
            filenames = [(s.get("rfilename") or "").lower() for s in siblings]
            gguf_count = sum(1 for f in filenames if f.endswith(".gguf"))
            st_count   = sum(1 for f in filenames if f.endswith(".safetensors"))
            if gguf_count == 0 and st_count == 0:
                continue
            tags = info.get("tags") or []
            is_mlx = "mlx" in tags or "-mlx-" in hf_id.lower() or hf_id.lower().endswith("-mlx")
            if gguf_count > 0:
                desc = f"GGUF · {gguf_count} file{'s' if gguf_count > 1 else ''}"
            elif is_mlx:
                desc = "MLX (Apple Silicon)"
            else:
                desc = f"safetensors · {st_count} shard{'s' if st_count > 1 else ''}"
            size_bytes = info.get("usedStorage") or 0
            results.append({
                "id": hf_id,
                "size": _fmt_size(size_bytes),
                "desc": desc,
            })
            if len(results) >= 16:
                break
        return results
    except Exception:
        return []


def _list_omlx_installed():
    """Return locally downloaded oMLX models from OMLX_MODEL_DIR."""
    if not OMLX_MODEL_DIR.exists():
        return []
    results = []
    for d in sorted(OMLX_MODEL_DIR.iterdir()):
        if not d.is_dir():
            continue
        try:
            size_bytes = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        except Exception:
            size_bytes = None
        results.append({"id": d.name, "size": _fmt_size(size_bytes)})
    return results


def _search_hf_mlx(term):
    """Search HuggingFace for MLX safetensors models across all publishers.

    Uses the `mlx` tag rather than filtering to a single org so packagers like
    mlx-community, lmstudio-community, and others all surface. Skips repos
    with no .safetensors files (mis-tagged or weight-less READMEs).
    """
    try:
        params = urllib.parse.urlencode({
            "search": term, "tags": "mlx",
            "sort": "downloads", "limit": 20,
        })
        req = urllib.request.Request(
            f"https://huggingface.co/api/models?{params}",
            headers={"User-Agent": "agent-bench/1.0"},
        )
        with urllib.request.urlopen(req, timeout=6) as r:
            items = json.loads(r.read())
        hf_ids = [m.get("id") or m.get("modelId", "") for m in items]
        hf_ids = [h for h in hf_ids if h]
        with ThreadPoolExecutor(max_workers=8) as pool:
            infos = list(pool.map(_hf_fetch_model_info, hf_ids))
        results = []
        for hf_id, info in zip(hf_ids, infos):
            siblings = info.get("siblings") or []
            has_st = any(
                (s.get("rfilename") or "").lower().endswith(".safetensors")
                for s in siblings
            )
            if not has_st:
                continue
            tags = info.get("tags") or []
            is_mlx = "mlx" in tags or "mlx" in hf_id.lower()
            if not is_mlx:
                continue
            org = hf_id.split("/")[0] if "/" in hf_id else ""
            size_bytes = info.get("usedStorage") or 0
            results.append({
                "id": hf_id.split("/")[-1],
                "hf_id": hf_id,
                "size": _fmt_size(size_bytes),
                "desc": org,
            })
            if len(results) >= 12:
                break
        return results
    except Exception:
        return []
