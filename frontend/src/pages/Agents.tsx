import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { api } from "../lib/api";
import type { Agent, AskResponse, Provider } from "../lib/types";

const MODEL_PRESETS: Record<Provider, string[]> = {
  anthropic: ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"],
  openai: ["gpt-4o", "gpt-4o-mini"],
  ollama: [],
};

export default function Agents() {
  const queryClient = useQueryClient();
  const { data: agents, isLoading } = useQuery({
    queryKey: ["agents"],
    queryFn: () => api<Agent[]>("/api/agents"),
  });
  const [showForm, setShowForm] = useState(false);
  const [testing, setTesting] = useState<Agent | null>(null);

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 16 }}>
        <h1 style={{ margin: 0 }}>Agentes</h1>
        <button onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cerrar" : "+ Nuevo agente"}
        </button>
      </div>

      {showForm && (
        <AgentForm
          onCreated={() => {
            setShowForm(false);
            queryClient.invalidateQueries({ queryKey: ["agents"] });
          }}
        />
      )}

      <div className="panel">
        {isLoading && <p className="muted">Cargando…</p>}
        {agents && agents.length === 0 && <p className="muted">Aún no hay agentes.</p>}
        {agents && agents.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Nombre</th>
                <th>Rol</th>
                <th>Modelo</th>
                <th>Límites</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {agents.map((agent) => (
                <tr key={agent.id}>
                  <td>{agent.name}</td>
                  <td className="muted">{agent.role}</td>
                  <td>
                    {agent.model_provider} · {agent.model_name}
                  </td>
                  <td className="muted">
                    {agent.max_steps} pasos · ${agent.max_cost_usd}
                  </td>
                  <td>
                    <button className="ghost" onClick={() => setTesting(agent)}>
                      Probar
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {testing && <AskPanel agent={testing} onClose={() => setTesting(null)} />}
    </>
  );
}

function AgentForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [role, setRole] = useState("researcher");
  const [provider, setProvider] = useState<Provider>("anthropic");
  const [model, setModel] = useState(MODEL_PRESETS.anthropic[0]);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [maxSteps, setMaxSteps] = useState(30);
  const [maxCost, setMaxCost] = useState(1.0);

  const create = useMutation({
    mutationFn: () =>
      api<Agent>("/api/agents", {
        method: "POST",
        body: JSON.stringify({
          name,
          role,
          model_provider: provider,
          model_name: model,
          system_prompt: systemPrompt,
          max_steps: maxSteps,
          max_cost_usd: maxCost,
        }),
      }),
    onSuccess: onCreated,
  });

  function changeProvider(p: Provider) {
    setProvider(p);
    setModel(MODEL_PRESETS[p][0] ?? "");
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  return (
    <div className="panel">
      <h2>Nuevo agente</h2>
      <form onSubmit={submit}>
        <div className="grid2">
          <div>
            <label>Nombre</label>
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div>
            <label>Rol</label>
            <input value={role} onChange={(e) => setRole(e.target.value)} required />
          </div>
          <div>
            <label>Proveedor</label>
            <select value={provider} onChange={(e) => changeProvider(e.target.value as Provider)}>
              <option value="anthropic">Anthropic</option>
              <option value="openai">OpenAI</option>
              <option value="ollama">Ollama (local)</option>
            </select>
          </div>
          <div>
            <label>Modelo</label>
            {MODEL_PRESETS[provider].length > 0 ? (
              <select value={model} onChange={(e) => setModel(e.target.value)}>
                {MODEL_PRESETS[provider].map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            ) : (
              <input
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="llama3.3, qwen2.5, …"
                required
              />
            )}
          </div>
          <div>
            <label>Máx. pasos</label>
            <input
              type="number"
              min={1}
              max={500}
              value={maxSteps}
              onChange={(e) => setMaxSteps(Number(e.target.value))}
            />
          </div>
          <div>
            <label>Presupuesto (USD)</label>
            <input
              type="number"
              step="0.1"
              min="0.1"
              value={maxCost}
              onChange={(e) => setMaxCost(Number(e.target.value))}
            />
          </div>
        </div>
        <label>System prompt</label>
        <textarea
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          placeholder="Eres un investigador riguroso que cita sus fuentes…"
        />
        {create.error && <p className="error-text">{create.error.message}</p>}
        <div style={{ marginTop: 12 }}>
          <button disabled={create.isPending}>
            {create.isPending ? "Creando…" : "Crear agente"}
          </button>
        </div>
      </form>
    </div>
  );
}

function AskPanel({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  const [question, setQuestion] = useState("");
  const ask = useMutation({
    mutationFn: () =>
      api<AskResponse>(`/api/agents/${agent.id}/ask`, {
        method: "POST",
        body: JSON.stringify({ question }),
      }),
  });

  return (
    <div className="panel">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>
          Probar: {agent.name} <span className="muted">({agent.model_name})</span>
        </h2>
        <button className="ghost" onClick={onClose}>
          Cerrar
        </button>
      </div>
      <label>Pregunta (sin herramientas)</label>
      <textarea value={question} onChange={(e) => setQuestion(e.target.value)} />
      <div style={{ marginTop: 10 }}>
        <button disabled={ask.isPending || !question.trim()} onClick={() => ask.mutate()}>
          {ask.isPending ? "Pensando…" : "Enviar"}
        </button>
      </div>
      {ask.error && <p className="error-text">{ask.error.message}</p>}
      {ask.data && (
        <>
          <pre className="answer">{ask.data.answer}</pre>
          <p className="muted">
            {ask.data.tokens_in}→{ask.data.tokens_out} tokens · $
            {ask.data.cost_usd.toFixed(5)} · {ask.data.latency_ms} ms
          </p>
        </>
      )}
    </div>
  );
}
