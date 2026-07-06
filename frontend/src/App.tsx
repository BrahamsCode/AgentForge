import { useQuery, useQueryClient } from "@tanstack/react-query";
import { JSX } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./lib/api";
import { useAuth } from "./lib/auth";
import { useOrg } from "./lib/orgStore";
import type { Organization } from "./lib/types";
import Agents from "./pages/Agents";
import Login from "./pages/Login";
import Metrics from "./pages/Metrics";
import Orgs from "./pages/Orgs";
import RunDetail from "./pages/RunDetail";
import Runs from "./pages/Runs";
import Teams from "./pages/Teams";

function RequireAuth({ children }: { children: JSX.Element }) {
  const token = useAuth((s) => s.token);
  const location = useLocation();
  if (!token) return <Navigate to="/login" state={{ from: location }} replace />;
  return children;
}

function OrgSelector() {
  const queryClient = useQueryClient();
  const { activeOrgId, setActiveOrg } = useOrg();
  const { data: orgs } = useQuery({
    queryKey: ["orgs"],
    queryFn: () => api<Organization[]>("/api/orgs"),
  });

  function change(value: string) {
    if (!value) {
      setActiveOrg(null, null);
    } else {
      const org = orgs?.find((o) => o.id === value);
      setActiveOrg(value, org?.name ?? null);
    }
    // El scope cambió: recarga agents/runs (y cualquier dato scopeado por org).
    queryClient.invalidateQueries({ queryKey: ["agents"] });
    queryClient.invalidateQueries({ queryKey: ["runs"] });
    queryClient.invalidateQueries({ queryKey: ["teams"] });
  }

  return (
    <div style={{ marginBottom: 12 }}>
      <label>Organización activa</label>
      <select value={activeOrgId ?? ""} onChange={(e) => change(e.target.value)}>
        <option value="">Personal</option>
        {orgs?.map((o) => (
          <option key={o.id} value={o.id}>
            {o.name}
          </option>
        ))}
      </select>
    </div>
  );
}

function Layout({ children }: { children: JSX.Element }) {
  const { email, clear } = useAuth();
  return (
    <div className="layout">
      <nav className="sidebar">
        <div className="brand">
          Agent<span>Forge</span>
        </div>
        <OrgSelector />
        <NavLink to="/agents">Agentes</NavLink>
        <NavLink to="/teams">Equipos</NavLink>
        <NavLink to="/runs">Runs</NavLink>
        <NavLink to="/metrics">Métricas</NavLink>
        <NavLink to="/orgs">Organizaciones</NavLink>
        <div className="spacer" />
        <div className="user">{email}</div>
        <button className="ghost" onClick={clear}>
          Salir
        </button>
      </nav>
      <main className="main">{children}</main>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/agents"
        element={
          <RequireAuth>
            <Layout>
              <Agents />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/teams"
        element={
          <RequireAuth>
            <Layout>
              <Teams />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/runs"
        element={
          <RequireAuth>
            <Layout>
              <Runs />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/metrics"
        element={
          <RequireAuth>
            <Layout>
              <Metrics />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/orgs"
        element={
          <RequireAuth>
            <Layout>
              <Orgs />
            </Layout>
          </RequireAuth>
        }
      />
      <Route
        path="/runs/:runId"
        element={
          <RequireAuth>
            <Layout>
              <RunDetail />
            </Layout>
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/agents" replace />} />
    </Routes>
  );
}
