import { useAuth } from "./auth";
import { useOrg } from "./orgStore";

export const API_BASE = import.meta.env.VITE_API_URL ?? "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { token, clear } = useAuth.getState();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string> | undefined),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  // Organización activa: si existe, todas las peticiones van scopeadas con
  // X-Org-Id. Sin org activa (modo personal) no se envía el header.
  const { activeOrgId } = useOrg.getState();
  if (activeOrgId) headers["X-Org-Id"] = activeOrgId;

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (response.status === 401) {
    clear();
    window.location.href = "/login";
    throw new ApiError(401, "Sesión expirada");
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* cuerpo no-JSON */
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function eventsUrl(runId: string): string {
  const { token } = useAuth.getState();
  return `${API_BASE}/api/runs/${runId}/events?token=${encodeURIComponent(token ?? "")}`;
}
