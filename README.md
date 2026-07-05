# AgentForge

Plataforma self-hosted de orquestación multi-agente: define agentes de IA especializados, conéctalos en equipos coordinados por un orquestador, dales herramientas reales y memoria persistente, y observa cada paso de su ejecución en tiempo real.

📄 **Documento de diseño completo:** [docs/DESIGN.md](docs/DESIGN.md)

## Estructura del monorepo

```
/backend     API FastAPI + motor de ejecución agéntica (Python 3.12)
/frontend    Panel de control (React 19 + Vite + TypeScript) — a partir de Fase 1
/infra       Docker Compose: PostgreSQL+pgvector, Redis, MinIO
/docs        Diseño y documentación
```

## Quick start (Fase 0)

```bash
# 1. Levantar la infraestructura
cd infra
docker compose up -d

# 2. Configurar el backend
cd ../backend
cp .env.example .env          # completa tus API keys
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. Migraciones y arranque
alembic upgrade head
uvicorn app.main:app --reload

# 4. Probar
open http://localhost:8000/docs
```

### Entregable de la Fase 0

Registrarse, crear un agente y hacerle una pregunta simple (sin herramientas):

```bash
# Registro + login
curl -X POST localhost:8000/api/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"demo@agentforge.dev","password":"demo1234"}'
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"demo@agentforge.dev","password":"demo1234"}' | jq -r .access_token)

# Crear un agente
AGENT=$(curl -s -X POST localhost:8000/api/agents -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Researcher","role":"researcher","model_provider":"anthropic",
       "model_name":"claude-opus-4-8","system_prompt":"Eres un investigador riguroso."}' | jq -r .id)

# Preguntarle algo (sin herramientas todavía)
curl -X POST localhost:8000/api/agents/$AGENT/ask -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"question":"¿Qué es un agente de IA?"}'
```

## Estado del roadmap

- [x] **Fase 0 — Fundaciones**: monorepo, Docker Compose, FastAPI + JWT, Alembic, CRUD de agentes, cliente LLM multi-proveedor con costos
- [ ] Fase 1 — Agente único con herramientas (worker + Redis Streams + trace + SSE)
- [ ] Fase 2 — Sandbox de código y memoria (RAG con pgvector)
- [ ] Fase 3 — Orquestación multi-agente (LangGraph + checkpointing)
- [ ] Fase 4 — Human-in-the-loop y seguridad
- [ ] Fase 5 — Programación, métricas y pulido

Ver el detalle de cada fase en [docs/DESIGN.md](docs/DESIGN.md#8-roadmap-por-fases).

## Proveedores LLM soportados

| Proveedor | Modelos | Notas |
|-----------|---------|-------|
| Anthropic | `claude-opus-4-8` (default), `claude-sonnet-5`, `claude-haiku-4-5` | SDK oficial, thinking adaptativo |
| OpenAI | configurable | SDK oficial |
| Ollama | cualquier modelo local | ideal para iterar barato en desarrollo |

Cada agente elige su proveedor y modelo; el cliente unificado registra tokens y costo por llamada.
