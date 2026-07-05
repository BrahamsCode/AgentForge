# AgentForge — Plataforma de Orquestación Multi-Agente

**Documento de diseño y plan de construcción — v1.0**
Fecha: Julio 2026 · Estado: Borrador para iniciar desarrollo

---

## 1. Visión del proyecto

### 1.1 ¿Qué es?

**AgentForge** es una plataforma self-hosted donde un usuario puede definir agentes de IA especializados, conectarlos en equipos coordinados por un orquestador, darles herramientas reales (APIs, bases de datos, navegador, código), memoria persistente, y observar cada paso de su razonamiento y ejecución desde un panel de control en tiempo real.

Piensa en ella como el **"sistema operativo" de un equipo de trabajo autónomo**: en lugar de un chatbot que responde una pregunta, defines un objetivo ("investiga a estos 20 competidores y genera un informe comparativo") y un equipo de agentes lo planifica, se reparte el trabajo, ejecuta durante minutos u horas, se recupera de errores y entrega el resultado.

### 1.2 ¿Por qué este proyecto?

- Es la **tendencia técnica dominante de 2026**: la industria pasó de asistentes de un solo turno a agentes que ejecutan flujos de larga duración con múltiples sub-agentes especializados coordinados por un orquestador.
- Toca casi todas las disciplinas difíciles a la vez: sistemas distribuidos, colas y workers, streaming en tiempo real, LLMs y prompting estructurado, RAG, sandboxing/seguridad, observabilidad y diseño de producto.
- Es el tipo de proyecto que las empresas están adoptando en producción masivamente, por lo que dominarlo tiene valor de mercado directo.

### 1.3 Objetivos medibles del proyecto

| # | Objetivo | Métrica de éxito |
|---|----------|------------------|
| O1 | Ejecutar tareas multi-paso de forma autónoma | Un run de 20+ pasos completa sin intervención humana |
| O2 | Coordinación multi-agente real | Orquestador delega a ≥3 sub-agentes especializados en paralelo |
| O3 | Observabilidad total | Cada paso (prompt, respuesta, tool call, costo, latencia) es trazable |
| O4 | Resiliencia | Un run sobrevive al reinicio del servidor y reanuda desde el último checkpoint |
| O5 | Seguridad | Ninguna herramienta ejecuta acciones destructivas sin política de aprobación |

---

## 2. Alcance

### 2.1 Dentro del alcance (v1)

- **Definición de agentes**: nombre, rol, modelo LLM, system prompt, herramientas permitidas, límites de presupuesto (tokens/costo/pasos).
- **Orquestador**: agente coordinador que descompone el objetivo en tareas, las asigna a sub-agentes, evalúa resultados y decide siguientes pasos.
- **Motor de ejecución**: loop agéntico (razonar → llamar herramienta → observar → repetir) con checkpoints persistentes.
- **Herramientas núcleo**: búsqueda web, fetch de URLs, ejecución de código Python en sandbox, lectura/escritura de archivos del workspace, consultas SQL de solo lectura.
- **Memoria**: memoria de trabajo por run + memoria de largo plazo con búsqueda vectorial (RAG sobre documentos subidos y aprendizajes previos).
- **Panel de control (frontend)**: crear/editar agentes y equipos, lanzar runs, ver el grafo de ejecución en vivo, inspeccionar cada paso, aprobar/rechazar acciones sensibles (human-in-the-loop).
- **Observabilidad**: traces completos, costos por run/agente/modelo, dashboard de métricas.
- **Multi-proveedor de LLM**: Anthropic, OpenAI y modelos locales vía Ollama, intercambiables por agente.

### 2.2 Fuera del alcance (v1)

- Marketplace público de agentes.
- Facturación/multi-tenancy comercial (se diseña la BD para soportarlo, no se implementa).
- Ejecución de agentes en navegador del usuario (browser automation) — candidato a v2.
- Fine-tuning de modelos.

