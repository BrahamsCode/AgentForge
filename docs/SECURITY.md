# Revisión de seguridad — AgentForge

Resumen de la revisión de las áreas sensibles de la plataforma. Se documentan
las mitigaciones existentes, los hallazgos corregidos y los riesgos residuales
conocidos.

## Modelo de amenaza

AgentForge ejecuta **código y decisiones generadas por un LLM** e ingiere
**contenido externo no confiable** (web, herramientas MCP). Las superficies de
mayor riesgo son: el sandbox de código, el acceso a archivos, la ingesta de
contenido externo (prompt injection), la autenticación y el aislamiento entre
organizaciones (multi-tenancy).

## Mitigaciones existentes

| Área | Mitigación |
|------|------------|
| **Sandbox `run_python`** | Contenedor Docker efímero: `--network none`, `--memory 512m`, `--cpus 1`, `--pids-limit 128`, `--read-only` + `tmpfs` acotado, `--user 1000:1000`, `timeout` interno y `asyncio.wait_for` externo. Salida truncada. |
| **Herramientas de archivos** | `read_file`/`write_file` resuelven el path a canónico y verifican `is_relative_to(workspace)`; rechazan `..`, symlinks y absolutos externos. Confinadas al workspace del run. |
| **Prompt injection** | Todo contenido externo (`web_fetch`, salidas MCP, `browser.extract_text`) se envuelve entre marcadores `<<CONTENIDO EXTERNO NO CONFIABLE>>`; el system prompt instruye a tratarlo como datos. `guardrails.scan_prompt_injection` detecta patrones. Defensa en profundidad, no barrera única. |
| **Human-in-the-loop** | Herramientas `sensitive`/`dangerous` (incl. `run_python`, `browser`, MCP) pasan por el gate de aprobación antes de ejecutarse; patrones destructivos en los argumentos elevan a aprobación. |
| **Autenticación** | Contraseñas con Argon2 (`argon2-cffi`); JWT HS256 con expiración; el token del SSE viaja por query param (necesario para `EventSource`). |
| **Presupuestos** | Límites duros por run (pasos, costo) y por organización (runs/día, costo/día → HTTP 429). |

## Hallazgos corregidos en esta revisión

### 1. IDOR / fuga entre organizaciones en endpoints por ID (severidad: media)

Los endpoints de acceso por UUID (`GET/PATCH/DELETE /api/agents/{id}`,
`/api/agents/{id}/ask`, `GET /api/runs/{id}`, `/trace`, `/messages`,
`/approvals`, `POST /api/runs/{id}/cancel`, `/approve`, `GET /api/runs/{id}/events`)
filtraban solo el **listado** por organización, pero al acceder por ID **no
verificaban** el contexto de organización. Un usuario podía leer o modificar
recursos de otra organización si conocía el UUID.

**Corrección:** los helpers `_get_agent_or_404` / `_get_run_or_404` ahora
filtran por `org_id == (org.id if org else None)` según la organización activa
(header `X-Org-Id`), devolviendo `404` (no `403`) para no filtrar la existencia
de recursos ajenos. El SSE, que se autentica por token en query (sin header),
exige pertenencia del usuario a la organización del run. Severidad media porque
los IDs son UUID v4 no enumerables.

### 2. Métricas agregadas sin scoping por organización (severidad: baja)

`GET /api/metrics/costs` agregaba costos, tokens y uso de herramientas sobre
**todos** los runs, filtrando por fecha pero no por organización — fuga de
información agregada entre tenants.

**Corrección:** el endpoint toma la organización activa y filtra las cuatro
consultas por `Run.org_id == (org.id if org else None)`.

### 3. Contexto personal compartido entre usuarios (severidad: media)

Los recursos sin organización (`org_id NULL`) no se filtraban por `created_by`,
así que en modo personal varios usuarios compartían el mismo espacio (podían
listar/leer agentes y runs de otros).

**Corrección:** helper `owner_scope(model, org, user)` — con organización activa
cualquier miembro ve los recursos de la org; en contexto personal solo los
propios (`org_id NULL AND created_by == user.id`). Aplicado en el listado y en
todos los accesos por ID de agents y runs, y en el SSE (que valida propiedad o
pertenencia según el caso).

## Riesgos residuales conocidos (backlog de endurecimiento)

- **Rate limiting de autenticación**: no hay límite de intentos de login; se
  recomienda añadirlo (p. ej. por IP/usuario) en el gateway.
- **JWT_SECRET**: debe fijarse a un valor fuerte en producción (el default es de
  desarrollo). El compose lo toma de la variable de entorno `JWT_SECRET`.
- **Egress del sandbox**: `run_python` corre sin red; si en el futuro se habilita
  una allowlist de red, revisar SSRF.

## Recomendaciones operativas

- Rotar `JWT_SECRET` y las credenciales de MinIO/Postgres en producción.
- Ejecutar los workers con acceso al socket de Docker **solo** en hosts de
  confianza (el sandbox lo requiere); considerar un runtime más aislado
  (gVisor/Kata) si se ejecuta código de terceros no confiables.
- Servir siempre tras TLS (el token del SSE viaja en la URL).
