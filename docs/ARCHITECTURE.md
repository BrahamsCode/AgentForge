# AgentForge — Arquitectura

Documento de arquitectura de AgentForge v1.0 + v2. Complementa el documento de diseño (`docs/DESIGN.md`) describiendo **lo que existe en el código** hoy: componentes, flujos de ejecución, resiliencia, seguridad, memoria y las capacidades v2.

---

## 1. Componentes

AgentForge es un sistema de procesos independientes que comparten Postgres y Redis. La API nunca ejecuta agentes: solo encola; los workers ejecutan.

```
┌──────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React 19 SPA)                         │
│        Agentes · Equipos · Runs · Trace en vivo · Aprobaciones         │
└───────────────┬──────────────────────────────────┬────────────────────┘
                │ REST (/api, JWT)                  │ SSE (/api/runs/:id/events?token=)
┌───────────────▼──────────────────────────────────▼────────────────────┐
│                          API (FastAPI · uvicorn)                       │
│  auth · agents · teams · runs(+approvals+messages) · memory · metrics  │
│  orgs   —   valida JWT, aplica X-Org-Id y límites, ENCOLA (no ejecuta) │
└───────┬───────────────────────────────────────────────┬───────────────┘
        │ XADD agentforge:runs                           │ lee eventos (XRANGE/XREAD)
┌───────▼────────────────────┐                  ┌────────▼───────────────┐
│   REDIS STREAMS            │                  │  Eventos por run        │
│   cola de jobs +           │◀───publish──────▶│  agentforge:events:{id} │
│   consumer group "workers" │                  └─────────────────────────┘
└───────┬────────────────────┘
        │ XREADGROUP / XAUTOCLAIM
┌───────▼────────────────────────────────────────────────────────────────┐
│                    WORKER(s)  ·  python worker.py  (N réplicas)          │
│   Motor de ejecución agéntica:                                          │
│     · loop.py         single-agent (razonar → herramienta → observar)   │
│     · orchestrator.py equipo  (plan → delegate → collect → synthesize)  │
│     · swarm.py        swarm    (N candidatos + juez)                    │
│   Checkpoints en runs.checkpoint  ·  presupuestos duros  ·  guardrails  │
└───┬──────────────────────────────┬─────────────────────────┬───────────┘
    │ proveedores LLM              │ capa de herramientas     │
┌───▼──────────────┐   ┌───────────▼──────────────┐   ┌───────▼───────────┐
│ Anthropic/OpenAI │   │ web_search · web_fetch   │   │  SCHEDULER         │
│ / Ollama         │   │ read/write_file · run_   │   │  python scheduler  │
│ (client.py +     │   │ python(Docker) · browser │   │  cron → runs hijo  │
│  toolcalling.py) │   │ search_memory · MCP · msg│   └───────────────────┘
└──────────────────┘   └──────────────────────────┘
┌────────────────────────────────────────────────────────────────────────┐
│  PERSISTENCIA:  PostgreSQL 16 + pgvector (estado, traces, memoria RAG)  │
│                 Redis (cola + eventos)   ·   MinIO/S3 (artefactos)      │
└────────────────────────────────────────────────────────────────────────┘
```

### API — FastAPI (`app.main:app`)
Expone la REST (`/api/...`) y el stream SSE. Valida el JWT (`app/security.py`), resuelve la organización activa por `X-Org-Id` y aplica los límites diarios (`app/tenancy/deps.py`). Al crear un run, hace `XADD` a la cola de Redis; **no ejecuta el agente**. Routers en `app/routers/`.

### Worker(s) — `worker.py` / `app/queue/worker.py`
Consumen la cola con `XREADGROUP` sobre el consumer group `workers`, ejecutan el motor agéntico y hacen `XACK` al terminar. `XAUTOCLAIM` recupera mensajes de workers muertos (min-idle 60 s). Escalan horizontalmente: más réplicas = más runs en paralelo (compose arranca 2). Son *stateless*: todo el estado vive en Postgres/Redis.

### Scheduler — `scheduler.py` / `app/scheduler/loop.py`
Cada 60 s revisa las plantillas (`Run` con `status="scheduled"` y `schedule_cron`) y, si el cron coincide con el minuto actual, crea un **run hijo** (`parent_run_id`) y lo encola. Idempotente por minuto (`checkpoint.last_fired_minute`). Parser de cron propio de 5 campos (`app/scheduler/cron.py`). Al terminar el hijo, el motor dispara el webhook si estaba configurado (`app/scheduler/webhooks.py`).