---

## 3. Casos de uso de referencia

Estos tres casos guían el diseño y sirven como pruebas de aceptación end-to-end:

### CU-1 · Investigación profunda

> "Investiga el mercado de X, analiza 15 fuentes, y genera un informe con tablas comparativas."

→ Orquestador crea plan → 3 agentes *Researcher* buscan en paralelo → agente *Analyst* sintetiza → agente *Writer* redacta → entrega archivo Markdown.

### CU-2 · Análisis de datos autónomo

> "Aquí tienes un CSV de ventas, encuentra anomalías y explícalas."

→ Agente *DataAnalyst* escribe y ejecuta Python en sandbox, itera sobre errores, genera gráficos y conclusiones.

### CU-3 · Monitoreo continuo (scheduled run)

> "Cada mañana revisa estas 5 fuentes y avísame solo si hay algo relevante."

→ Run programado (cron) → agente evalúa relevancia → notifica vía webhook solo si supera umbral.

---

## 4. Arquitectura

### 4.1 Vista de alto nivel

```
┌───────────────────────────────────────────────────────────┐
│                    FRONTEND (React SPA)                    │
│   Builder de agentes · Vista de runs en vivo · Traces     │
└──────────────┬────────────────────────────┬───────────────┘
               │ REST (config/CRUD)         │ WebSocket/SSE (eventos en vivo)
┌──────────────▼────────────────────────────▼───────────────┐
│                  API GATEWAY (FastAPI)                     │
│   Auth · CRUD agentes/equipos/runs · Endpoint de eventos  │
└──────────────┬────────────────────────────────────────────┘
               │ encola jobs
┌──────────────▼───────────────┐   ┌────────────────────────┐
│      COLA (Redis Streams)    │──▶│   WORKERS (N procesos) │
└──────────────────────────────┘   │  Motor de ejecución    │
                                   │  agéntica (LangGraph)  │
                                   └───┬─────────┬──────────┘
                     ┌─────────────────┤         │
        ┌────────────▼──────┐  ┌───────▼───────┐ │
        │  PROVEEDORES LLM  │  │  HERRAMIENTAS │ │
        │ Anthropic/OpenAI/ │  │ web, sandbox  │ │
        │ Ollama            │  │ código, SQL…  │ │
        └───────────────────┘  └───────────────┘ │
┌────────────────────────────────────────────────▼──────────┐
│  PERSISTENCIA: PostgreSQL (+pgvector) · Redis · MinIO/S3  │
│  Estado de runs, checkpoints, traces, memoria vectorial,  │
│  archivos de workspace                                     │
└────────────────────────────────────────────────────────────┘
```

### 4.2 Componentes

#### API Gateway (FastAPI)

- CRUD de agentes, equipos, herramientas, runs.
- Autenticación JWT + API keys para acceso programático.
- Endpoint SSE/WebSocket que retransmite eventos de ejecución al frontend.
- **Nunca ejecuta agentes directamente: solo encola.**

#### Workers de ejecución

- Procesos independientes que consumen jobs de Redis Streams.
- Cada worker corre el loop agéntico: construir contexto → llamar LLM → parsear decisión → ejecutar herramienta → registrar paso → checkpoint → repetir hasta terminar, agotar presupuesto o requerir aprobación humana.
- Escalables horizontalmente (agregar workers = más runs en paralelo).

#### Motor de orquestación (LangGraph o implementación propia)

- El orquestador es un grafo de estados: `plan → delegate → collect → evaluate → (replan | synthesize) → done`.
- Cada sub-agente es un nodo con su propio sub-loop.
- El estado del grafo se serializa a PostgreSQL en cada transición (checkpoint) → esto cumple **O4 (resiliencia)**.
- **Recomendación**: empezar con LangGraph (checkpointing y grafos ya resueltos) y considerar motor propio solo si el framework limita.

#### Capa de herramientas (Tool Layer)

