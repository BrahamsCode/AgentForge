from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import agents, auth, memory, metrics, runs, teams

app = FastAPI(
    title="AgentForge API",
    version="0.1.0",
    description="Plataforma de orquestación multi-agente — Fase 0 (fundaciones)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # frontend Vite (Fase 1)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(agents.router)
app.include_router(teams.router)
app.include_router(runs.router)
app.include_router(memory.router)
app.include_router(metrics.router)


@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok"}
