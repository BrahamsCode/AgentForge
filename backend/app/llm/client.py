"""Cliente LLM unificado multi-proveedor (Anthropic, OpenAI, Ollama).

Cada agente elige proveedor y modelo; este cliente expone una única operación
`complete()` que devuelve el texto más tokens, costo y latencia — la base de
la observabilidad (trace_steps) de fases posteriores.
"""

import time
from dataclasses import dataclass

import httpx
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.config import get_settings
from app.llm.pricing import estimate_cost_usd

# Modelos Anthropic 4.6+ que rechazan parámetros de sampling (temperature/top_p)
# y usan thinking adaptativo en lugar de budget_tokens.
_ANTHROPIC_NO_SAMPLING_PREFIXES = (
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-5",
)


@dataclass(slots=True)
class LLMResult:
    text: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    model_provider: str
    model_name: str


class LLMClient:
    """Fachada única sobre los tres proveedores soportados."""

    def __init__(self) -> None:
        settings = get_settings()
        self._anthropic = (
            AsyncAnthropic(api_key=settings.anthropic_api_key)
            if settings.anthropic_api_key
            else None
        )
        self._openai = (
            AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        )
        self._ollama_base_url = settings.ollama_base_url.rstrip("/")

    async def complete(
        self,
        *,
        provider: str,
        model: str,
        system_prompt: str,
        user_message: str,
        temperature: float | None = None,
        max_tokens: int = 16000,
    ) -> LLMResult:
        started = time.monotonic()
        if provider == "anthropic":
            text, tokens_in, tokens_out = await self._complete_anthropic(
                model, system_prompt, user_message, temperature, max_tokens
            )
        elif provider == "openai":
            text, tokens_in, tokens_out = await self._complete_openai(
                model, system_prompt, user_message, temperature, max_tokens
            )
        elif provider == "ollama":
            text, tokens_in, tokens_out = await self._complete_ollama(
                model, system_prompt, user_message, temperature
            )
        else:
            raise ValueError(f"Proveedor LLM no soportado: {provider!r}")

        latency_ms = int((time.monotonic() - started) * 1000)
        return LLMResult(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=estimate_cost_usd(model, tokens_in, tokens_out),
            latency_ms=latency_ms,
            model_provider=provider,
            model_name=model,
        )

    async def _complete_anthropic(
        self,
        model: str,
        system_prompt: str,
        user_message: str,
        temperature: float | None,
        max_tokens: int,
    ) -> tuple[str, int, int]:
        if self._anthropic is None:
            raise RuntimeError("ANTHROPIC_API_KEY no está configurada")

        params: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": user_message}],
        }
        if system_prompt:
            params["system"] = system_prompt
        if model.startswith(_ANTHROPIC_NO_SAMPLING_PREFIXES):
            # 4.7+ rechaza temperature/top_p; el thinking adaptativo es el control.
            params["thinking"] = {"type": "adaptive"}
        elif temperature is not None:
            params["temperature"] = temperature

        response = await self._anthropic.messages.create(**params)
        text = "".join(block.text for block in response.content if block.type == "text")
        return text, response.usage.input_tokens, response.usage.output_tokens

    async def _complete_openai(
        self,
        model: str,
        system_prompt: str,
        user_message: str,
        temperature: float | None,
        max_tokens: int,
    ) -> tuple[str, int, int]:
        if self._openai is None:
            raise RuntimeError("OPENAI_API_KEY no está configurada")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})

        kwargs: dict = {"model": model, "messages": messages, "max_completion_tokens": max_tokens}
        if temperature is not None:
            kwargs["temperature"] = temperature

        response = await self._openai.chat.completions.create(**kwargs)
        text = response.choices[0].message.content or ""
        usage = response.usage
        return text, usage.prompt_tokens if usage else 0, usage.completion_tokens if usage else 0

    async def _complete_ollama(
        self,
        model: str,
        system_prompt: str,
        user_message: str,
        temperature: float | None,
    ) -> tuple[str, int, int]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})

        payload: dict = {"model": model, "messages": messages, "stream": False}
        if temperature is not None:
            payload["options"] = {"temperature": temperature}

        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(f"{self._ollama_base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        return (
            data.get("message", {}).get("content", ""),
            data.get("prompt_eval_count", 0),
            data.get("eval_count", 0),
        )


_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
