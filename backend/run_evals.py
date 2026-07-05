"""Corre la suite de evals y compara con la línea base (para CI).

    python run_evals.py                 # offline (CI, sin tokens)
    AGENTFORGE_EVAL_LIVE=1 python run_evals.py   # contra LLMs reales

Sale con código 1 si el score cae por debajo de la línea base (regresión).
"""

import asyncio
import sys

from app.evals.runner import run_suite

BASELINE = 0.85  # línea base offline; ajústala al subir de versión


async def main() -> int:
    report = await run_suite()
    print(report.to_json())
    print(f"\nScore total: {report.total_score:.3f} (línea base {BASELINE})")
    if report.total_score < BASELINE:
        print("❌ REGRESIÓN: el score cayó por debajo de la línea base")
        return 1
    print("✅ Sin regresiones")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
