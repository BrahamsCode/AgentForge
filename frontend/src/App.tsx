import { JSX } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./lib/auth";
import Agents from "./pages/Agents";
import Login from "./pages/Login";
import RunDetail from "./pages/RunDetail";
import Runs from "./pages/Runs";

function RequireAuth({ children }: { children: JSX.Element }) {
  const token = useAuth((s) => s.token);
  const location = useLocation();
  if (!token) return <Navigate to="/login" state={{ from: location }} replace />;
  return children;
}

function Layout({ children }: { children: JSX.Element }) {
  const { email, clear } = useAuth();
  return (
    <div className="layout">
      <nav className="sidebar">
        <div className="brand">
          Agent<span>Forge</span>
        </div>
        <NavLink to="/agents">Agentes</NavLink>
        <NavLink to="/runs">Runs</NavLink>
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
