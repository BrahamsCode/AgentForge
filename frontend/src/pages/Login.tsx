import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

export default function Login() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const setSession = useAuth((s) => s.setSession);
  const navigate = useNavigate();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "register") {
        await api("/api/auth/register", {
          method: "POST",
          body: JSON.stringify({ email, password }),
        });
      }
      const { access_token } = await api<{ access_token: string }>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setSession(access_token, email);
      navigate("/agents");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error inesperado");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <div className="panel login-card">
        <div className="brand" style={{ fontSize: 20, fontWeight: 700, marginBottom: 16 }}>
          Agent<span style={{ color: "var(--accent)" }}>Forge</span>
        </div>
        <div className="tabs">
          <button
            className={mode === "login" ? "" : "inactive"}
            onClick={() => setMode("login")}
            type="button"
          >
            Entrar
          </button>
          <button
            className={mode === "register" ? "" : "inactive"}
            onClick={() => setMode("register")}
            type="button"
          >
            Registrarse
          </button>
        </div>
        <form onSubmit={submit}>
          <label>Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoFocus
          />
          <label>Contraseña (mín. 8 caracteres)</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            required
          />
          {error && <p className="error-text">{error}</p>}
          <div style={{ marginTop: 14 }}>
            <button disabled={busy} style={{ width: "100%" }}>
              {busy ? "..." : mode === "login" ? "Entrar" : "Crear cuenta"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
