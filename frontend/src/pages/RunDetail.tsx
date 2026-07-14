import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api, eventsUrl } from "../lib/api";
import type { AgentMessage, Approval, Run, RunEvent, TraceStep } from "../lib/types";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

export default function RunDetail() {
  const { runId } = useParams<{ runId: string }>();
  const queryClient = useQueryClient();

  const { data: run } = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api<Run>(`/api/runs/${runId}`),
    enabled: !!runId,
  });

  const { data: trace } = useQuery({
    queryKey: ["trace", runId],
    queryFn: () => api<TraceStep[]>(`/api/runs/${runId}/trace?limit=200`),
    enabled: !!runId,
  });

  const runTerminal = run ? TERMINAL.has(run.status) : false;
  const { data: messages } = useQuery({
    queryKey: ["messages", runId],
    queryFn: () => api<AgentMessage[]>(`/api/runs/${runId}/messages`),
    enabled: !!runId,
    refetchInterval: runTerminal ? false : 4000,
  });

  const { data: approvals } = useQuery({
    queryKey: ["approvals", runId],
    queryFn: () => api<Approval[]>(`/api/runs/${runId}/approvals?only_pending=true`),
    enabled: !!runId,
    refetchInterval: (query) =>
      (query.state.data as Approval[] | undefined)?.length ? 3000 : false,
  });

  const decide = useMutation({
    mutationFn: (vars: { approvalId: string; decision: "approved" | "rejected" }) =>
      api<Approval>(`/api/runs/${runId}/approve`, {
        method: "POST",
        body: JSON.stringify({ approval_id: vars.approvalId, decision: vars.decision }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["approvals", runId] });
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
    },
  });

  const [liveEvents, setLiveEvents] = useState<RunEvent[]>([]);
  const sourceRef = useRef<EventSource | null>(null);

  const isTerminal = run ? TERMINAL.has(run.status) : false;

  useEffect(() => {
    if (!runId || isTerminal || sourceRef.current) return;
    const source = new EventSource(eventsUrl(runId));
    sourceRef.current = source;

    source.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as RunEvent;
        setLiveEvents((prev) => [...prev, event]);
        if (event.type === "approval_required" || event.type === "approval_decided") {
          queryClient.invalidateQueries({ queryKey: ["approvals", runId] });
          queryClient.invalidateQueries({ queryKey: ["run", runId] });
        }
        if (event.type === "run_finished" || event.type === "run_cancelled") {
          source.close();
          sourceRef.current = null;
          queryClient.invalidateQueries({ queryKey: ["run", runId] });
          queryClient.invalidateQueries({ queryKey: ["trace", runId] });
        }
      } catch {
        /* keepalive u otro frame no-JSON */
      }
    };
    source.onerror = () => {
      /* el navegador reintenta solo; si el run terminó, el efecto lo cierra */
    };

    return () => {
      source.close();
      sourceRef.current = null;
    };
  }, [runId, isTerminal, queryClient]);

  const cancel = useMutation({
    mutationFn: () => api<Run>(`/api/runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["run", runId] }),
  });

  if (!run) return <p className="muted">Cargando…</p>;

  const liveCost = liveEvents.reduce((sum, e) => sum + (e.cost_usd ?? 0), 0);

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 14 }}>
        <h1 style={{ margin: 0 }}>
          Run <span className="muted">{run.id.slice(0, 8)}</span>{" "}
          <span className={`badge ${run.status}`}>{run.status}</span>
        </h1>
        {!isTerminal && (
          <button className="danger" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
            Cancelar
          </button>
        )}
      </div>

      <div className="panel">
        <p style={{ marginTop: 0 }}>{run.goal}</p>
        <p className="muted" style={{ marginBottom: 0 }}>
          ${Math.max(run.total_cost_usd, liveCost).toFixed(4)} · {run.total_tokens} tokens
          {run.error && <span className="error-text"> · {run.error}</span>}
        </p>
      </div>

      {approvals && approvals.length > 0 && (
        <div className="panel" style={{ borderColor: "var(--warn)" }}>
          <h2 style={{ color: "var(--warn)" }}>⚠ Aprobación requerida (human-in-the-loop)</h2>
          {approvals.map((approval) => (
            <div key={approval.id} className="step" style={{ borderLeftColor: "var(--warn)" }}>
              <div>{approval.action_summary}</div>
              <div className="row" style={{ marginTop: 8 }}>
                <button
                  disabled={decide.isPending}
                  onClick={() =>
                    decide.mutate({ approvalId: approval.id, decision: "approved" })
                  }
                >
                  Aprobar
                </button>
                <button
                  className="danger"
                  disabled={decide.isPending}
                  onClick={() =>
                    decide.mutate({ approvalId: approval.id, decision: "rejected" })
                  }
                >
                  Rechazar
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {messages && messages.length > 0 && (
        <div className="panel">
          <h2>💬 Mensajes entre agentes</h2>
          <div className="timeline">
            {messages.map((m) => (
              <div key={m.id} className="step" style={{ borderLeftColor: "var(--accent)" }}>
                <div>
                  <strong>{m.from_agent_name}</strong> →{" "}
                  {m.to_agent === "all" ? "todo el equipo" : m.to_agent}
                </div>
                <div>{m.content}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {run.final_answer && (
        <div className="panel">
          <h2>Respuesta final</h2>
          <pre className="answer">{run.final_answer}</pre>
        </div>
      )}

      <div className="panel">
        <h2>
          Trace {!isTerminal && <span className="badge running">en vivo</span>}
        </h2>
        <div className="timeline">
          {trace?.map((step) => (
            <TraceStepView key={step.id} step={step} />
          ))}
          {!isTerminal &&
            liveEvents
              .filter((e) => e.type === "step")
              .filter((e) => !trace || (e.step ?? 0) > trace.length)
              .map((e, i) => (
                <div key={`live-${i}`} className={`step ${e.kind ?? ""}`}>
                  <div>
                    <strong>#{e.step}</strong> {e.kind === "tool_call" ? `🔧 ${e.tool}` : "🧠 LLM"}
                  </div>
                  <div>{e.summary}</div>
                  {e.cost_usd != null && <div className="meta">${e.cost_usd.toFixed(5)}</div>}
                </div>
              ))}
          {trace?.length === 0 && liveEvents.length === 0 && (
            <p className="muted">Esperando el primer paso…</p>
          )}
        </div>
      </div>
    </>
  );
}

function TraceStepView({ step }: { step: TraceStep }) {
  const [open, setOpen] = useState(false);
  const title =
    step.kind === "tool_call"
      ? `🔧 ${(step.input?.tool as string) ?? "herramienta"}`
      : step.kind === "llm_call"
        ? "🧠 LLM"
        : `⚠️ ${step.kind}`;
  const summary =
    step.kind === "tool_call"
      ? JSON.stringify(step.input?.args ?? {}).slice(0, 140)
      : ((step.output?.text as string) ?? "").slice(0, 140) || "(razonando)";

  return (
    <div className={`step ${step.kind}`} onClick={() => setOpen((v) => !v)} style={{ cursor: "pointer" }}>
      <div>
        <strong>#{step.step_number}</strong> {title}
      </div>
      <div>{summary}</div>
      <div className="meta">
        {step.tokens_in + step.tokens_out > 0 && `${step.tokens_in}→${step.tokens_out} tokens · `}
        ${step.cost_usd.toFixed(5)} · {step.latency_ms} ms
      </div>
      {open && (
        <pre className="answer" onClick={(e) => e.stopPropagation()}>
          {JSON.stringify({ input: step.input, output: step.output }, null, 2)}
        </pre>
      )}
    </div>
  );
}
