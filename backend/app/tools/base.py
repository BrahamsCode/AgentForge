"""Base de la capa de herramientas (Tool Layer) — Fase 1.

Contrato (ver docs/DESIGN.md sección 4.2 "Capa de herramientas"):
cada herramienta declara un JSON Schema de entrada, un nivel de riesgo
(`safe` / `sensitive` / `dangerous`), una implementación async y un timeout.
El caller (motor de ejecución) aplica ``asyncio.wait_for`` con
``timeout_seconds``; las herramientas NO gestionan su propio wait_for.
"""

from __future__ import annotations

import abc
import pathlib

RISK_LEVELS = ("safe", "sensitive", "dangerous")


class ToolError(Exception):
    """Error recuperable de una herramienta.

    El mensaje se devuelve al LLM como resultado del tool call para que
    pueda corregir sus argumentos o cambiar de estrategia. Cualquier otra
    excepción se considera un bug y burbujea al motor de ejecución.
    """


class ToolContext:
    """Contexto de ejecución que el motor pasa a cada tool call.

    ``workspace_dir`` es el directorio raíz permitido para operaciones de
    archivos: ninguna herramienta debe leer/escribir fuera de él.

    En runs multi-agente el motor rellena la identidad del agente que ejecuta
    (``agent_id``/``agent_name``) y el ``roster`` {nombre: id} de sus pares,
    para que las herramientas de mensajería directa sepan quién envía y a quién
    puede escribir. En runs single-agent quedan vacíos.
    """

    def __init__(
        self,
        run_id: str,
        workspace_dir: pathlib.Path,
        *,
        agent_id: str | None = None,
        agent_name: str | None = None,
        roster: dict[str, str] | None = None,
    ):
        self.run_id = run_id
        self.workspace_dir = pathlib.Path(workspace_dir)
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.roster = roster or {}


class Tool(abc.ABC):
    """Clase base de todas las herramientas.

    Atributos de clase que cada subclase debe definir:
      - ``name``: identificador snake_case único (se usa en el registry y
        en las definiciones de tools que ve el LLM).
      - ``description``: descripción para el LLM.
      - ``input_schema``: JSON Schema (dict) del input, con "type": "object".
      - ``risk_level``: "safe" | "sensitive" | "dangerous" (default "safe").
        Los niveles sensitive/dangerous disparan human-in-the-loop.
      - ``timeout_seconds``: presupuesto de tiempo que el caller aplica con
        ``asyncio.wait_for`` (default 30).
    """

    name: str
    description: str
    input_schema: dict
    risk_level: str = "safe"
    timeout_seconds: int = 30

    @abc.abstractmethod
    async def run(self, args: dict, ctx: ToolContext) -> str:
        """Ejecuta la herramienta y devuelve el resultado como texto.

        En error recuperable lanza ``ToolError(mensaje)``; el mensaje se
        devuelve al LLM.
        """
        raise NotImplementedError
