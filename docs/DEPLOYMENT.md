# AgentForge — Despliegue

Guía para levantar AgentForge con Docker Compose, configurar variables de entorno, aplicar migraciones, escalar workers, sembrar datos demo y correr los evals en CI.

---

## 1. Stack completo con Docker Compose

Todo el stack se levanta con un comando desde `infra/`:

```bash
cd infra
ANTHROPIC_API_KEY=sk-... docker compose up --build
```

Puertos publicados:
- API: `http://localhost:8000` (docs en `/docs`)
- Frontend (panel): `http://localhost:5173`
- MinIO: API `:9000`, consola web `:9001`
- PostgreSQL: `:5432` · Redis: `:6379`

### Servicios del compose (`infra/docker-compose.yml`)

| Servicio | Imagen / build | Rol |
|----------|----------------|-----|
| `postgres` | `pgvector/pgvector:pg16` | estado, traces, memoria RAG (pgvector). Ejecuta `init-db.sql` al inicializar. Healthcheck `pg_isready`. |
| `redis` | `redis:7-alpine` | cola de jobs + streams de eventos, con AOF (`--appendonly yes`). |
| `minio` | `minio/minio:latest` | almacenamiento S3 de artefactos/workspaces. |
| `api` | build `../backend` | FastAPI/uvicorn en `:8000`. **Es el único que aplica migraciones** (`RUN_MIGRATIONS=1`). |
| `worker` | build `../backend` | ejecuta los runs de la cola. **2 réplicas** por defecto (`deploy.replicas: 2`). Monta `/var/run/docker.sock` para el sandbox de `run_python`. |
| `scheduler` | build `../backend` | lanza los runs programados (cron). |
| `frontend` | build `../frontend` | SPA servida en `:5173` (contenedor escucha en `:80`). |

`api`, `worker` y `scheduler` comparten el mismo bloque de entorno (`x-backend-env`) y usan `entrypoint.sh`, que espera a Postgres, aplica migraciones solo si `RUN_MIGRATIONS=1`, y luego arranca el comando del servicio.

Los datos persisten en los volúmenes `pgdata`, `redisdata` y `miniodata`.

---

## 2. Variables de entorno

Las lee `app/config.py` (Pydantic Settings; también admite un `.env` en `backend/`). En el compose se definen en `x-backend-env` y se pasan por `${VAR}` desde el shell.

| Variable | Default | Descripción |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://agentforge:agentforge@localhost:5432/agentforge` | Postgres async (driver `asyncpg`). |
| `REDIS_URL` | `redis://localhost:6379/0` | cola + eventos. |
| `JWT_SECRET` | `dev-secret` | **cámbialo en producción**; firma los JWT (HS256). En compose: `JWT_SECRET`. |
| `JWT_EXPIRES_MINUTES` | `1440` | vigencia del token (24 h). |
| `ANTHROPIC_API_KEY` | `""` | API key de Anthropic. |
| `OPENAI_API_KEY` | `""` | API key de OpenAI (también usada por el embedder OpenAI). |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | endpoint de Ollama (en compose: `http://host.docker.internal:11434`). |
| `MCP_SERVERS` | `[]` | JSON con la lista de servidores MCP: `[{"name":"...","url":"https://...","headers":{...}}]`. |
| `S3_ENDPOINT` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_BUCKET` | MinIO local | almacenamiento de artefactos. |
| `APPROVAL_TIMEOUT_SECONDS` | `900` | timeout del gate human-in-the-loop; al vencer se rechaza la acción. |
| `APPROVAL_POLL_SECONDS` | `2.0` | intervalo de sondeo de la decisión de aprobación. |
| `RUN_MIGRATIONS` | `0` | si `1`, `entrypoint.sh` aplica `alembic upgrade head` antes de arrancar. Solo el servicio `api` lo pone a `1`. |

Como mínimo, para runs reales configura una API key de proveedor (`ANTHROPIC_API_KEY` y/o `OPENAI_API_KEY`), o apunta a un Ollama local. Sin API key, `POST /api/agents/{id}/ask` devuelve `503`.

Ejemplo con MCP:
```bash
export MCP_SERVERS='[{"name":"github","url":"https://mcp.ejemplo/github","headers":{"Authorization":"Bearer xxx"}}]'
docker compose up --build
```

---

## 3. Migraciones (Alembic)

El esquema se gestiona con Alembic (`backend/alembic/`).

- **En el stack**: el servicio `api` corre con `RUN_MIGRATIONS=1`, así que aplica `alembic upgrade head` automáticamente al arrancar (los demás servicios no migran, para evitar carreras).
- **En local**:
  ```bash
  cd backend
  alembic upgrade head        # aplicar
  alembic revision --autogenerate -m "descripcion"   # nueva migración
  ```

---

## 4. Escalado de workers

Los workers son *stateless* y consumen la cola con consumer group + `XAUTOCLAIM`, por lo que escalan horizontalmente sin coordinación adicional: **más workers = más runs en paralelo**.

```bash
# En caliente
docker compose up --scale worker=4

