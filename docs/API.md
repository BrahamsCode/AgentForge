# AgentForge — Referencia de la API REST

API HTTP de AgentForge (v1.0 + v2). Todas las rutas cuelgan de `/api` salvo `GET /health`.
La documentación interactiva (OpenAPI/Swagger) está en `http://localhost:8000/docs`.

- Base URL por defecto: `http://localhost:8000`
- Formato: JSON (excepto la subida de documentos, que también acepta `multipart/form-data`, y el stream SSE de eventos).
- Los IDs son UUID.

---

## Autenticación

### JWT Bearer

Casi todos los endpoints requieren un token JWT en la cabecera:

```
Authorization: Bearer <access_token>
```

El token se obtiene en `POST /api/auth/login` (`access_token`, tipo `bearer`). Caduca según `jwt_expires_minutes` (por defecto 1440 min = 24 h). El algoritmo es `HS256` firmado con `JWT_SECRET`.

Sin token o con token inválido → `401 Unauthorized`.

### Scoping por organización — `X-Org-Id`

Para operar dentro de una organización (multi-tenancy, v2) se envía la cabecera opcional:

```
X-Org-Id: <org_uuid>
```

- **Ausente** → contexto personal: agentes y runs con `org_id = NULL` (compatibilidad hacia atrás).
- **Presente** → se valida la membresía (`403` si no perteneces) y se aplican los límites diarios de la organización. Al crear un run, si la org supera `max_runs_per_day` o `max_cost_usd_per_day` se devuelve `429 Too Many Requests`.
- `X-Org-Id` con un valor que no es UUID → `400 Bad Request`.

Aplica al listar/crear agentes (`/api/agents`) y al listar/crear runs (`/api/runs`).

### SSE vía query param — `?token=`

El endpoint de eventos en vivo (`GET /api/runs/{id}/events`) admite el JWT como **cabecera Bearer o** como query param `?token=<jwt>`, porque `EventSource` del navegador no puede enviar cabeceras personalizadas.

---

## Auth

### `POST /api/auth/register`
Registra un usuario. → `201`. `409` si el email ya existe.

Body: `{ "email": "...", "password": "..." }` (password: 8–128 caracteres).

```bash
curl -X POST localhost:8000/api/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"demo@agentforge.dev","password":"demo1234"}'
```

### `POST /api/auth/login`
Devuelve un JWT. `401` si las credenciales no son válidas.

Respuesta: `{ "access_token": "...", "token_type": "bearer" }`

```bash
curl -s -X POST localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"demo@agentforge.dev","password":"demo1234"}'
```

### `GET /api/auth/me`
Devuelve el usuario autenticado (`id`, `email`, `role`, `created_at`).

```bash
curl localhost:8000/api/auth/me -H "Authorization: Bearer $TOKEN"
```

---

## Agents

Un agente define nombre, rol, proveedor/modelo LLM, system prompt y presupuestos (`max_steps`, `max_cost_usd`, `temperature`).

### `POST /api/agents`
Crea un agente. → `201`. Respeta `X-Org-Id` (lo asocia a la org o al contexto personal).

Body clave:
```json
{
  "name": "Researcher",
  "role": "researcher",
  "model_provider": "anthropic",      // anthropic | openai | ollama
  "model_name": "claude-opus-4-8",
  "system_prompt": "Eres un investigador riguroso.",
  "max_steps": 30,                      // 1–500, default 30
  "max_cost_usd": 1.0,                  // > 0, default 1.0
  "temperature": null                   // 0–2 o null (los modelos 4.7+ la rechazan)
}
```

```bash
curl -X POST localhost:8000/api/agents -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Researcher","role":"researcher","system_prompt":"Investigas."}'
```

### `GET /api/agents`
Lista los agentes del contexto activo (org o personal), más recientes primero.

### `GET /api/agents/{agent_id}`
Devuelve un agente. `404` si no existe.

### `PATCH /api/agents/{agent_id}`
Actualiza campos parciales (mismos campos que `POST`, todos opcionales).

### `DELETE /api/agents/{agent_id}`
Elimina un agente. → `204`.