- Cada herramienta es un módulo con: JSON Schema de entrada, nivel de riesgo (`safe` / `sensitive` / `dangerous`), implementación async y timeout.
- Herramientas `sensitive`/`dangerous` disparan el flujo human-in-the-loop: el run se pausa, el frontend muestra la acción propuesta, el humano aprueba o rechaza.
- El sandbox de código corre en contenedores Docker efímeros sin red (o con allowlist), con límites de CPU/RAM/tiempo.

#### Memoria

- **Memoria de trabajo**: el historial del run, con compresión automática (resumir pasos viejos cuando el contexto crece) — esencial para runs largos.
- **Memoria de largo plazo**: pgvector. Documentos subidos se trocean, se embeben y quedan disponibles vía herramienta `search_memory`. Los agentes pueden guardar "aprendizajes" al finalizar un run.

#### Observabilidad

- Cada llamada LLM y tool call genera un registro en `trace_steps` (prompt, respuesta, tokens, costo, latencia, error).
- Integración opcional con Langfuse u OpenTelemetry.
- Dashboard: costo por run, tasa de éxito, pasos promedio, herramientas más usadas.

### 4.3 Flujo de un run (secuencia)

1. Usuario lanza run desde el frontend → `POST /runs` → estado `queued`, job en Redis.
2. Worker toma el job → estado `running` → instancia el grafo del orquestador.
3. Orquestador llama al LLM con el objetivo → produce plan (JSON estructurado) → crea tareas.
4. Sub-agentes se ejecutan (paralelo cuando las tareas son independientes) → cada paso emite evento → SSE → frontend actualiza el grafo en vivo.
5. Si una herramienta es `sensitive` → estado `awaiting_approval` → humano decide → continúa o aborta esa rama.
6. Orquestador evalúa resultados → replanifica si hace falta → sintetiza entregable final.
7. Estado `completed` (o `failed` con causa) → artefactos guardados en el workspace (MinIO/S3).

---

## 5. Stack tecnológico

| Capa | Tecnología | Justificación |
|------|------------|---------------|
| Backend API | Python 3.12 + FastAPI | Ecosistema de IA más maduro; async nativo |
| Orquestación | LangGraph | Grafos de agentes con checkpointing incluido; estándar de facto |
| Cola de jobs | Redis Streams | Simple, rápido, consumer groups para workers |
| Base de datos | PostgreSQL 16 + pgvector | Estado, traces y búsqueda vectorial en un solo motor |
| Archivos | MinIO (compatible S3) | Workspaces y artefactos self-hosted |
| Sandbox | Docker (contenedores efímeros) | Aislamiento real para ejecución de código |
| LLMs | Anthropic API + OpenAI API + Ollama | Multi-proveedor por agente; Ollama para iterar barato en local |
| Frontend | React 19 + Vite + TypeScript | SPA con estado complejo en tiempo real |
| UI del grafo | React Flow | Visualización interactiva del grafo de ejecución |
| Estado/datos frontend | TanStack Query + Zustand | Cache de servidor + estado de UI en vivo |
| Tiempo real | SSE (v1) → WebSocket si hace falta bidireccional | SSE es más simple y suficiente para streaming de eventos |
| Observabilidad | Langfuse (self-hosted) u OpenTelemetry | Traces LLM listos para usar |
| Infra dev | Docker Compose | Todo el stack con un comando |
| Tests | pytest + Playwright | Unit/integración backend + E2E del panel |

---

## 6. Modelo de datos (esquema inicial)