### Cola y bus de eventos — Redis Streams (`app/queue/`)
- **Cola de jobs**: stream `agentforge:runs`, consumer group `workers`.
- **Eventos por run**: stream `agentforge:events:{run_id}` (un campo `data` con el evento JSON), con `MAXLEN ~10 000` y TTL 24 h. El SSE lo lee desde el inicio (histórico) y luego en vivo.

### Persistencia
- **PostgreSQL 16 + pgvector**: definiciones (agentes/equipos), estado de runs y checkpoints, `trace_steps`, `approvals`, mensajes entre agentes, y memoria RAG (documentos + chunks con embeddings, índices HNSW). Acceso 100 % async (SQLAlchemy async).
- **Redis**: cola de jobs + streams de eventos.
- **MinIO (S3)**: artefactos/workspaces. Cada run tiene un workspace local (`/tmp/agentforge/workspaces/{run_id}`) donde las herramientas de archivos operan con sandbox de rutas.

### LLM (`app/llm/`)
Cliente unificado multi-proveedor (`client.py`) con tabla de precios (`pricing.py`) que registra tokens y costo por llamada. `toolcalling.py` implementa el tool calling nativo por proveedor y `compact()` (compresión de contexto). Modelo por defecto: `claude-opus-4-8` (los modelos 4.7+ usan thinking adaptativo y rechazan `temperature`).

---

## 2. Flujo de un run

Al crear un run, la API valida (exactamente uno de `agent_id`/`team_id`), lo persiste en `queued` y hace `XADD`. Un worker lo toma y, según su forma, entra en uno de tres motores. El punto de entrada `execute_run` (`app/engine/loop.py`) enruta:

- `checkpoint.mode == "swarm"` → **swarm**
- `team_id` presente y sin `agent_id` → **orquestador de equipo**
- resto → **single-agent**

Cada paso emite un evento `step` a Redis → SSE → el frontend actualiza el trace en vivo. El trace persistente vive en `trace_steps`.

### 2.1 Single-agent (`loop.py`)
Loop **razonar → herramienta → observar**:
1. `status="running"`; se manda el objetivo al LLM.
2. Si el LLM responde sin tool calls → respuesta final → `completed` (`checkpoint.final_answer`).
3. Si hay tool calls: por cada uno se evalúan los guardrails (§4), se ejecuta la herramienta con `asyncio.wait_for(timeout)` y se registra el paso.
4. Corte por presupuesto: si `run.total_cost_usd >= agent.max_cost_usd` → cierre limpio con respuesta parcial (`checkpoint.partial=true`). Corte por `max_steps` → `failed`.
5. En runs largos, cuando el historial supera 20 mensajes se llama a `session.compact()` (compresión de contexto).

### 2.2 Equipo / orquestador (`orchestrator.py`)
Grafo propio de fases con checkpoint fase a fase en `runs.checkpoint.orchestrator`:

- **plan**: el orquestador produce un plan JSON con un DAG de tareas (1–8), cada una asignada a un miembro con `depends_on`. Parseo robusto con degradación (si no hay JSON usable → una sola tarea). Se materializan en la tabla `tasks`.
- **delegate**: las tareas se ejecutan por **olas** respetando dependencias; hasta 4 en paralelo (`_MAX_PARALLEL_TASKS`). Cada sub-agente corre su propio sub-loop agéntico. Corte por presupuesto de equipo (`orchestrator.max_cost_usd`). Un fallo de tarea no aborta el run: se marca fallida y se registra su error.
- **synthesize**: el orquestador integra los resultados de las tareas en el entregable final → `completed`.

Las escrituras concurrentes de las sub-tareas se serializan con un lock (`_Recorder`). Los sub-agentes reciben identidad + roster para poder comunicarse entre sí (§7.5).

### 2.3 Swarm (`swarm.py`, v2)
N candidatos (por defecto 3) resuelven el **mismo** objetivo en paralelo, cada uno en su subdirectorio de workspace (`candidate_{i}`), reutilizando el mismo sub-loop agéntico. Un candidato que falla no aborta el swarm. Luego un **juez** (LLM sin herramientas) elige el ganador; parseo robusto del veredicto (primer entero 1..N; si no, el candidato válido más largo). El ganador queda en `checkpoint.final_answer` y el detalle en `checkpoint.swarm`.