### `POST /api/agents/{agent_id}/ask`
Pregunta directa a un agente **sin herramientas ni run** (entregable de Fase 0; útil para probar la conexión con el proveedor). `503` si falta la API key del proveedor.

Body: `{ "question": "..." }`. Respuesta: `{ answer, model_provider, model_name, tokens_in, tokens_out, cost_usd, latency_ms }`.

```bash
curl -X POST localhost:8000/api/agents/$AGENT/ask -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"question":"¿Qué es un agente de IA?"}'
```

---

## Teams

Un equipo tiene un agente orquestador y una lista de miembros (agente + especialidad).

### `POST /api/teams`
Crea un equipo. → `201`. `404` si algún agente referenciado no existe.

Body:
```json
{
  "name": "Investigación de mercado",
  "description": "",
  "orchestrator_agent_id": "<uuid>",
  "members": [
    { "agent_id": "<uuid>", "specialty": "búsqueda web" },
    { "agent_id": "<uuid>", "specialty": "redacción" }
  ]
}
```
`members`: entre 1 y 20 miembros.

### `GET /api/teams`
Lista los equipos (con sus miembros: `agent_id`, `agent_name`, `specialty`).

### `GET /api/teams/{team_id}`
Devuelve un equipo con sus miembros. `404` si no existe.

### `DELETE /api/teams/{team_id}`
Elimina el equipo y sus membresías. → `204`.

---

## Runs

Un run es la ejecución de un objetivo (`goal`) por un agente único **o** un equipo. Se encola en Redis Streams y lo procesa un worker.

### `POST /api/runs`
Crea y encola un run. → `201`. Respeta `X-Org-Id` (aplica límites diarios → `429`).

Body:
```json
{
  "agent_id": "<uuid>",        // exactamente uno: agent_id O team_id
  "team_id": null,
  "goal": "Investiga el mercado X y genera un informe",
  "schedule_cron": null,        // si se envía → crea plantilla programada (no encola)
  "webhook_url": null,          // POST al terminar (CU-3)
  "mode": null                  // "swarm" → N clones compiten + juez (requiere agent_id)
}
```

Reglas y errores:
- Debes enviar **exactamente uno** de `agent_id` / `team_id` → si no, `422`.
- `mode` solo admite `"swarm"` y requiere `agent_id` → si no, `422`.
- Con `schedule_cron`: se valida el cron (5 campos) y se crea un Run con `status="scheduled"` (plantilla); el scheduler lanza runs hijo. Cron inválido → `422`.

```bash
# Run de agente único
curl -X POST localhost:8000/api/runs -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"'$AGENT'","goal":"Resume las novedades de IA de esta semana"}'

# Run de equipo
curl -X POST localhost:8000/api/runs -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"team_id":"'$TEAM'","goal":"Informe comparativo de 5 competidores"}'

# Run programado (cron: cada día a las 8:00)
curl -X POST localhost:8000/api/runs -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"'$AGENT'","goal":"Revisa estas fuentes","schedule_cron":"0 8 * * *","webhook_url":"https://ejemplo/hook"}'
```

Respuesta (`RunOut`): `id, agent_id, team_id, goal, status, error, total_cost_usd, total_tokens, created_at, started_at, finished_at, final_answer`.
`final_answer` se rellena desde `checkpoint.final_answer` cuando el run termina.

Estados posibles: `queued | running | awaiting_approval | completed | failed | cancelled | scheduled`.

### `GET /api/runs`
Lista los runs del contexto activo (paginado). Query: `offset` (≥0), `limit` (1–100, default 50).

### `GET /api/runs/{run_id}`
Devuelve un run (`RunOut`). `404` si no existe.

### `GET /api/runs/{run_id}/trace`
Trace completo paginado, ordenado por `step_number`. Query: `offset` (≥0), `limit` (1–200, default 100).

Cada paso (`TraceStepOut`): `id, step_number, kind, input, output, tokens_in, tokens_out, cost_usd, latency_ms, created_at`.
`kind` ∈ `llm_call | tool_call | error` (los `input.tool` de los `tool_call` alimentan las métricas de herramientas).

