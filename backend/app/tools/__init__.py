from app.tools.base import RISK_LEVELS, Tool, ToolContext, ToolError
from app.tools.registry import get_tool, list_tools, register


def get_default_tools() -> list[Tool]:
    """Instancia y registra las herramientas núcleo de la Fase 1."""
    from app.memory.tool import build_search_memory_tool
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
    ]
    for tool in tools:
        register(tool)
    return tools


__all__ = [
    "RISK_LEVELS",
    "Tool",
    "ToolContext",
    "ToolError",
    "get_default_tools",
    "get_tool",
    "list_tools",
    "register",
]
