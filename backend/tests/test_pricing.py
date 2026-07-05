from app.llm.pricing import estimate_cost_usd


def test_known_model_cost():
    # claude-opus-4-8: $5/M entrada, $25/M salida
    cost = estimate_cost_usd("claude-opus-4-8", tokens_in=1_000_000, tokens_out=1_000_000)
    assert cost == 30.0


def test_partial_tokens():
    cost = estimate_cost_usd("claude-haiku-4-5", tokens_in=1000, tokens_out=500)
    assert abs(cost - (1000 * 1.0 + 500 * 5.0) / 1_000_000) < 1e-12


def test_unknown_or_local_model_is_free():
    assert estimate_cost_usd("llama3.3:70b", 5000, 5000) == 0.0