```sql
-- Definiciones
agents(id, name, role, model_provider, model_name, system_prompt,
       tool_ids[], max_steps, max_cost_usd, temperature, created_at)

teams(id, name, orchestrator_agent_id, description, created_at)

team_members(team_id, agent_id, specialty)

tools(id, name, description, input_schema jsonb,
      risk_level, timeout_seconds, enabled)

-- Ejecución
runs(id, team_id, goal text, status, -- queued|running|awaiting_approval|completed|failed|cancelled
     checkpoint jsonb,               -- estado serializado del grafo
     total_cost_usd, total_tokens, started_at, finished_at,
     schedule_cron, parent_run_id)

tasks(id, run_id, agent_id, description, status,
      depends_on_task_ids[], result jsonb, created_at, finished_at)

trace_steps(id, run_id, task_id, agent_id, step_number,
            kind,                    -- llm_call|tool_call|approval|checkpoint|error
            input jsonb, output jsonb,
            tokens_in, tokens_out, cost_usd, latency_ms, created_at)

approvals(id, run_id, trace_step_id, action_summary,
          status,                    -- pending|approved|rejected
          decided_by, decided_at)

-- Memoria
memory_documents(id, name, source, created_at)

memory_chunks(id, document_id, content text, embedding vector(1024), metadata jsonb)

agent_learnings(id, agent_id, run_id, content text, embedding vector(1024), created_at)

-- Plataforma
users(id, email, password_hash, role, created_at)

api_keys(id, user_id, key_hash, name, last_used_at)

workspace_files(id, run_id, path, size_bytes, mime_type, s3_key)
```

**Índices críticos**: `trace_steps(run_id, step_number)`, HNSW sobre columnas `embedding`, `runs(status)` parcial para la cola de aprobaciones.

---

## 7. Contratos clave (API)

```
POST   /api/agents                Crear agente
POST   /api/teams                 Crear equipo
POST   /api/runs                  Lanzar run { team_id, goal, files? }
GET    /api/runs/:id              Estado + resumen
GET    /api/runs/:id/events       SSE de eventos en vivo
GET    /api/runs/:id/trace        Trace completo paginado
POST   /api/runs/:id/approve      { trace_step_id, decision }
POST   /api/runs/:id/cancel       Cancelación cooperativa
POST   /api/memory/documents      Subir documento para RAG
GET    /api/metrics/costs         Costos agregados por periodo/agente
```

**Formato de evento SSE:**

```json
{ "type": "step", "run_id": "…", "agent": "researcher-2",
  "kind": "tool_call", "tool": "web_search",
  "summary": "Buscando: mercado SaaS LATAM 2026",
  "step": 14, "cost_usd": 0.0031 }
```

---

## 8. Roadmap por fases

### Fase 0 — Fundaciones (semana 1–2)

- Repo monorepo (`/backend`, `/frontend`, `/infra`), Docker Compose con Postgres+pgvector, Redis, MinIO.
- FastAPI con auth JWT, migraciones (Alembic), CRUD de agentes.
- Cliente LLM unificado multi-proveedor con conteo de tokens y costos.
- **Entregable**: puedo crear un agente y hacerle una pregunta simple (sin herramientas).

### Fase 1 — Agente único con herramientas (semana 3–5)

- Loop agéntico de un solo agente con tool calling estructurado.
- Herramientas: `web_search`, `web_fetch`, `read_file`, `write_file`.
- Worker + Redis Streams; `trace_steps` registrando todo.
- Frontend mínimo: lanzar run y ver el trace paso a paso (SSE).
- **Entregable**: CU-1 en versión simple con un solo agente.

### Fase 2 — Sandbox de código y memoria (semana 6–8)

- Herramienta `run_python` con contenedores Docker efímeros y límites de recursos.
- RAG: subida de documentos, chunking, embeddings, herramienta `search_memory`.
- Compresión de contexto para runs largos.
- **Entregable**: CU-2 completo (análisis de CSV autónomo).

### Fase 3 — Orquestación multi-agente (semana 9–12) ← el corazón

- Grafo orquestador en LangGraph: `plan → delegate → collect → evaluate → synthesize`.
- Ejecución paralela de sub-agentes con dependencias entre tareas.
- Checkpointing completo: matar el worker a mitad de run y reanudar.
- Visualización del grafo en vivo con React Flow.
- **Entregable**: CU-1 completo con equipo de 4 agentes; demo de resiliencia (O4).

