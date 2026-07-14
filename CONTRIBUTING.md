# Contribuir a AgentForge

Gracias por tu interés. Esta guía resume cómo trabajar en el proyecto.

## Requisitos

- Python 3.12 (el código es compatible con 3.11+)
- Node 20+
- Docker + Docker Compose (para el stack completo y el sandbox `run_python`)

## Puesta en marcha

```bash
# Infraestructura de datos
cd infra && docker compose up -d postgres redis minio

# Backend
cd ../backend
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload      # API en :8000
python worker.py                   # worker (en otra terminal)
python scheduler.py                # runs programados (opcional)

# Frontend
cd ../frontend
npm install && npm run dev         # :5173
```

## Antes de abrir un PR

```bash
# Backend
cd backend
python -m pytest tests -q          # toda la suite debe pasar
python run_evals.py                # sin regresiones vs. línea base
ruff check app                     # estilo

# Frontend
cd ../frontend
npm run build                      # typecheck + build
```

## Convenciones

- **Async en todo el backend** (SQLAlchemy async, httpx, redis.asyncio).
- **Tests sin dependencias externas**: se parchea la BD (`SessionLocal`), el LLM
  (`ToolCallingSession`) y Redis (`fakeredis`). Sigue ese patrón al añadir tests.
- **Modelo LLM por defecto**: `claude-opus-4-8`. Los modelos 4.7+ usan thinking
  adaptativo y rechazan `temperature` (ver `app/llm/toolcalling.py`).
- **Migraciones**: una revisión Alembic por cambio de esquema, encadenada a la
  anterior (`down_revision`). Verifica que la cadena sea lineal.
- **Idioma**: comentarios y mensajes de usuario en español.
- **Herramientas nuevas**: implementa el contrato `Tool` de `app/tools/base.py`
  (schema, nivel de riesgo, timeout). Las de riesgo `sensitive`/`dangerous`
  pasan por el gate de aprobación automáticamente.

## Estructura

Ver [`CLAUDE.md`](CLAUDE.md) para el mapa de módulos y [`docs/DESIGN.md`](docs/DESIGN.md)
para el documento de diseño completo.
