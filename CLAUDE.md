# AgentForge — Guía para agentes de código

Plataforma self-hosted de orquestación multi-agente. Documento de diseño completo en `docs/DESIGN.md`.

## Estructura

```
backend/    FastAPI + motor de ejecución agéntica (Python 3.12, paquete `app`)
frontend/   SPA React 19 + Vite + TypeScript
infra/      docker-compose del stack completo
docs/       diseño
```

## Comandos

```bash
# Backend (desde backend/)
pip install -e ".[dev]"
python -m pytest tests -q          # 59 tests, sin red ni BD reales (fakes + fakeredis)
python run_evals.py                # suite de evals offline vs. línea base
uvicorn app.main:app --reload      # API
python worker.py                   # worker de la cola
python scheduler.py                # runs programados (cron)
alembic upgrade head               # migraciones

# Frontend (desde frontend/)
npm install && npm run build       # typecheck + build
npm run dev                        # dev server con proxy /api

# Stack completo
cd infra && docker compose up --build
```

## Arquitectura (mapa de módulos)

- `app/llm/client.py` — cliente LLM simple multi-proveedor (Anthropic/OpenAI/Ollama) con costos.
- `app/llm/toolcalling.py` — tool calling nativo por proveedor + `compact()` (compresión de contexto).
- `app/llm/pricing.py` — tabla de precios por modelo.
- `app/tools/` — capa de herramientas: `Tool` (schema/riesgo/timeout), registry, web_search, web_fetch, files, run_python, browser (Playwright), mcp (cliente MCP). `get_runtime_tools()` = por defecto + tools de servidores MCP configurados.
- `app/engine/swarm.py` — modo swarm (v2): N clones del agente compiten y un juez elige (run con `checkpoint.mode == "swarm"`).
- `app/tenancy/` — organizaciones y membresías (v2); router `app/routers/orgs.py`.
- `app/engine/loop.py` — motor single-agent (razonar → herramienta → observar) con checkpoints, presupuestos y gate de aprobación.
- `app/engine/orchestrator.py` — orquestador multi-agente (grafo plan→delegate→collect→synthesize).
- `app/engine/guardrails.py` — política de aprobación por riesgo + detección de prompt injection.
- `app/queue/` — Redis Streams: `bus.py` (enqueue/eventos), `worker.py` (consumer group + XAUTOCLAIM).
- `app/routers/` — auth, agents, teams, runs (+ SSE + aprobaciones), memory, metrics.
- `app/memory/` — RAG con pgvector (chunking, embeddings, service, herramienta search_memory).
- `app/scheduler/` — cron parser propio + loop que lanza runs programados; webhooks.
- `app/evals/` — suite de tareas de referencia con scoring.

## Convenciones

- **Modelo LLM por defecto: `claude-opus-4-8`.** Los modelos 4.7+ usan thinking adaptativo y rechazan `temperature` (ver `toolcalling.py`).
- Async en todo el backend (SQLAlchemy async, httpx, redis.asyncio).
- Tests sin dependencias externas: se parchea BD (`SessionLocal`), LLM (`ToolCallingSession`) y Redis (`fakeredis`). Sigue ese patrón al añadir tests.
- Estados de run: `queued | running | awaiting_approval | completed | failed | cancelled | scheduled`.
- Comentarios y mensajes de usuario en español (es el idioma del proyecto).

## Estado

v1.0 completa (fases 0–5, objetivos O1–O5, 3 casos de uso). Backlog v2 iniciado: agente navegador (Playwright), soporte MCP, multi-tenancy (orgs/membresías) y modo swarm — ya integrados. Pendiente de v2: scoping de agents/runs por organización, comunicación directa entre agentes, marketplace de plantillas.
