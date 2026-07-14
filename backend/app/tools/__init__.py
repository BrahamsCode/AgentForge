from app.tools.base import RISK_LEVELS, Tool, ToolContext, ToolError
from app.tools.registry import get_tool, list_tools, register


def get_default_tools() -> list[Tool]:
    """Instancia y registra las herramientas núcleo (web, archivos, sandbox,
    memoria y navegador)."""
    from app.memory.tool import build_search_memory_tool
    from app.tools.browser import BrowserTool
    from app.tools.files import ReadFileTool, WriteFileTool
    from app.tools.run_python import RunPythonTool
    from app.tools.web_fetch import WebFetchTool
    from app.tools.web_search import WebSearchTool

    tools = [
        WebSearchTool(),
        WebFetchTool(),
        ReadFileTool(),
        WriteFileTool(),
        RunPythonTool(),
        build_search_memory_tool(),
        BrowserTool(),  # v2: automatización web (Playwright, import perezoso)
    ]
    for tool in tools:
        register(tool)
    return tools


async def get_runtime_tools() -> list[Tool]:
    """Herramientas por defecto + las expuestas por los servidores MCP
    configurados (v2). Es lo que usa el motor al ejecutar un run."""
    from app.config import get_settings
    from app.tools.mcp import build_mcp_tools

    tools = get_default_tools()
    for server in get_settings().mcp_servers:
        try:
            mcp_tools = await build_mcp_tools(
                server["name"], server["url"], server.get("headers")
            )
            for tool in mcp_tools:
                register(tool)
            tools.extend(mcp_tools)
        except Exception:  # un servidor MCP caído no debe tumbar el run
            import logging

            logging.getLogger(__name__).warning(
                "No se pudieron cargar las tools del servidor MCP %s", server.get("name")
            )
    return tools


__all__ = [
    "RISK_LEVELS",
    "Tool",
    "ToolContext",
    "ToolError",
    "get_default_tools",
    "get_runtime_tools",
    "get_tool",
    "list_tools",
    "register",
]
