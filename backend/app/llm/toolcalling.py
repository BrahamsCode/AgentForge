"""Tool calling multi-proveedor con interfaz uniforme para el motor agéntico.

`ToolCallingSession` mantiene el historial de mensajes (serializable, para
checkpoints) y expone dos operaciones: enviar un mensaje de usuario y devolver
resultados de herramientas. Cada operación produce un `StepOutcome` con el
texto, las tool calls solicitadas, tokens, costo y latencia.

NO toca app/llm/client.py: ese cliente es para completions simples sin
herramientas; este módulo implementa el protocolo de tool calling nativo de
cada proveedor (Anthropic tool_use/tool_result, OpenAI function calling,
Ollama /api/chat con tools).
"""

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.llm.pricing import estimate_cost_usd

# Modelos Anthropic 4.6+ que rechazan parámetros de sampling (temperature/top_p)
# y usan thinking adaptativo. Mismo criterio que app/llm/client.py.
_ANTHROPIC_ADAPTIVE_PREFIXES = (
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-5",
)

_MAX_TOKENS = 16000


@dataclass(slots=True)
class ToolCallRequest:
    id: str
    name: str
    args: dict


@dataclass(slots=True)
class StepOutcome:
    text: str
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


def _tool_spec(tool: Any) -> dict:
    """Extrae (name, description, input_schema) de un Tool del contrato app.tools."""
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
    }


class ToolCallingSession:
    """Sesión de conversación con tool calling, uniforme entre proveedores.

    El historial (`export_messages`) es JSON-serializable para poder guardarlo
    en `runs.checkpoint` y reanudar.
    """

    def __init__(self, provider: str, model: str, system_prompt: str, tools: list) -> None:
        if provider not in ("anthropic", "openai", "ollama"):
            raise ValueError(f"Proveedor LLM no soportado: {provider!r}")
        self.provider = provider
        self.model = model
        self.system_prompt = system_prompt or ""
        self.tools = list(tools)
        # Historial serializable. Para openai/ollama el system va como primer
        # mensaje; para anthropic va como parámetro `system` aparte.
        self._messages: list[dict] = []
        if provider in ("openai", "ollama") and self.system_prompt:
            self._messages.append({"role": "system", "content": self.system_prompt})

    # ------------------------------------------------------------------ API

    async def send_user(self, content: str) -> StepOutcome:
        self._messages.append({"role": "user", "content": content})
        return await self._step()

    async def send_tool_results(self, results: list[tuple[str, str, bool]]) -> StepOutcome:
        """results: lista de (call_id, output, is_error)."""
        if self.provider == "anthropic":
            blocks = [
                {
                    "type": "tool_result",
                    "tool_use_id": call_id,
                    "content": output,
                    "is_error": is_error,
                }
                for call_id, output, is_error in results
            ]
            self._messages.append({"role": "user", "content": blocks})
        elif self.provider == "openai":
            for call_id, output, _is_error in results:
                self._messages.append(
                    {"role": "tool", "tool_call_id": call_id, "content": output}
                )
        else:  # ollama
            for _call_id, output, _is_error in results:
                self._messages.append({"role": "tool", "content": output})
        return await self._step()

    def export_messages(self) -> list:
        """Historial serializable (para checkpoint/reanudación)."""
        return json.loads(json.dumps(self._messages, default=str))

    # ------------------------------------------------------------ internos

    async def _step(self) -> StepOutcome:
        started = time.monotonic()
        if self.provider == "anthropic":
            outcome = await self._step_anthropic()
        elif self.provider == "openai":
            outcome = await self._step_openai()
        else:
            outcome = await self._step_ollama()
        outcome.latency_ms = int((time.monotonic() - started) * 1000)
        outcome.cost_usd = estimate_cost_usd(self.model, outcome.tokens_in, outcome.tokens_out)
        return outcome

    async def _step_anthropic(self) -> StepOutcome:
        from anthropic import AsyncAnthropic

        from app.config import get_settings

        settings = get_settings()
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY no está configurada")
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)

        params: dict = {
            "model": self.model,
            "max_tokens": _MAX_TOKENS,
            "messages": self._messages,
            "tools": [_tool_spec(t) for t in self.tools],
        }
        if self.system_prompt:
            params["system"] = self.system_prompt
        if self.model.startswith(_ANTHROPIC_ADAPTIVE_PREFIXES):
            # 4.6+: thinking adaptativo; NO pasar temperature/top_p (devuelven 400).
            params["thinking"] = {"type": "adaptive"}

        response = await client.messages.create(**params)

        text_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []
        serialized_blocks: list[dict] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCallRequest(id=block.id, name=block.name, args=dict(block.input or {}))
                )
            # Serializar TODOS los bloques (incluidos thinking) para poder
            # devolverlos intactos en el siguiente turno.
            try:
                serialized_blocks.append(block.model_dump())
            except AttributeError:
                serialized_blocks.append({"type": getattr(block, "type", "unknown")})

        self._messages.append({"role": "assistant", "content": serialized_blocks})
        return StepOutcome(
            text="".join(text_parts),
            tool_calls=tool_calls,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
        )

    async def _step_openai(self) -> StepOutcome:
        from openai import AsyncOpenAI

        from app.config import get_settings

        settings = get_settings()
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY no está configurada")
        client = AsyncOpenAI(api_key=settings.openai_api_key)

        kwargs: dict = {
            "model": self.model,
            "messages": self._messages,
            "max_completion_tokens": _MAX_TOKENS,
            "tools": [
                {"type": "function", "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                }}
                for t in self.tools
            ],
        }
        response = await client.chat.completions.create(**kwargs)
        message = response.choices[0].message

        tool_calls: list[ToolCallRequest] = []
        serialized_calls: list[dict] = []
        for tc in message.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            tool_calls.append(ToolCallRequest(id=tc.id, name=tc.function.name, args=args))
            serialized_calls.append(
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
            )

        assistant_msg: dict = {"role": "assistant", "content": message.content or ""}
        if serialized_calls:
            assistant_msg["tool_calls"] = serialized_calls
        self._messages.append(assistant_msg)

        usage = response.usage
        return StepOutcome(
            text=message.content or "",
            tool_calls=tool_calls,
            tokens_in=usage.prompt_tokens if usage else 0,
            tokens_out=usage.completion_tokens if usage else 0,
        )

    async def _step_ollama(self) -> StepOutcome:
        from app.config import get_settings

        base_url = get_settings().ollama_base_url.rstrip("/")
        payload: dict = {
            "model": self.model,
            "messages": self._messages,
            "stream": False,
            "tools": [
                {"type": "function", "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                }}
                for t in self.tools
            ],
        }
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(f"{base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {}) or {}
        tool_calls: list[ToolCallRequest] = []
        for i, tc in enumerate(message.get("tool_calls") or []):
            fn = tc.get("function", {}) or {}
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            call_id = tc.get("id") or f"ollama_call_{len(self._messages)}_{i}"
            tool_calls.append(ToolCallRequest(id=call_id, name=fn.get("name", ""), args=args))

        # Si el modelo no devuelve tool_calls, es texto final.
        self._messages.append(
            {
                "role": "assistant",
                "content": message.get("content", ""),
                **({"tool_calls": message.get("tool_calls")} if tool_calls else {}),
            }
        )
        return StepOutcome(
            text=message.get("content", ""),
            tool_calls=tool_calls,
            tokens_in=data.get("prompt_eval_count", 0),
            tokens_out=data.get("eval_count", 0),
        )
