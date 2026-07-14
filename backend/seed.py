"""Datos de demostración: usuario, agentes y un equipo listos para probar.

    python seed.py

Idempotente: si el usuario demo ya existe, no duplica nada.
"""

import asyncio

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Agent, Team, TeamMember, User
from app.security import hash_password

DEMO_EMAIL = "demo@agentforge.dev"
DEMO_PASSWORD = "demo1234"


async def main() -> None:
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            user = User(email=DEMO_EMAIL, password_hash=hash_password(DEMO_PASSWORD))
            db.add(user)
            await db.commit()
            await db.refresh(user)
            print(f"Usuario demo creado: {DEMO_EMAIL} / {DEMO_PASSWORD}")
        else:
            print("El usuario demo ya existía; no se duplica nada.")
            return

        # Agentes especializados
        orchestrator = Agent(
            name="Coordinador", role="orchestrator", model_provider="anthropic",
            model_name="claude-opus-4-8",
            system_prompt="Coordinas un equipo de investigación. Planificas y sintetizas.",
            max_steps=40, max_cost_usd=2.0, created_by=user.id,
        )
        researcher_a = Agent(
            name="Researcher-1", role="research", model_provider="anthropic",
            model_name="claude-sonnet-5",
            system_prompt="Investigas fuentes web y extraes hechos con sus URLs.",
            max_steps=20, max_cost_usd=0.5, created_by=user.id,
        )
        researcher_b = Agent(
            name="Researcher-2", role="research", model_provider="anthropic",
            model_name="claude-sonnet-5",
            system_prompt="Investigas fuentes web y extraes hechos con sus URLs.",
            max_steps=20, max_cost_usd=0.5, created_by=user.id,
        )
        analyst = Agent(
            name="DataAnalyst", role="analysis", model_provider="anthropic",
            model_name="claude-opus-4-8",
            system_prompt="Analizas datos con Python en el sandbox y sacas conclusiones.",
            max_steps=25, max_cost_usd=1.0, created_by=user.id,
        )
        writer = Agent(
            name="Writer", role="writing", model_provider="anthropic",
            model_name="claude-sonnet-5",
            system_prompt="Redactas informes claros en Markdown con tablas comparativas.",
            max_steps=15, max_cost_usd=0.5, created_by=user.id,
        )
        for agent in (orchestrator, researcher_a, researcher_b, analyst, writer):
            db.add(agent)
        await db.commit()
        for agent in (orchestrator, researcher_a, researcher_b, analyst, writer):
            await db.refresh(agent)

        # Equipo de investigación profunda (CU-1)
        team = Team(
            name="Investigación profunda",
            description="Orquestador + 2 researchers + analista + writer",
            orchestrator_agent_id=orchestrator.id,
        )
        db.add(team)
        await db.flush()
        for agent, spec in [
            (researcher_a, "fuentes primarias"),
            (researcher_b, "competidores"),
            (analyst, "análisis cuantitativo"),
            (writer, "redacción"),
        ]:
            db.add(TeamMember(team_id=team.id, agent_id=agent.id, specialty=spec))
        await db.commit()

        print(f"Creados 5 agentes y el equipo '{team.name}'.")
        print("Entra al panel, lanza un run del equipo y observa el trace en vivo.")


if __name__ == "__main__":
    asyncio.run(main())
