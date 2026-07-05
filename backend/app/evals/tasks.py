"""Tareas de referencia para la suite de evals (DESIGN.md sección 9 y 10).

Cada tarea tiene un objetivo, el proveedor/modelo a usar y una función de
scoring que evalúa la salida (asserts deterministas y/o LLM-as-judge). El
scoring devuelve un float en [0, 1].
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True)
class EvalTask:
    id: str
    goal: str
    provider: str
    model: str
    score_fn: Callable[[str], float]
    weight: float = 1.0


def _contains_all(keywords: list[str]) -> Callable[[str], float]:
    def scorer(output: str) -> float:
        low = output.lower()
        hits = sum(1 for k in keywords if k.lower() in low)
        return hits / len(keywords)
    return scorer


def _is_number_close(expected: float, tol: float = 1e-6) -> Callable[[str], float]:
    import re

    def scorer(output: str) -> float:
        nums = re.findall(r"-?\d+(?:\.\d+)?", output)
        return 1.0 if any(abs(float(n) - expected) <= tol for n in nums) else 0.0
    return scorer


# Línea base fija de 10 tareas de referencia. Determinista y sin red: sirve
# para detectar regresiones de scaffolding/parsing al cambiar prompts o el
# motor. (Las tareas con LLM real se activan con AGENTFORGE_EVAL_LIVE=1.)
REFERENCE_TASKS: list[EvalTask] = [
    EvalTask("math-sum", "Suma 27 y 453.", "anthropic", "claude-haiku-4-5", _is_number_close(480)),
    EvalTask("math-mul", "Multiplica 27 por 453.", "anthropic", "claude-haiku-4-5", _is_number_close(12231)),
    EvalTask("capital", "¿Cuál es la capital de Perú?", "anthropic", "claude-haiku-4-5", _contains_all(["lima"])),
    EvalTask("list", "Nombra tres lenguajes de programación.", "anthropic", "claude-haiku-4-5", lambda o: min(len([w for w in ["python", "java", "javascript", "go", "rust", "c++", "ruby", "typescript"] if w in o.lower()]), 3) / 3),
    EvalTask("summary", "Resume en una frase qué es un agente de IA.", "anthropic", "claude-sonnet-5", _contains_all(["agente"])),
    EvalTask("keyword", "Explica qué es RAG en recuperación aumentada.", "anthropic", "claude-sonnet-5", _contains_all(["recuper", "context"])),
    EvalTask("translate", "Traduce al inglés: 'el gato duerme'.", "anthropic", "claude-haiku-4-5", _contains_all(["cat", "sleep"])),
    EvalTask("classify", "Clasifica el sentimiento (positivo/negativo): 'Me encantó el producto'.", "anthropic", "claude-haiku-4-5", _contains_all(["positiv"])),
    EvalTask("json", "Devuelve un JSON con la clave 'ok' en true.", "anthropic", "claude-haiku-4-5", _contains_all(["ok", "true"])),
    EvalTask("reason", "Si un tren recorre 120 km en 2 horas, ¿cuál es su velocidad media en km/h?", "anthropic", "claude-sonnet-5", _is_number_close(60)),
]
