"""Herramientas read_file / write_file, confinadas al workspace del run."""

from pathlib import Path

from app.tools.base import Tool, ToolContext, ToolError

_MAX_READ_BYTES = 200_000


def _resolve_inside_workspace(raw_path: str, workspace: Path) -> Path:
    """Resuelve un path relativo al workspace y verifica que no escape de él."""
    if not raw_path or not raw_path.strip():
        raise ToolError("El argumento 'path' es obligatorio")
    candidate = (workspace / raw_path.lstrip("/")).resolve()
    workspace_resolved = workspace.resolve()
    if not candidate.is_relative_to(workspace_resolved):
        raise ToolError(f"Path fuera del workspace del run: {raw_path!r}")
    return candidate


class ReadFileTool(Tool):
    name = "read_file"
    description = "Lee un archivo de texto del workspace del run."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Ruta relativa dentro del workspace"},
        },
        "required": ["path"],
    }
    risk_level = "safe"
    timeout_seconds = 10

    async def run(self, args: dict, ctx: ToolContext) -> str:
        path = _resolve_inside_workspace(str(args.get("path", "")), ctx.workspace_dir)
        if not path.is_file():
            raise ToolError(f"El archivo no existe: {args.get('path')!r}")
        data = path.read_bytes()
        if len(data) > _MAX_READ_BYTES:
            raise ToolError(f"Archivo demasiado grande (>{_MAX_READ_BYTES} bytes)")
        return data.decode("utf-8", "replace")


class WriteFileTool(Tool):
    name = "write_file"
    description = "Escribe (o sobreescribe) un archivo de texto en el workspace del run."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Ruta relativa dentro del workspace"},
            "content": {"type": "string", "description": "Contenido a escribir"},
        },
        "required": ["path", "content"],
    }
    risk_level = "sensitive"
    timeout_seconds = 10

    async def run(self, args: dict, ctx: ToolContext) -> str:
        path = _resolve_inside_workspace(str(args.get("path", "")), ctx.workspace_dir)
        content = str(args.get("content", ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return f"Escrito {len(content)} caracteres en {path.relative_to(ctx.workspace_dir.resolve())}"
