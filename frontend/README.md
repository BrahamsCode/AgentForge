# AgentForge — Frontend

Panel de control: React 19 + Vite + TypeScript + TanStack Query + Zustand.

```bash
npm install
npm run dev     # http://localhost:5173 (proxy /api → localhost:8000)
npm run build   # typecheck + build de producción
```

## Pantallas

- **Login** — registro e inicio de sesión (JWT en localStorage vía Zustand persist).
- **Agentes** — lista + creación con presets de modelo por proveedor y panel "Probar" (pregunta directa con tokens/costo/latencia).
- **Runs** — lanzar un run (agente + objetivo) e historial con estados.
- **Detalle de run** — trace paso a paso (llm_call / tool_call expandibles) y **stream SSE en vivo** vía `EventSource` a `/api/runs/{id}/events?token=…`; al terminar muestra la respuesta final.