### Fase 4 — Human-in-the-loop y seguridad (semana 13–15)

- Niveles de riesgo por herramienta, flujo de aprobaciones, cola de pendientes en UI.
- Presupuestos duros (tokens/costo/pasos) con corte limpio.
- Guardrails de entrada/salida (detección de prompt injection en contenido web, validación de outputs estructurados).
- **Entregable**: O5 cumplido; ningún tool `dangerous` corre sin aprobación.

### Fase 5 — Programación, métricas y pulido (semana 16–18)

- Runs programados (cron) + notificaciones webhook (CU-3).
- Dashboard de costos y métricas; comparador de modelos por agente.
- Suite de evaluación: 10 tareas de referencia con scoring automático para medir regresiones al cambiar prompts/modelos.
- Documentación de usuario, seeds de demo, video demo.
- **Entregable**: v1.0 completa, los 3 casos de uso funcionando end-to-end.

---

## 9. Retos técnicos principales (y su estrategia)

| Reto | Por qué es difícil | Estrategia |
|------|--------------------|------------|
| Estado de larga duración | Un run de horas no puede vivir en RAM | Checkpoint del grafo en cada transición; workers stateless |
| Explosión de contexto | Runs largos exceden la ventana del modelo | Resumir pasos antiguos; memoria de trabajo jerárquica |
| Paralelismo con dependencias | Tareas dependen de resultados de otras | DAG de tareas con `depends_on`; scheduler simple sobre el grafo |
| Costos descontrolados | Un agente en bucle puede quemar dinero | Presupuestos duros por run y por agente; kill-switch |
| Prompt injection | Contenido web puede manipular al agente | Sanitizar/etiquetar contenido externo como no-confiable; herramientas sensibles requieren aprobación |
| Sandbox seguro | Código generado por LLM es hostil por definición | Docker efímero, sin red por defecto, límites cgroups, timeout |
| Determinismo para debug | Los LLMs no son deterministas | Traces exhaustivos + replay: re-ejecutar un run reutilizando respuestas grabadas |
| Evaluación de calidad | ¿Cómo sé si un cambio mejoró el sistema? | Suite de evals con tareas fijas y scoring (LLM-as-judge + asserts) |

---

## 10. Criterios de aceptación de la v1

1. Los 3 casos de uso (CU-1, CU-2, CU-3) completan de forma autónoma.
2. Matar el proceso worker durante un run y reiniciarlo → el run reanuda y termina bien.
3. Un run con presupuesto de $0.50 se detiene limpiamente al alcanzarlo, con resumen parcial.
4. Una acción `dangerous` queda pausada hasta aprobación humana, con timeout configurable.
5. El trace de cualquier run permite reconstruir el 100% de las decisiones tomadas.
6. La suite de evals corre en CI y reporta score comparado contra la línea base.

---

## 11. Ideas para v2 (backlog)

- Agente con navegador (Playwright) para automatización web.
- Agentes que se comunican entre sí por mensajes (no solo vía orquestador).
- Marketplace/plantillas de equipos preconfigurados.
- Soporte MCP (Model Context Protocol) para conectar herramientas de terceros estándar.
- Multi-tenancy real con planes y límites por organización.
- Modo "swarm": N agentes idénticos compitiendo y un juez seleccionando la mejor solución.

---

## 12. Glosario

- **Run**: una ejecución completa de un objetivo por un equipo de agentes.
- **Orquestador**: agente coordinador que planifica, delega y evalúa.
- **Checkpoint**: snapshot serializado del estado del grafo, persistido en BD.
- **Human-in-the-loop (HITL)**: pausa del sistema para que un humano apruebe una acción.
- **Trace**: registro completo y ordenado de cada paso de un run.
- **Eval**: prueba automatizada que mide la calidad del comportamiento agéntico.
