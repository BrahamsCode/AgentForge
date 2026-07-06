import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { TeamTemplate } from "../lib/types";

export default function Templates() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { data: templates, isLoading } = useQuery({
    queryKey: ["templates"],
    queryFn: () => api<TeamTemplate[]>("/api/templates"),
  });

  const instantiate = useMutation({
    mutationFn: (id: string) =>
      api<{ team_id: string; agent_ids: string[] }>(`/api/templates/${id}/instantiate`, {
        method: "POST",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teams"] });
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      navigate("/teams");
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => api<void>(`/api/templates/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["templates"] }),
  });

  return (
    <>
      <h1>Plantillas de equipos</h1>
      <p className="muted">
        Crea un equipo completo (orquestador + miembros especializados) de un clic a partir de una
        plantilla preconfigurada.
      </p>

      {isLoading && <p className="muted">Cargando…</p>}
      {templates?.map((tpl) => (
        <div key={tpl.id} className="panel">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h2 style={{ margin: 0 }}>
              {tpl.name}{" "}
              <span className="badge">{tpl.category}</span>{" "}
              {tpl.is_builtin && <span className="badge completed">oficial</span>}
            </h2>
            <div className="row">
              <button
                disabled={instantiate.isPending}
                onClick={() => instantiate.mutate(tpl.id)}
              >
                Usar plantilla
              </button>
              {!tpl.is_builtin && (
                <button className="danger" onClick={() => remove.mutate(tpl.id)}>
                  Borrar
                </button>
              )}
            </div>
          </div>
          <p className="muted">{tpl.description}</p>
          <table>
            <thead>
              <tr>
                <th>Rol</th>
                <th>Agente</th>
                <th>Modelo</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Orquestador</td>
                <td>{tpl.spec.orchestrator.name}</td>
                <td className="muted">{tpl.spec.orchestrator.model_name}</td>
              </tr>
              {tpl.spec.members.map((m, i) => (
                <tr key={i}>
                  <td>{m.specialty || m.role}</td>
                  <td>{m.name}</td>
                  <td className="muted">{m.model_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {instantiate.error && <p className="error-text">{instantiate.error.message}</p>}
    </>
  );
}
