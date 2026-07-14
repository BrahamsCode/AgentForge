import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

interface CostByAgent {
  agent_id: string | null;
  agent_name: string | null;
  cost_usd: number;
  tokens: number;
  steps: number;
}

interface MetricsSummary {
  runs_total: number;
  runs_completed: number;
  runs_failed: number;
  success_rate: number;
  total_cost_usd: number;
  total_tokens: number;
  avg_steps_per_run: number;
  cost_by_agent: CostByAgent[];
  top_tools: { tool: string; count: number }[];
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel" style={{ flex: 1, marginBottom: 0 }}>
      <div className="muted" style={{ fontSize: 12 }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{value}</div>
    </div>
  );
}

export default function Metrics() {
  const { data, isLoading } = useQuery({
    queryKey: ["metrics"],
    queryFn: () => api<MetricsSummary>("/api/metrics/costs?since_days=30"),
    refetchInterval: 10000,
  });

  if (isLoading || !data) return <p className="muted">Cargando métricas…</p>;

  return (
    <>
      <h1>Métricas (últimos 30 días)</h1>

      <div className="row" style={{ gap: 12, marginBottom: 18 }}>
        <Stat label="Runs" value={String(data.runs_total)} />
        <Stat label="Tasa de éxito" value={`${(data.success_rate * 100).toFixed(0)}%`} />
        <Stat label="Costo total" value={`$${data.total_cost_usd.toFixed(4)}`} />
        <Stat label="Tokens" value={data.total_tokens.toLocaleString()} />
        <Stat label="Pasos/run" value={data.avg_steps_per_run.toFixed(1)} />
      </div>

      <div className="panel">
        <h2>Costo por agente</h2>
        {data.cost_by_agent.length === 0 ? (
          <p className="muted">Sin datos.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Agente</th>
                <th>Costo</th>
                <th>Tokens</th>
                <th>Pasos</th>
              </tr>
            </thead>
            <tbody>
              {data.cost_by_agent.map((row, i) => (
                <tr key={row.agent_id ?? i}>
                  <td>{row.agent_name ?? "—"}</td>
                  <td>${row.cost_usd.toFixed(5)}</td>
                  <td>{row.tokens.toLocaleString()}</td>
                  <td>{row.steps}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <h2>Herramientas más usadas</h2>
        {data.top_tools.length === 0 ? (
          <p className="muted">Sin llamadas a herramientas todavía.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Herramienta</th>
                <th>Usos</th>
              </tr>
            </thead>
            <tbody>
              {data.top_tools.map((row) => (
                <tr key={row.tool}>
                  <td>{row.tool}</td>
                  <td>{row.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
