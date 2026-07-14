"""Tests del soporte MCP — sin red.

Se parchea ``httpx.AsyncClient`` por un servidor MCP FALSO en memoria que
responde JSON-RPC 2.0 a initialize / tools/list / tools/call.
"""

import json

import httpx
import pytest

from app.tools import mcp as mcp_mod
from app.tools.base import ToolContext, ToolError
from app.tools.mcp import MCPTool, build_mcp_tools
from app.tools.web_fetch import UNTRUSTED_CLOSE, UNTRUSTED_OPEN


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(run_id="test-run", workspace_dir=tmp_path)


# --- servidor MCP falso en memoria -----------------------------------------

_TOOLS = [
    {
        "name": "get_weather",
        "description": "Devuelve el clima de una ciudad.",
        "inputSchema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
    {
        "name": "roll-dice",  # con guion: fuerza el saneado del nombre
        "description": "Tira un dado.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class _FakeResponse:
    def __init__(self, payload: dict | None, headers: dict | None = None):
        self._payload = payload
        self.headers = {"content-type": "application/json", **(headers or {})}
        self.text = "" if payload is None else json.dumps(payload)

    def raise_for_status(self):
        pass


def _handle(payload: dict) -> _FakeResponse:
    method = payload.get("method")
    req_id = payload.get("id")

    if method == "notifications/initialized":
        # Notificación: sin cuerpo (202 Accepted).
        return _FakeResponse(None)

    if method == "initialize":
        result = {"protocolVersion": mcp_mod.PROTOCOL_VERSION, "serverInfo": {"name": "fake"}}
    elif method == "tools/list":
        result = {"tools": _TOOLS}
    elif method == "tools/call":
        name = payload["params"]["name"]
        if name == "get_weather":
            city = payload["params"]["arguments"].get("city", "?")
            result = {"content": [{"type": "text", "text": f"Soleado en {city}"}]}
        elif name == "boom":
            result = {"content": [{"type": "text", "text": "algo falló"}], "isError": True}
        else:
            result = {"content": [{"type": "text", "text": "ok"}]}
    else:  # pragma: no cover - método inesperado
        return _FakeResponse({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "método desconocido"}})

    return _FakeResponse({"jsonrpc": "2.0", "id": req_id, "result": result})


class _FakeClient:
    def __init__(self, *a, **k): ...

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        return _handle(json)


class _NetworkErrorClient:
    def __init__(self, *a, **k): ...

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        raise httpx.ConnectError("conexión rechazada")


# --- tests -----------------------------------------------------------------


async def test_build_discovers_tools(monkeypatch):
    monkeypatch.setattr(mcp_mod.httpx, "AsyncClient", _FakeClient)

    tools = await build_mcp_tools("clima", "https://mcp.example.com/rpc")

    assert len(tools) == 2
    assert all(isinstance(t, MCPTool) for t in tools)

    by_name = {t.name: t for t in tools}
    assert "mcp__clima__get_weather" in by_name
    assert "mcp__clima__roll_dice" in by_name  # guion saneado a underscore

    weather = by_name["mcp__clima__get_weather"]
    assert weather.risk_level == "sensitive"
    assert weather.input_schema == _TOOLS[0]["inputSchema"]
    assert weather.description == "Devuelve el clima de una ciudad."


async def test_run_wraps_untrusted(ctx, monkeypatch):
    monkeypatch.setattr(mcp_mod.httpx, "AsyncClient", _FakeClient)

    tools = await build_mcp_tools("clima", "https://mcp.example.com/rpc")
    weather = next(t for t in tools if t.name == "mcp__clima__get_weather")

    result = await weather.run({"city": "Lima"}, ctx)

    assert result.startswith(UNTRUSTED_OPEN)
    assert result.endswith(UNTRUSTED_CLOSE)
    assert "Soleado en Lima" in result


async def test_is_error_raises_toolerror(ctx, monkeypatch):
    monkeypatch.setattr(mcp_mod.httpx, "AsyncClient", _FakeClient)

    client = mcp_mod.MCPClient("clima", "https://mcp.example.com/rpc")
    await client.initialize()

    with pytest.raises(ToolError, match="devolvió un error"):
        await client.call_tool("boom", {})


async def test_network_failure_raises_toolerror(monkeypatch):
    monkeypatch.setattr(mcp_mod.httpx, "AsyncClient", _NetworkErrorClient)

    with pytest.raises(ToolError, match="Fallo de red"):
        await build_mcp_tools("clima", "https://mcp.example.com/rpc")
