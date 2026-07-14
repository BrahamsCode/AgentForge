import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { api } from "../lib/api";
import { useOrg } from "../lib/orgStore";
import type { Organization, OrgMember, OrgRole } from "../lib/types";

export default function Orgs() {
  const queryClient = useQueryClient();
  const { data: orgs, isLoading } = useQuery({
    queryKey: ["orgs"],
    queryFn: () => api<Organization[]>("/api/orgs"),
  });
  const [showForm, setShowForm] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 16 }}>
        <h1 style={{ margin: 0 }}>Organizaciones</h1>
        <button onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cerrar" : "+ Nueva organización"}
        </button>
      </div>

      {showForm && (
        <OrgForm
          onCreated={() => {
            setShowForm(false);
            queryClient.invalidateQueries({ queryKey: ["orgs"] });
          }}
        />
      )}

      <div className="panel">
        {isLoading && <p className="muted">Cargando…</p>}
        {orgs && orgs.length === 0 && (
          <p className="muted">
            Aún no perteneces a ninguna organización. Crea una para compartir agentes y runs
            con límites de uso por plan.
          </p>
        )}
        {orgs && orgs.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Nombre</th>
                <th>Plan</th>
                <th>Límites diarios</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {orgs.map((org) => (
                <tr key={org.id}>
                  <td>{org.name}</td>
                  <td>
                    <span className="badge">{org.plan}</span>
                  </td>
                  <td className="muted">
                    {org.max_runs_per_day} runs · ${org.max_cost_usd_per_day}
                  </td>
                  <td>
                    <button
                      className="ghost"
                      onClick={() => setSelected((s) => (s === org.id ? null : org.id))}
                    >
                      {selected === org.id ? "Ocultar" : "Detalle"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selected && <OrgDetail orgId={selected} />}
    </>
  );
}

function OrgForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () =>
      api<Organization>("/api/orgs", {
        method: "POST",
        body: JSON.stringify({ name }),
      }),
    onSuccess: onCreated,
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  return (
    <div className="panel">
      <h2>Nueva organización</h2>
      <form onSubmit={submit}>
        <label>Nombre</label>
        <input value={name} onChange={(e) => setName(e.target.value)} required />
        {create.error && <p className="error-text">{create.error.message}</p>}
        <div style={{ marginTop: 12 }}>
          <button disabled={create.isPending || !name.trim()}>
            {create.isPending ? "Creando…" : "Crear organización"}
          </button>
        </div>
      </form>
    </div>
  );
}

function OrgDetail({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  const { activeOrgId, setActiveOrg } = useOrg();
  const { data: org, isLoading } = useQuery({
    queryKey: ["orgs", orgId],
    queryFn: () => api<Organization>(`/api/orgs/${orgId}`),
  });

  const [userId, setUserId] = useState("");
  const [role, setRole] = useState<OrgRole>("member");

  const addMember = useMutation({
    mutationFn: () =>
      api<OrgMember>(`/api/orgs/${orgId}/members`, {
        method: "POST",
        body: JSON.stringify({ user_id: userId, role }),
      }),
    onSuccess: () => {
      setUserId("");
      queryClient.invalidateQueries({ queryKey: ["orgs", orgId] });
    },
  });

  const removeMember = useMutation({
    mutationFn: (uid: string) =>
      api<void>(`/api/orgs/${orgId}/members/${uid}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["orgs", orgId] }),
  });

  function submitMember(e: FormEvent) {
    e.preventDefault();
    addMember.mutate();
  }

  if (isLoading) return <div className="panel">Cargando…</div>;
  if (!org) return null;

  const isActive = activeOrgId === org.id;

  return (
    <div className="panel">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>{org.name}</h2>
        <button
          className={isActive ? "danger" : "ghost"}
          onClick={() =>
            isActive ? setActiveOrg(null, null) : setActiveOrg(org.id, org.name)
          }
        >
          {isActive ? "Desactivar" : "Activar"}
        </button>
      </div>

      <div className="grid2" style={{ marginTop: 12 }}>
        <div>
          <label>Plan</label>
          <div>
            <span className="badge">{org.plan}</span>
          </div>
        </div>
        <div>
          <label>Creada</label>
          <div className="muted">{new Date(org.created_at).toLocaleString()}</div>
        </div>
        <div>
          <label>Máx. runs / día</label>
          <div>{org.max_runs_per_day}</div>
        </div>
        <div>
          <label>Máx. costo / día (USD)</label>
          <div>${org.max_cost_usd_per_day}</div>
        </div>
      </div>

      <h2 style={{ marginTop: 18 }}>Miembros</h2>
      {org.members && org.members.length > 0 ? (
        <table>
          <thead>
            <tr>
              <th>User ID</th>
              <th>Rol</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {org.members.map((m) => (
              <tr key={m.user_id}>
                <td className="muted">{m.user_id}</td>
                <td>
                  <span className="badge">{m.role}</span>
                </td>
                <td>
                  <button
                    className="danger"
                    disabled={removeMember.isPending}
                    onClick={() => removeMember.mutate(m.user_id)}
                  >
                    Quitar
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">Sin miembros listados.</p>
      )}

      <form onSubmit={submitMember} style={{ marginTop: 12 }}>
        <div className="grid2">
          <div>
            <label>Añadir miembro (user_id)</label>
            <input
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              placeholder="UUID del usuario"
              required
            />
          </div>
          <div>
            <label>Rol</label>
            <select value={role} onChange={(e) => setRole(e.target.value as OrgRole)}>
              <option value="member">member</option>
              <option value="admin">admin</option>
              <option value="owner">owner</option>
            </select>
          </div>
        </div>
        {(addMember.error || removeMember.error) && (
          <p className="error-text">
            {(addMember.error || removeMember.error)?.message}
          </p>
        )}
        <div style={{ marginTop: 12 }}>
          <button disabled={addMember.isPending || !userId.trim()}>
            {addMember.isPending ? "Añadiendo…" : "Añadir miembro"}
          </button>
        </div>
      </form>
    </div>
  );
}
