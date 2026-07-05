import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { Agent, Run } from "../lib/types";

export default function Runs() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { data: agents } = useQuery({
    queryKey: ["agents"],
    queryFn: () => api<Agent[]>("/api/agents"),
  });
  const { data: runs, isLoading } = useQuery({
    queryKey: ["runs"],
    queryFn: () => api<Run[]>("/api/runs"),
    refetchInterval: 5000,
  });

  const [agentId, setAgentId] = useState("");
  const [goal, setGoal] = useState("");

  const launch = useMutation({
    mutationFn: () =>
      api<Run>("/api/runs", {
        method: "POST",
        body: JSON.stringify({ agent_id: agentId, goal }),
      }),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      navigate(`/runs/${run.id}`);
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    launch.mutate();
  }

  return (
    <>
      <h1>Runs</h1>

      <div className="panel">
        <h2>Lanzar run</h2>
        <form onSubmit={submit}>
          <label>Agente</label>
          <select value={agentId} onChange={(e) => setAgentId(e.target.value)} required>
            <option value="">— elige un agente —</option>
            {agents?.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.model_name})
              </option>
            ))}
          </select>
          <label>Objetivo</label>
          <textarea
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="Investiga X, compara Y y genera un informe en informe.md…"
            required
          />
          {launch.error && <p className="error-text">{launch.error.message}</p>}
          <div style={{ marginTop: 10 }}>
            <button disabled={launch.isPending || !agentId || !goal.trim()}>
              {launch.isPending ? "Encolando…" : "Lanzar"}
            </button>
          </div>
        </form>
      </div>

      <div className="panel">
        <h2>Historial</h2>
        {isLoading && <p className="muted">Cargando…</p>}
        {runs && runs.length === 0 && <p className="muted">Sin runs todavía.</p>}
        {runs && runs.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Objetivo</th>
                <th>Estado</th>
                <th>Costo</th>
                <th>Tokens</th>
                <th>Creado</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr
                  key={run.id}
                  className="clickable"
                  onClick={() => navigate(`/runs/${run.id}`)}
                >
                  <td>{run.goal.slice(0, 80)}</td>
                  <td>
                    <span className={`badge ${run.status}`}>{run.status}</span>
                  </td>
                  <td>${run.total_cost_usd.toFixed(4)}</td>
                  <td>{run.total_tokens}</td>
                  <td className="muted">{new Date(run.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
