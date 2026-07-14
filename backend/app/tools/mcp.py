"""Soporte MCP (Model Context Protocol) — backlog v2.

Conecta servidores MCP de terceros (Streamable HTTP + JSON-RPC 2.0) como
herramientas nativas de AgentForge. Cada tool remota se envuelve en un
``MCPTool`` con ``risk_level="sensitive"`` (herramienta externa → requiere
aprobación por defecto, encaja con el guardrail existente).

El cliente se implementa a mano sobre ``httpx`` (sin el paquete ``mcp``):

  - ``initialize``           handshake initialize + notifications/initialized
  - ``tools/list``           descubrimiento de herramientas
  - ``tools/call``           invocación de una herramienta

Las salidas de las herramientas externas se envuelven en marcadores de
contenido NO CONFIABLE (misma mitigación de prompt injection que web_fetch,
docs/DESIGN.md sección 9).
"""

from __future__ import annotations

import json
import re

import httpx

from app.tools.base import Tool, ToolContext, ToolError
from app.tools.web_fetch import UNTRUSTED_CLOSE, UNTRUSTED_OPEN

# Versión del protocolo que anunciamos en el handshake.
PROTOCOL_VERSION = "2025-06-18"

_CLIENT_INFO = {"name": "AgentForge", "version": "0.1"}


def _sanitize(fragment: str) -> str:
    """Normaliza un fragmento de nombre a snake-safe ([0-9A-Za-z_])."""
    return re.sub(r"[^0-9A-Za-z_]+", "_", fragment).strip("_") or "tool"


class MCPClient:
    """Cliente de un servidor MCP remoto vía Streamable HTTP / JSON-RPC 2.0.

    Cada llamada abre un ``httpx.AsyncClient`` efímero (POST al mismo endpoint).
    Si el servidor gestiona sesión (cabecera ``Mcp-Session-Id`` en la respuesta
    a initialize) la conservamos y reenviamos en las peticiones siguientes.
    """

    def __init__(
        self,
        server_name: str,
        url: str,
        headers: dict | None = None,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.server_name = server_name
        self.url = url
        self._extra_headers = dict(headers or {})
        self._timeout = timeout
        self._session_id: str | None = None
        self._next_id = 0
        self._initialized = False

    # -- transporte ---------------------------------------------------------

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self._extra_headers,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    @staticmethod
    def _decode_body(response: httpx.Response) -> dict | None:
        """Extrae el objeto JSON-RPC de una respuesta JSON o SSE."""
        content_type = response.headers.get("content-type", "")
        text = response.text
        if "text/event-stream" in content_type:
            # SSE: nos quedamos con la concatenación de las líneas ``data:``.
            data_parts = [
                line[len("data:"):].lstrip()
                for line in text.splitlines()
                if line.startswith("data:")
            ]
            text = "".join(data_parts)
        text = text.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except (ValueError, json.JSONDecodeError) as exc:
            raise ToolError(
                f"Respuesta no-JSON del servidor MCP '{self.server_name}': {exc}"
            ) from exc

    async def _post(self, payload: dict, *, expect_response: bool = True) -> dict | None:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=True
            ) as client:
                response = await client.post(
                    self.url, json=payload, headers=self._headers()
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ToolError(
                f"Fallo de red con el servidor MCP '{self.server_name}': {exc}"
            ) from exc

        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id

        if not expect_response:
            return None

        message = self._decode_body(response)
        if message is None:
            raise ToolError(
                f"Respuesta vacía del servidor MCP '{self.server_name}'"
            )
        if isinstance(message, dict) and message.get("error"):
            err = message["error"]
            detail = err.get("message", err) if isinstance(err, dict) else err
            raise ToolError(
                f"Error JSON-RPC del servidor MCP '{self.server_name}': {detail}"
            )
        return message

    async def _request(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        message = await self._post(payload, expect_response=True)
        assert message is not None  # _post lanza ToolError si es None
        return message.get("result", {})

    async def _notify(self, method: str, params: dict | None = None) -> None:
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        await self._post(payload, expect_response=False)

    # -- API MCP ------------------------------------------------------------

    async def initialize(self) -> dict:
        """Handshake: initialize + notifications/initialized."""
        result = await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": _CLIENT_INFO,
            },
        )
        await self._notify("notifications/initialized")
        self._initialized = True
        return result

    async def list_tools(self) -> list[dict]:
        """Devuelve la lista de tools (name/description/inputSchema)."""
        result = await self._request("tools/list")
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            raise ToolError(
                f"Respuesta tools/list inválida del servidor MCP '{self.server_name}'"
            )
        return tools

    async def call_tool(self, name: str, arguments: dict | None = None) -> str:
        """Invoca una tool remota y concatena sus bloques de texto.

        Si el resultado trae ``isError=true`` lanza ``ToolError``.
        """
        result = await self._request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )
        blocks = result.get("content", []) or []
        texts = [
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = "\n".join(t for t in texts if t)

        if result.get("isError"):
            raise ToolError(
                f"La herramienta MCP '{name}' devolvió un error: {text or 'sin detalle'}"
            )
        return text


class MCPTool(Tool):
    """Envuelve una tool concreta de un servidor MCP como herramienta nativa.

    El nombre expuesto al LLM es ``mcp__<server>__<tool>`` (saneado). El
    ``input_schema`` y la ``description`` provienen del servidor. Se marca como
    ``sensitive`` porque es una herramienta externa (aprobación por defecto).
    """

    risk_level = "sensitive"
    timeout_seconds = 60

    def __init__(self, client: MCPClient, tool_spec: dict) -> None:
        self._client = client
        self._remote_name = tool_spec["name"]
        self.name = f"mcp__{_sanitize(client.server_name)}__{_sanitize(self._remote_name)}"
        self.description = tool_spec.get("description") or (
            f"Herramienta externa '{self._remote_name}' del servidor MCP "
            f"'{client.server_name}'. Salida marcada como NO CONFIABLE."
        )
        schema = tool_spec.get("inputSchema") or {"type": "object", "properties": {}}
        if "type" not in schema:
            schema = {**schema, "type": "object"}
        self.input_schema = schema

    async def run(self, args: dict, ctx: ToolContext) -> str:
        text = await self._client.call_tool(self._remote_name, args or {})
        return f"{UNTRUSTED_OPEN}\n{text}\n{UNTRUSTED_CLOSE}"


async def build_mcp_tools(
    server_name: str,
    url: str,
    headers: dict | None = None,
) -> list[MCPTool]:
    """Factory: conecta con un servidor MCP y devuelve una MCPTool por tool.

    Hace el handshake ``initialize`` y descubre las herramientas con
    ``tools/list``. El coordinador cablea el resultado en get_default_tools/config.
    """
    client = MCPClient(server_name, url, headers)
    await client.initialize()
    specs = await client.list_tools()
    return [MCPTool(client, spec) for spec in specs if spec.get("name")]