```bash
curl "localhost:8000/api/runs/$RUN/trace?limit=200" -H "Authorization: Bearer $TOKEN"
```

### `POST /api/runs/{run_id}/cancel`
Cancelación cooperativa: pone el run en `cancelled` y emite un evento `run_cancelled`. `409` si el run ya está en estado terminal.

### `GET /api/runs/{run_id}/messages`
Mensajes de comunicación directa entre agentes durante el run (v2), en orden cronológico. Cada mensaje: `id, from_agent_name, to_agent, content, read, created_at` (`to_agent` puede ser un nombre o `"all"`).

### `GET /api/runs/{run_id}/approvals`
Lista las aprobaciones del run. Query: `only_pending` (bool, default false).
Cada aprobación (`ApprovalOut`): `id, run_id, action_summary, status, created_at, decided_at`. `status` ∈ `pending | approved | rejected`.

### `POST /api/runs/{run_id}/approve`
Decide una aprobación pendiente (human-in-the-loop). `404` si no existe; `409` si ya fue decidida; `422` si `decision` no es válido.

Body: `{ "approval_id": "<uuid>", "decision": "approved" }` (`decision` ∈ `approved | rejected`).

```bash
curl -X POST localhost:8000/api/runs/$RUN/approve -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"approval_id":"'$APPROVAL'","decision":"approved"}'
```

### `GET /api/runs/{run_id}/events` — SSE

Stream Server-Sent Events (`text/event-stream`) con el histórico + los eventos en vivo del run. Autenticación por Bearer **o** `?token=<jwt>`.

- Emite primero todo el histórico del stream Redis del run, luego sigue en vivo.
- Cierra al ver un evento terminal (`run_finished` o `run_cancelled`).
- Mientras no hay eventos envía keepalives (`: ping`) cada ~15 s.

```bash
curl -N "localhost:8000/api/runs/$RUN/events?token=$TOKEN"
```

```js
const es = new EventSource(`/api/runs/${runId}/events?token=${token}`);
es.onmessage = (e) => console.log(JSON.parse(e.data));
```

#### Formato de los eventos SSE

Cada frame es `data: <json>\n\n` (con un `id:` = id de entrada del stream Redis). Tipos emitidos por el backend (`app/engine/loop.py`, `orchestrator.py`, `swarm.py`, `sse.py`):

**`step`** — un paso de ejecución (llamada al LLM o herramienta):
```json
{ "type": "step", "run_id": "...", "agent": "Researcher",
  "kind": "llm_call", "step": 14, "summary": "(razonando)", "cost_usd": 0.0031 }
```
```json
{ "type": "step", "run_id": "...", "agent": "Researcher",
  "kind": "tool_call", "tool": "web_search", "step": 15,
  "summary": "web_search(query='mercado SaaS 2026')", "error": false }
```
En runs swarm los `step` incluyen además `"candidate": <n>`.

**`approval_required`** — el run se pausó esperando aprobación humana:
```json
{ "type": "approval_required", "run_id": "...", "approval_id": "...",
  "step": 12, "tool": "run_python", "summary": "run_python(...) — herramienta de riesgo 'sensitive'" }
```

**`approval_decided`** — se resolvió una aprobación (`decision` ∈ `approved | rejected | timeout`):
```json
{ "type": "approval_decided", "approval_id": "...", "decision": "approved" }
```

**`run_finished`** — evento terminal; el stream se cierra tras emitirlo:
```json
{ "type": "run_finished", "run_id": "...", "status": "completed", "error": null }
```
`status` ∈ `completed | failed`.

**`run_cancelled`** — evento terminal emitido al cancelar el run:
```json
{ "type": "run_cancelled", "run_id": "..." }
```

---

## Memory (RAG)

### `POST /api/memory/documents`
Ingiere un documento para RAG (chunking + embeddings + pgvector). → `201`.
Acepta JSON `{ "name": "...", "text": "..." }` **o** un archivo (`multipart/form-data`, campo `file`). `422` si va vacío.

Respuesta: `{ "id": "...", "name": "...", "chunks": <n> }`.