# O de forma fija en docker-compose.yml
services:
  worker:
    deploy:
      replicas: 4
```

Un run tomado por un worker que muere se re-entrega tras 60 s (`XAUTOCLAIM`, min-idle) a otro worker, que reanuda desde el último checkpoint (ver `docs/ARCHITECTURE.md` §3). El scheduler está pensado para correr como **una sola instancia** (los disparos son idempotentes por minuto, pero no necesita réplicas).

**Nota sobre `run_python`**: el sandbox lanza contenedores Docker efímeros, por lo que los workers necesitan acceso al socket de Docker (`/var/run/docker.sock`, ya montado en el compose).

---

## 5. Seed de datos demo

Con el stack arriba, siembra un usuario y agentes/equipo de ejemplo:

```bash
docker compose exec api python seed.py
```

Crea el usuario demo `demo@agentforge.dev` / `demo1234` con agentes especializados (orquestador + investigadores/redactor) y un equipo listo para lanzar runs. Es **idempotente**: si el usuario demo ya existe, no duplica nada.

En local (sin Docker): desde `backend/` con el venv activo y la BD migrada, `python seed.py`.

---

## 6. Desarrollo local (sin todo el stack)

```bash
# 1. Solo la infraestructura de datos
cd infra && docker compose up -d postgres redis minio

# 2. Backend
cd ../backend
cp .env.example .env          # completa tus API keys
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload # API en :8000

# 3. Worker y scheduler (terminales aparte, mismo venv)
python worker.py
python scheduler.py

# 4. Frontend
cd ../frontend && npm install && npm run dev   # :5173 con proxy /api
```

Procesos:

| Proceso | Comando | Rol |
|---------|---------|-----|
| API | `uvicorn app.main:app` | REST + SSE |
| Worker(s) | `python worker.py` | ejecuta runs de la cola (escalable) |
| Scheduler | `python scheduler.py` | dispara runs programados (cron) |
| Evals | `python run_evals.py` | scoring vs. línea base (CI) |

---

## 7. Tests y evals en CI

El backend se prueba sin dependencias externas (BD, LLM y Redis parcheados con fakes/fakeredis).

```bash
cd backend
python -m pytest tests -q     # suite de tests
python run_evals.py           # evals offline; exit 1 si el score cae bajo la línea base (0.85)
```

`run_evals.py` corre offline por defecto (sin gastar tokens); con `AGENTFORGE_EVAL_LIVE=1` corre contra LLMs reales.

La CI (`.github/workflows/ci.yml`) tiene dos jobs:
- **backend**: Python 3.12 → `pip install -e ".[dev]"` → `pytest tests -q` → `python run_evals.py`.
- **frontend**: Node 20 → `npm install` → `npm run build` (typecheck + build).

Se dispara en `push` a `main` / `claude/**` y en cada `pull_request`.

---

## 8. Checklist de producción

- Define `JWT_SECRET` fuerte (no el default `dev-secret`).
- Configura al menos una API key de proveedor LLM.
- Cambia las credenciales de MinIO y Postgres del compose de ejemplo.
- Ejecuta migraciones (`RUN_MIGRATIONS=1` en `api`, o `alembic upgrade head`).
- Ajusta `worker` replicas al volumen de runs esperado.
- Asegura el acceso de los workers al socket de Docker si usas `run_python`.
- Revisa los límites por organización (`max_runs_per_day`, `max_cost_usd_per_day`) si usas multi-tenancy.
