from app.tools.base import Tool

_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    _REGISTRY[tool.name] = tool
    return tool


def get_tool(name: str) -> Tool:
    return _REGISTRY[name]


def list_tools() -> list[Tool]:
    return list(_REGISTRY.values())