---

## 3. Checkpointing y resiliencia (O4)

**Objetivo O4 — un run sobrevive al reinicio del worker y reanuda desde el último checkpoint.**

- Cada transición relevante persiste estado en `runs.checkpoint` (JSON): en single-agent, los mensajes de la sesión y el `step`; en equipo, la fase actual (`plan`/`delegate`/`synthesize`) y el plan; en swarm, el resultado.
- Los workers son *stateless* y usan **consumer group + XACK**: un run solo se confirma cuando termina. Si el worker muere a mitad, el mensaje queda pendiente y **`XAUTOCLAIM`** (min-idle 60 s) lo re-entrega a otro worker.
- Al re-ejecutar, el orquestador **reanuda desde la última fase** persistida, saltándose las tareas ya `completed` (se releen de la tabla `tasks`). El single-agent reejecuta el run desde su checkpoint de mensajes.
- Si `execute_run` lanza una excepción no controlada, el worker marca el run `failed` con causa (`mark_run_failed`) y siempre hace `XACK` (no reintenta en bucle infinito).

Trazabilidad total (**O3**): cada llamada LLM y tool call genera un `TraceStep` con `input/output`, `tokens_in/out`, `cost_usd`, `latency_ms` y `kind` (`llm_call | tool_call | error`), reconstruible vía `GET /api/runs/{id}/trace`.

---

## 4. Capa de herramientas, riesgo y human-in-the-loop (O5)

**Objetivo O5 — ninguna herramienta ejecuta acciones destructivas sin política de aprobación.**

Cada herramienta (`app/tools/base.py:Tool`) declara: `name`, `description`, `input_schema` (JSON Schema), `risk_level` y `timeout_seconds`. El motor aplica el timeout con `asyncio.wait_for`; los errores recuperables se devuelven al LLM como `ToolError`.

### Niveles de riesgo y política (`app/engine/guardrails.py`)
- `safe` → siempre se ejecuta.
- `sensitive` → se ejecuta, **salvo** que los argumentos disparen un patrón sospechoso (heurística: `rm -rf`, `sudo`, `DROP TABLE`, `/etc/passwd`, `curl ... | sh`, etc.), en cuyo caso escala a aprobación.
- `dangerous` → **siempre** requiere aprobación humana.

### Herramientas incluidas (`get_default_tools`)
| Herramienta | Riesgo | Timeout | Notas |
|-------------|--------|---------|-------|
| `web_search` | safe | 30 s | búsqueda web |
| `web_fetch` | safe | 30 s | fetch de URL; marca contenido externo como no confiable |
| `read_file` | safe | 10 s | lectura dentro del workspace |
| `write_file` | sensitive | 10 s | escritura dentro del workspace |
| `run_python` | sensitive | 150 s | sandbox Docker efímero, sin red, límites CPU/RAM/pids, rootfs de solo lectura |
| `search_memory` | safe | — | RAG sobre pgvector |
| `browser` | sensitive | 60 s | Chromium headless (Playwright), v2 |
| `send_message` / `check_messages` | safe | 15 s | comunicación directa entre agentes, v2 |
| `mcp__<server>__<tool>` | sensitive | 60 s | herramientas de servidores MCP, v2 |

### Flujo de aprobación (`loop.py:_await_approval`)
Cuando un tool call requiere aprobación (`ask`): se crea una `Approval` pendiente, el run pasa a **`awaiting_approval`** y se emite `approval_required`. El motor sondea la decisión humana (`POST /api/runs/{id}/approve`). Al aprobar → se ejecuta; al rechazar → el LLM recibe "acción rechazada" y sigue. Hay **timeout** configurable (`approval_timeout_seconds`, default 900 s): al vencer, se rechaza automáticamente (`decision=timeout`) y el run continúa. Si el run se cancela mientras espera, se corta.

### Defensa contra prompt injection
El contenido externo (web/fetch/browser) se envuelve entre marcadores `<<CONTENIDO EXTERNO NO CONFIABLE>> … <<FIN CONTENIDO EXTERNO>>` y el system prompt instruye explícitamente no obedecer instrucciones dentro de esos bloques. `guardrails.scan_prompt_injection` detecta patrones de inyección como telemetría/defensa en profundidad.

---

## 5. Memoria (RAG)

