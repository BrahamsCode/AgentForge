import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { Agent, Run, Team } from "../lib/types";

export default function Runs() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { data: agents } = useQuery({
    queryKey: ["agents"],
    queryFn: () => api<Agent[]>("/api/agents"),
  });
  const { data: teams } = useQuery({
    queryKey: ["teams"],
    queryFn: () => api<Team[]>("/api/teams"),
  });
  const { data: runs, isLoading } = useQuery({
    queryKey: ["runs"],
    queryFn: () => api<Run[]>("/api/runs"),
    refetchInterval: 5000,
  });

  // executor: "agent:<id>" o "team:<id>"
  const [executor, setExecutor] = useState("");
  const [goal, setGoal] = useState("");

  const launch = useMutation({
    mutationFn: () => {
      const [kind, id] = executor.split(":");
      return api<Run>("/api/runs", {
        method: "POST",
        body: JSON.stringify(
          kind === "team" ? { team_id: id, goal } : { agent_id: id, goal },
        ),
      });
    },
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
          <label>Ejecutor (agente o equipo)</label>
          <select value={executor} onChange={(e) => setExecutor(e.target.value)} required>
            <option value="">— elige agente o equipo —</option>
            {agents && agents.length > 0 && (
              <optgroup label="Agentes">
                {agents.map((a) => (
                  <option key={a.id} value={`agent:${a.id}`}>
                    {a.name} ({a.model_name})
                  </option>
                ))}
              </optgroup>
            )}
            {teams && teams.length > 0 && (
              <optgroup label="Equipos (multi-agente)">
                {teams.map((t) => (
                  <option key={t.id} value={`team:${t.id}`}>
                    ⚙ {t.name} — {t.members.length} miembros
                  </option>
                ))}
              </optgroup>
            )}
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
            <button disabled={launch.isPending || !executor || !goal.trim()}>
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
