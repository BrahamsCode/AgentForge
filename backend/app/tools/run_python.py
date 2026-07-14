"""Herramienta run_python: ejecuta código en un contenedor Docker efímero.

Aislamiento (docs/DESIGN.md sección 9 "Sandbox seguro"): sin red, límites de
CPU/RAM/procesos, sistema de archivos de solo lectura salvo el workspace del
run (montado en /workspace) y timeout duro. El código generado por el LLM se
trata como hostil por definición.
"""

import asyncio
import shutil

from app.tools.base import Tool, ToolContext, ToolError

_IMAGE = "python:3.12-slim"
_MAX_OUTPUT = 20_000


class RunPythonTool(Tool):
    name = "run_python"
    description = (
        "Ejecuta código Python 3.12 en un sandbox aislado (sin red, con límites de "
        "CPU/RAM/tiempo). El directorio /workspace es el workspace del run: lee y "
        "escribe archivos ahí. Devuelve stdout+stderr. Úsala para análisis de datos, "
        "cálculos y generación de archivos."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Código Python a ejecutar"},
            "timeout_seconds": {
                "type": "integer",
                "description": "Timeout de ejecución (default 60, máx 120)",
            },
        },
        "required": ["code"],
    }
    risk_level = "sensitive"
    timeout_seconds = 150  # margen sobre el timeout interno del contenedor

    async def run(self, args: dict, ctx: ToolContext) -> str:
        code = str(args.get("code", ""))
        if not code.strip():
            raise ToolError("El argumento 'code' es obligatorio")
        exec_timeout = min(int(args.get("timeout_seconds") or 60), 120)

        if shutil.which("docker") is None:
            raise ToolError(
                "Docker no está disponible en este worker: run_python requiere el "
                "sandbox de contenedores (ver infra/README)"
            )

        ctx.workspace_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            "docker", "run", "--rm",
            "--network", "none",
            "--memory", "512m",
            "--cpus", "1",
            "--pids-limit", "128",
            "--read-only",
            "--tmpfs", "/tmp:size=64m",
            "-v", f"{ctx.workspace_dir}:/workspace:rw",
            "-w", "/workspace",
            "--user", "1000:1000",
            _IMAGE,
            "timeout", str(exec_timeout), "python", "-c", code,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=exec_timeout + 20)
        except TimeoutError:
            raise ToolError(f"El sandbox no respondió en {exec_timeout + 20}s") from None
        except OSError as exc:
            raise ToolError(f"No se pudo lanzar el sandbox: {exc}") from exc

        output = stdout.decode("utf-8", "replace")
        if len(output) > _MAX_OUTPUT:
            output = output[:_MAX_OUTPUT] + f"\n… (salida truncada a {_MAX_OUTPUT} caracteres)"

        if process.returncode == 124:  # exit code de `timeout`
            raise ToolError(f"El código excedió el timeout de {exec_timeout}s.\n{output}")
        if process.returncode != 0:
            # Error de ejecución: se devuelve al LLM para que itere sobre él (CU-2)
            return f"[exit code {process.returncode}]\n{output}"
        return output or "(sin salida)"