```bash
# Texto plano
curl -X POST localhost:8000/api/memory/documents -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"notas","text":"Contenido a indexar..."}'

# Archivo
curl -X POST localhost:8000/api/memory/documents -H "Authorization: Bearer $TOKEN" \
  -F 'file=@informe.txt'
```

### `GET /api/memory/documents`
Lista los documentos ingeridos (`id, name, source, created_at`), más recientes primero.

### `GET /api/memory/search`
Búsqueda semántica sobre la memoria. Query: `q` (obligatorio), `limit` (1–20, default 5). Devuelve los chunks más relevantes. (Los agentes usan internamente la herramienta `search_memory` sobre este mismo servicio.)

```bash
curl "localhost:8000/api/memory/search?q=anomalias+de+ventas&limit=5" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Metrics

### `GET /api/metrics/costs`
Resumen de métricas agregadas. Query: `since_days` (1–365, default 30).

Respuesta (`MetricsSummary`):
```json
{
  "runs_total": 42, "runs_completed": 38, "runs_failed": 3,
  "success_rate": 0.905, "total_cost_usd": 12.34, "total_tokens": 1500000,
  "avg_steps_per_run": 11.4,
  "cost_by_agent": [ { "agent_id": "...", "agent_name": "Researcher", "cost_usd": 4.2, "tokens": 500000, "steps": 120 } ],
  "top_tools":     [ { "tool": "web_search", "count": 87 } ]
}
```

```bash
curl "localhost:8000/api/metrics/costs?since_days=7" -H "Authorization: Bearer $TOKEN"
```

---

## Orgs (multi-tenancy, v2)

Organizaciones con membresías (roles `owner | admin | member`) y límites de uso por plan.

### `POST /api/orgs`
Crea una organización (el usuario queda como `owner`). → `201`.
Body: `{ "name": "..." }`. Respuesta (`OrgOut`): `id, name, plan, max_runs_per_day, max_cost_usd_per_day, created_at` (defaults del plan free: 100 runs/día, $10/día).

### `GET /api/orgs`
Lista las organizaciones de las que el usuario es miembro.

### `GET /api/orgs/{org_id}`
Devuelve una organización. `404` si el usuario no es miembro.

### `POST /api/orgs/{org_id}/members`
Añade un miembro. Requiere rol `owner`/`admin` (`403` si no). → `201`.
Body: `{ "user_id": "<uuid>", "role": "member" }` (`role` ∈ `owner | admin | member`).

### `DELETE /api/orgs/{org_id}/members/{user_id}`
Elimina un miembro. Requiere rol `owner`/`admin` (`403` si no). → `204`.

```bash
curl -X POST localhost:8000/api/orgs -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"Mi Empresa"}'
# usa el id devuelto como X-Org-Id en el resto de llamadas:
curl localhost:8000/api/agents -H "Authorization: Bearer $TOKEN" -H "X-Org-Id: $ORG"
```

---

## Salud

### `GET /health`
Sin autenticación. Devuelve el estado del servicio.

---

## Templates (marketplace de plantillas de equipos)

Plantillas reutilizables que crean un equipo completo (orquestador + miembros) de un clic.

### `GET /api/templates`
Lista las plantillas disponibles (siembra las *builtin* de forma idempotente en la primera llamada + las creadas por el usuario). Cada `TeamTemplate` incluye `id`, `name`, `description`, `category`, `spec` (`{orchestrator, members[]}`), `is_builtin`, `created_at`.

### `GET /api/templates/{id}`
Detalle de una plantilla. `404` si no existe.

### `POST /api/templates/{id}/instantiate`
Instancia la plantilla: crea los agentes (orquestador + miembros) y un equipo reales, y devuelve `{team_id, agent_ids}`. `201`.

### `POST /api/templates/from-team`
Guarda un equipo existente como plantilla propia. Cuerpo: `{team_id, name, description, category}`.

### `DELETE /api/templates/{id}`
Borra una plantilla. `403` si es *builtin* o de otro usuario; `404` si no existe.

**Plantillas builtin:** «Investigación profunda» (orquestador + 2 researchers + analyst + writer), «Análisis de datos» (DataAnalyst con `run_python`) y «Monitoreo» (evaluador de relevancia).
