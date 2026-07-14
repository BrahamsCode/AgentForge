import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { api } from "../lib/api";
import type { Agent, Team } from "../lib/types";

export default function Teams() {
  const queryClient = useQueryClient();
  const { data: teams, isLoading } = useQuery({
    queryKey: ["teams"],
    queryFn: () => api<Team[]>("/api/teams"),
  });
  const { data: agents } = useQuery({
    queryKey: ["agents"],
    queryFn: () => api<Agent[]>("/api/agents"),
  });
  const [showForm, setShowForm] = useState(false);

  const remove = useMutation({
    mutationFn: (id: string) => api<void>(`/api/teams/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["teams"] }),
  });

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 16 }}>
        <h1 style={{ margin: 0 }}>Equipos</h1>
        <button onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cerrar" : "+ Nuevo equipo"}
        </button>
      </div>

      {showForm && agents && (
        <TeamForm
          agents={agents}
          onCreated={() => {
            setShowForm(false);
            queryClient.invalidateQueries({ queryKey: ["teams"] });
          }}
        />
      )}

      <div className="panel">
        {isLoading && <p className="muted">Cargando…</p>}
        {teams && teams.length === 0 && (
          <p className="muted">
            Sin equipos. Un equipo = un agente orquestador que planifica y delega en miembros
            especializados.
          </p>
        )}
        {teams && teams.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Nombre</th>
                <th>Descripción</th>
                <th>Miembros</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {teams.map((team) => (
                <tr key={team.id}>
                  <td>{team.name}</td>
                  <td className="muted">{team.description}</td>
                  <td>{team.members.map((m) => m.agent_name).join(", ")}</td>
                  <td>
                    <button className="danger" onClick={() => remove.mutate(team.id)}>
                      Borrar
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function TeamForm({ agents, onCreated }: { agents: Agent[]; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [orchestratorId, setOrchestratorId] = useState("");
  const [memberIds, setMemberIds] = useState<string[]>([]);

  const create = useMutation({
    mutationFn: () =>
      api<Team>("/api/teams", {
        method: "POST",
        body: JSON.stringify({
          name,
          description,
          orchestrator_agent_id: orchestratorId,
          members: memberIds.map((id) => ({ agent_id: id, specialty: "" })),
        }),
      }),
    onSuccess: onCreated,
  });

  function toggleMember(id: string) {
    setMemberIds((prev) =>
      prev.includes(id) ? prev.filter((m) => m !== id) : [...prev, id],
    );
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  return (
    <div className="panel">
      <h2>Nuevo equipo</h2>
      <form onSubmit={submit}>
        <div className="grid2">
          <div>
            <label>Nombre</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div>
            <label>Orquestador</label>
            <select
              value={orchestratorId}
              onChange={(e) => setOrchestratorId(e.target.value)}
              required
            >
              <option value="">— elige el agente coordinador —</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.model_name})
                </option>
              ))}
            </select>
          </div>
        </div>
        <label>Descripción</label>
        <input value={description} onChange={(e) => setDescription(e.target.value)} />
        <label>Miembros (mínimo 1)</label>
        <div className="panel" style={{ padding: 10, marginBottom: 0 }}>
          {agents.map((a) => (
            <label key={a.id} className="row" style={{ margin: 4, cursor: "pointer" }}>
              <input
                type="checkbox"
                style={{ width: "auto" }}
                checked={memberIds.includes(a.id)}
                onChange={() => toggleMember(a.id)}
              />
              {a.name} <span className="muted">— {a.role}</span>
            </label>
          ))}
        </div>
        {create.error && <p className="error-text">{create.error.message}</p>}
        <div style={{ marginTop: 12 }}>
          <button disabled={create.isPending || !orchestratorId || memberIds.length === 0}>
            {create.isPending ? "Creando…" : "Crear equipo"}
          </button>
        </div>
      </form>
    </div>
  );
}
