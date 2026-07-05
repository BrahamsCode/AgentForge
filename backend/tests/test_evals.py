"""Test de la suite de evals: verifica el scoring y el harness en modo offline."""

from app.evals.runner import run_suite
from app.evals.tasks import REFERENCE_TASKS, EvalTask


async def test_offline_suite_scores_high():
    report = await run_suite()
    assert len(report.tasks) == len(REFERENCE_TASKS)
    # El solucionador offline da respuestas correctas → score alto (no-regresión)
    assert report.total_score >= 0.85
    assert report.passed >= 9
    assert 0.0 <= report.total_score <= 1.0


async def test_scoring_penalizes_bad_output():
    async def bad_solver(_task: EvalTask) -> str:
        return "no tengo idea"

    report = await run_suite(solver=bad_solver)
    assert report.total_score < 0.2


async def test_report_json_serializable():
    report = await run_suite()
    import json

    parsed = json.loads(report.to_json())
    assert "total_score" in parsed
    assert len(parsed["tasks"]) == len(REFERENCE_TASKS)
