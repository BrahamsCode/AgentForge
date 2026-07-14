"""Ejecutor de la suite de evals: puntúa cada tarea y compara con la línea base.

En CI corre en modo offline (respuestas simuladas por un solucionador fijo) para
verificar el scoring y el harness sin gastar tokens; con
AGENTFORGE_EVAL_LIVE=1 llama a los LLM reales vía el cliente unificado.
"""

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass

from app.evals.tasks import REFERENCE_TASKS, EvalTask


@dataclass(slots=True)
class TaskResult:
    id: str
    score: float
    weight: float
    output_preview: str


@dataclass(slots=True)
class EvalReport:
    total_score: float           # promedio ponderado en [0, 1]
    passed: int
    tasks: list[TaskResult]

    def to_json(self) -> str:
        return json.dumps(
            {"total_score": round(self.total_score, 4), "passed": self.passed,
             "tasks": [asdict(t) for t in self.tasks]},
            indent=2, ensure_ascii=False,
        )


async def _live_solver(task: EvalTask) -> str:
    from app.llm.client import get_llm_client

    result = await get_llm_client().complete(
        provider=task.provider, model=task.model,
        system_prompt="Responde de forma breve y directa.", user_message=task.goal,
    )
    return result.text


async def run_suite(
    tasks: list[EvalTask] | None = None,
    *,
    solver: Callable[[EvalTask], Awaitable[str]] | None = None,
    pass_threshold: float = 0.5,
) -> EvalReport:
    tasks = tasks if tasks is not None else REFERENCE_TASKS
    if solver is None:
        solver = _live_solver if os.getenv("AGENTFORGE_EVAL_LIVE") == "1" else _offline_solver

    results: list[TaskResult] = []
    for task in tasks:
        output = await solver(task)
        score = max(0.0, min(1.0, task.score_fn(output)))
        results.append(TaskResult(task.id, round(score, 4), task.weight, output[:120]))

    total_weight = sum(t.weight for t in tasks) or 1.0
    total = sum(r.score * r.weight for r in results) / total_weight
    passed = sum(1 for r in results if r.score >= pass_threshold)
    return EvalReport(total_score=total, passed=passed, tasks=results)


# Solucionador offline determinista: respuestas "correctas" fijas para verificar
# que el scoring reconoce buenas salidas (score alto esperado en CI).
_OFFLINE_ANSWERS = {
    "math-sum": "El resultado es 480.",
    "math-mul": "27 por 453 es 12231.",
    "capital": "La capital de Perú es Lima.",
    "list": "Python, JavaScript y Go.",
    "summary": "Un agente de IA es un sistema autónomo que persigue objetivos.",
    "keyword": "RAG recupera contexto relevante y lo añade al prompt del modelo.",
    "translate": "The cat sleeps.",
    "classify": "El sentimiento es positivo.",
    "json": '{"ok": true}',
    "reason": "La velocidad media es 60 km/h.",
}


async def _offline_solver(task: EvalTask) -> str:
    await asyncio.sleep(0)
    return _OFFLINE_ANSWERS.get(task.id, "")
