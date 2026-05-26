from ai_bench.combos import planned_combos, planned_step_count

REGISTRY = {
    "pi":       {"supports_backends": ["ollama", "lmstudio", "omlx"]},
    "direct":   {"supports_backends": ["ollama", "lmstudio", "omlx"]},
    "opencode": {"supports_backends": ["ollama"]},
}

MODELS = [
    {"id": "qwen3-1.7b",  "ollama": "qwen3:1.7b", "lmstudio": "lmstudio-community/Qwen3-1.7B-GGUF"},
    {"id": "qwen3-coder", "omlx": "Qwen3-Coder-MLX-4bit"},
]


def test_returns_full_cross_product_for_supported_combinations():
    combos = planned_combos(
        models=MODELS[:1],  # qwen3-1.7b (has ollama + lmstudio)
        agents=["pi", "direct"],
        backends=["ollama", "lmstudio"],
        agent_registry=REGISTRY,
    )
    assert set(combos) == {
        ("ollama",   "pi",     "qwen3-1.7b"),
        ("ollama",   "direct", "qwen3-1.7b"),
        ("lmstudio", "pi",     "qwen3-1.7b"),
        ("lmstudio", "direct", "qwen3-1.7b"),
    }


def test_skips_model_missing_alias_for_backend():
    combos = planned_combos(
        models=MODELS,  # qwen3-coder has no ollama alias
        agents=["pi"],
        backends=["ollama"],
        agent_registry=REGISTRY,
    )
    assert len(combos) == 1
    assert combos[0] == ("ollama", "pi", "qwen3-1.7b")


def test_skips_agent_backend_pair_not_in_supports_backends():
    # opencode only supports ollama, not lmstudio
    combos = planned_combos(
        models=MODELS[:1],
        agents=["opencode"],
        backends=["lmstudio"],
        agent_registry=REGISTRY,
    )
    assert combos == []


def test_skips_unknown_agent():
    combos = planned_combos(
        models=MODELS[:1],
        agents=["ghost-agent"],
        backends=["ollama"],
        agent_registry=REGISTRY,
    )
    assert combos == []


def test_returns_empty_when_no_combos_survive_filtering():
    combos = planned_combos(
        models=[{"id": "m", "lmstudio": "m"}],
        agents=["opencode"],  # opencode doesn't support lmstudio
        backends=["lmstudio"],
        agent_registry=REGISTRY,
    )
    assert combos == []


def test_planned_step_count_multiplies_combos_by_total_iters():
    combos = [("ollama", "pi", "m1"), ("ollama", "pi", "m2")]
    assert planned_step_count(combos, iterations=3, warmup=1) == 8


def test_planned_step_count_is_zero_for_empty_combos():
    assert planned_step_count([], iterations=5, warmup=2) == 0