`app/memory/`: los documentos subidos (`POST /api/memory/documents`, texto o archivo) se trocean con solape (`chunking.py`), se embeben (`embeddings.py`; embedders OpenAI/Ollama/hash) y se guardan en `memory_chunks` con `vector` + índice HNSW. La búsqueda (`service.search_memory`) hace similitud vectorial y alimenta tanto `GET /api/memory/search` como la herramienta `search_memory` que usan los agentes durante un run.

---

## 6. Presupuestos y observabilidad

- **Presupuestos duros** por agente: `max_steps` y `max_cost_usd`. El motor corta limpio al alcanzarlos (parcial en single-agent/swarm; marca de tareas restantes como fallidas en equipo). Evita bucles que quemen dinero.
- **Métricas** (`GET /api/metrics/costs`): tasa de éxito, costo/tokens por agente (atribuido vía `trace_steps`), herramientas más usadas, pasos promedio, en una ventana de días.
- **Evals** (`app/evals/`, `run_evals.py`): suite de tareas de referencia con scoring, comparada contra una línea base offline (0.85) en CI.

---

## 7. Capacidades v2

### 7.1 MCP — Model Context Protocol (`app/tools/mcp.py`)
Cliente MCP (JSON-RPC sobre Streamable HTTP). Los servidores se declaran en `MCP_SERVERS` (JSON: `[{name, url, headers?}]`). `get_runtime_tools()` carga sus herramientas y las registra con nombre `mcp__<server>__<tool>` y `risk_level="sensitive"` (externas → gate de aprobación). Un servidor caído no tumba el run (se ignora con warning).

### 7.2 Agente navegador (`app/tools/browser.py`)
Herramienta `browser` con acciones `goto | click | type | extract_text | screenshot` sobre Chromium headless (Playwright), con página persistente por run. El texto extraído se marca como no confiable. `sensitive` (requiere aprobación por defecto). Import perezoso: si falta Playwright, devuelve `ToolError`.

### 7.3 Multi-tenancy (`app/tenancy/`)
Organizaciones (`plan`, `max_runs_per_day`, `max_cost_usd_per_day`) y membresías con roles (`owner | admin | member`). API en `/api/orgs`.

### 7.4 Scoping y límites por organización (`app/tenancy/deps.py`)
La org activa se resuelve del header `X-Org-Id`: ausente → contexto personal (`org_id=NULL`, compatibilidad hacia atrás); presente → se valida la membresía (`403` si no) y se aíslan agentes y runs por `org_id`. Al crear un run, `enforce_daily_limits` cuenta los runs y el costo de las últimas 24 h de la org y devuelve **`429`** si superan el plan.

### 7.5 Comunicación directa entre agentes (`app/tools/messaging.py`)
En runs de equipo, el orquestador inyecta en el `ToolContext` de cada sub-tarea la identidad del agente (`agent_id`/`agent_name`) y el `roster` de sus pares. Con `send_message` un sub-agente escribe a un par por nombre (o difunde con `all`) sin pasar por el orquestador; con `check_messages` revisa su bandeja. Los mensajes se persisten y son visibles en `GET /api/runs/{id}/messages`.

### 7.6 Swarm
Ver §2.3.

### Backlog v2 — completo
Todos los items del backlog v2 están implementados: agente navegador (Playwright), soporte MCP, multi-tenancy con scoping por organización y límites, modo swarm, comunicación directa entre agentes y **marketplace de plantillas** (`app/marketplace/` + endpoints `/api/templates`).

---

## 8. Mapa de objetivos O1–O5

| Objetivo | Cómo se cumple |
|----------|----------------|
| **O1** — tareas multi-paso autónomas | Loop agéntico (`loop.py`) razonar→herramienta→observar con `max_steps` (hasta 500) y corte limpio por presupuesto. |
| **O2** — coordinación multi-agente | Orquestador (`orchestrator.py`): plan DAG → delegación en olas con hasta 4 sub-agentes en paralelo → síntesis. |
| **O3** — observabilidad total | `trace_steps` registra cada llamada LLM/tool (input/output, tokens, costo, latencia); expuesto vía `/trace` y streaming SSE en vivo. |
| **O4** — resiliencia | Checkpoints en `runs.checkpoint`, workers stateless, consumer group + `XACK` + `XAUTOCLAIM`, reanudación fase a fase. |
| **O5** — seguridad | Niveles de riesgo por herramienta + guardrails, gate `awaiting_approval` con timeout, sandbox Docker de `run_python`, marcado de contenido externo no confiable. |
