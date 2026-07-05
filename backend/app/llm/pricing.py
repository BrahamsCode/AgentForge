"""Tabla de precios por millón de tokens (USD) para calcular el costo de cada llamada.

Actualizada a junio 2026. Los modelos que no aparecen (p. ej. cualquier modelo
de Ollama, que corre local) se consideran costo 0.
"""

# (input $/1M, output $/1M)
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-fable-5": (10.00, 50.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    # OpenAI (aproximados; ajustar según el modelo que se use)
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
}


def estimate_cost_usd(model_name: str, tokens_in: int, tokens_out: int) -> float:
    """Costo estimado en USD de una llamada. Modelos desconocidos/locales → 0."""
    prices = PRICES_PER_MTOK.get(model_name)
    if prices is None:
        return 0.0
    price_in, price_out = prices
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000
