"""Tests de la suite de evals agénticas (offline): scoring, no-regresión y serialización."""

import json

from app.evals.agentic_tasks import (
    AGENTIC_OFFLINE_ANSWERS,
    AGENTIC_TASKS,
    offline_solver,
)
from app.evals.runner import run_suite
from app.evals.tasks import EvalTask


async def test_offline_agentic_suite_scores_high():
    report = await run_suite(tasks=AGENTIC_TASKS, solver=offline_solver)
    assert len(report.tasks) == len(AGENTIC_TASKS)
    # Las respuestas de referencia evidencian comportamiento agéntico → score alto.
    assert report.total_score >= 0.8
    assert 0.0 <= report.total_score <= 1.0
    assert report.passed == len(AGENTIC_TASKS)


async def test_bad_solver_scores_low():
    async def bad_solver(_task: EvalTask) -> str:
        return "no tengo idea"

    report = await run_suite(tasks=AGENTIC_TASKS, solver=bad_solver)
    assert report.total_score < 0.2


async def test_report_is_json_serializable():
    report = await run_suite(tasks=AGENTIC_TASKS, solver=offline_solver)
    parsed = json.loads(report.to_json())
    assert "total_score" in parsed
    assert len(parsed["tasks"]) == len(AGENTIC_TASKS)
    assert {t["id"] for t in parsed["tasks"]} == {t.id for t in AGENTIC_TASKS}


def test_every_task_has_offline_answer():
    # Cada tarea debe tener una respuesta de referencia mapeada.
    assert {t.id for t in AGENTIC_TASKS} == set(AGENTIC_OFFLINE_ANSWERS)


def test_scorers_return_normalized_floats():
    # El contrato de scoring: floats (potencialmente fuera de [0,1], que run_suite
    # recorta). Aquí verificamos que devuelven un número finito para cada respuesta.
    for task in AGENTIC_TASKS:
        score = task.score_fn(AGENTIC_OFFLINE_ANSWERS[task.id])
        assert isinstance(score, float)
        assert score >= 0.8  # respuesta buena → puntúa alto antes del clamp


async def test_missing_answer_yields_empty_output():
    other = EvalTask("no-existe", "x", "anthropic", "m", lambda o: 1.0)
    assert await offline_solver(other) == ""
