"""Tareas de evals de comportamiento agéntico multi-paso (complemento offline).

Módulo aparte y complementario a `app.evals.tasks`: no lo modifica. Reutiliza el
mismo `EvalTask` y el mismo contrato de scoring (funciones que devuelven un float
en [0, 1]). Estas tareas premian que la salida evidencie comportamiento agéntico
—haber usado herramientas, seguido pasos ordenados o razonado antes de actuar—
en lugar de solo contener la respuesta final.

Se ejecuta con `run_suite(tasks=AGENTIC_TASKS, solver=offline_solver)` para
verificar el harness y el scoring sin gastar tokens ni red.
"""

import re
from collections.abc import Callable

from app.evals.tasks import EvalTask


def _mentions_tools(tools: list[str], *, min_fraction: float = 0.5) -> Callable[[str], float]:
    """Premia mencionar el uso de las herramientas esperadas.

    Devuelve la fracción de herramientas citadas; 0 si no se menciona ninguna
    señal de "uso de herramienta".
    """

    use_signals = ("us", "invoc", "llam", "ejecut", "consult", "buscar", "búsqueda")

    def scorer(output: str) -> float:
        low = output.lower()
        if not any(sig in low for sig in use_signals):
            return 0.0
        hits = sum(1 for t in tools if t.lower() in low)
        frac = hits / len(tools)
        return frac if frac >= min_fraction else frac * 0.5

    return scorer


def _ordered_steps(markers: list[str]) -> Callable[[str], float]:
    """Premia que los marcadores de pasos aparezcan en orden dentro de la salida.

    Devuelve la fracción de transiciones consecutivas que respetan el orden.
    """

    def scorer(output: str) -> float:
        low = output.lower()
        positions = [low.find(m.lower()) for m in markers]
        if any(p < 0 for p in positions):
            present = [p for p in positions if p >= 0]
            # Penaliza ausencias: base = fracción presente.
            return len(present) / len(markers) * 0.5
        ordered = sum(1 for a, b in zip(positions, positions[1:]) if a < b)
        return ordered / (len(markers) - 1)

    return scorer


def _plan_then_act(keywords: list[str]) -> Callable[[str], float]:
    """Premia evidencia de planificar antes de actuar y de reportar el resultado."""

    def scorer(output: str) -> float:
        low = output.lower()
        has_plan = any(k in low for k in ("plan", "primero", "paso 1", "voy a"))
        has_action = any(k in low for k in ("ejecut", "us", "invoc", "llam"))
        has_result = any(k in low for k in ("resultado", "final", "conclu", "listo"))
        kw_hits = sum(1 for k in keywords if k.lower() in low) / max(len(keywords), 1)
        structural = (has_plan + has_action + has_result) / 3
        return round(0.5 * structural + 0.5 * kw_hits, 4)

    return scorer


def _cites_count(min_citations: int) -> Callable[[str], float]:
    """Premia citar/numerar al menos N pasos o fuentes (p. ej. '1.', '[1]')."""

    def scorer(output: str) -> float:
        markers = re.findall(r"(?:^|\s)(?:\d+[\.\)]|\[\d+\])", output)
        return min(len(markers), min_citations) / min_citations

    return scorer


AGENTIC_TASKS: list[EvalTask] = [
    EvalTask(
        "agentic-research",
        "Investiga la capital de Francia usando búsqueda web y reporta la fuente.",
        "anthropic",
        "claude-opus-4-8",
        _mentions_tools(["web_search", "web_fetch"]),
    ),
    EvalTask(
        "agentic-file-pipeline",
        "Lee un archivo de datos, calcula el total y escribe el resultado.",
        "anthropic",
        "claude-opus-4-8",
        _ordered_steps(["leer", "calcular", "escribir"]),
    ),
    EvalTask(
        "agentic-plan-act",
        "Resuelve una tarea de análisis: planifica, ejecuta herramientas y reporta el resultado.",
        "anthropic",
        "claude-opus-4-8",
        _plan_then_act(["análisis", "datos"]),
    ),
    EvalTask(
        "agentic-multistep-cite",
        "Enumera los pasos que seguiste para completar la tarea, al menos tres.",
        "anthropic",
        "claude-opus-4-8",
        _cites_count(3),
    ),
    EvalTask(
        "agentic-tool-python",
        "Calcula la suma de 1 a 100 ejecutando código Python con run_python.",
        "anthropic",
        "claude-opus-4-8",
        _mentions_tools(["run_python"]),
        weight=1.5,
    ),
    EvalTask(
        "agentic-delegate",
        "Delega la subtarea de traducción a otro agente y sintetiza su respuesta.",
        "anthropic",
        "claude-opus-4-8",
        _ordered_steps(["delegar", "recibir", "sintetizar"]),
    ),
]


# Respuestas "buenas" de referencia para el modo offline: cada una evidencia el
# comportamiento agéntico que el scorer correspondiente premia.
AGENTIC_OFFLINE_ANSWERS: dict[str, str] = {
    "agentic-research": (
        "Usé la herramienta web_search para buscar 'capital de Francia' y luego "
        "invoqué web_fetch sobre la fuente. La capital es París (fuente: Wikipedia)."
    ),
    "agentic-file-pipeline": (
        "Primero voy a leer el archivo de datos con la herramienta de archivos, "
        "después calcular el total sumando las filas, y finalmente escribir el "
        "resultado en el archivo de salida."
    ),
    "agentic-plan-act": (
        "Plan: primero preparo el análisis de datos. Luego ejecuté las herramientas "
        "necesarias y usé run_python para procesar. Resultado final: el cálculo quedó listo."
    ),
    "agentic-multistep-cite": (
        "Pasos seguidos:\n1. Leí la entrada.\n2. Ejecuté las herramientas.\n"
        "3. Verifiqué y reporté el resultado final."
    ),
    "agentic-tool-python": (
        "Ejecuté run_python invocando la herramienta con `sum(range(1, 101))`; "
        "el resultado devuelto fue 5050."
    ),
    "agentic-delegate": (
        "Voy a delegar la subtarea de traducción al agente traductor; tras recibir "
        "su respuesta, procedo a sintetizar el resultado final para el usuario."
    ),
}


async def offline_solver(task: EvalTask) -> str:
    """Solucionador offline determinista para AGENTIC_TASKS.

    Devuelve la respuesta "buena" de referencia (o cadena vacía si la tarea no
    está mapeada), replicando el contrato de `app.evals.runner._offline_solver`.
    """

    return AGENTIC_OFFLINE_ANSWERS.get(task.id, "")
