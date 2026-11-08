// The three AI agents, as a bare row of characters — no panel, no chrome.
// Click one to open a side panel with what it does and its own trace: each tool call as a
// chip, the tool's OUTPUT underneath it, handoffs, and the model's reasoning. A sidebar
// (not a modal) leaves the dashboard visible and usable while you read the trace.

import { useEffect, useState } from "react";
import { AGENT_BY_ID, agentOf, REASONING_AGENTS, type AgentId } from "../agents";
import { getAgentSpecs } from "../api";
import { useLive } from "../context";
import { Link } from "../router";
import { ago } from "../format";
import { useNow } from "../hooks";
import type { AgentSpec, TimelineEntry } from "../types";
import { VerdictChip } from "./Status";

const ACTIVE_MS = 20_000; // an agent counts as "working" if it acted this recently

export function AgentMap({ selected, onSelect }: { selected: AgentId | null; onSelect: (a: AgentId | null) => void }) {
  const { snapshot } = useLive();
  const now = useNow(2000);

  // Close the panel on Escape. (Hook must run every render, so it sits above the early return.)
  useEffect(() => {
    if (!selected) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onSelect(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected, onSelect]);

  if (!snapshot) return null;

  // Group timeline entries by the agent that emitted them (only the three AI agents matter here).
  const byAgent = new Map<AgentId, TimelineEntry[]>();
  for (const e of snapshot.timeline) {
    const id = agentOf(e);
    byAgent.set(id, [...(byAgent.get(id) ?? []), e]);
  }

  return (
    <div className="agent-strip">
      <div className="agent-strip-row">
        {REASONING_AGENTS.map((id) => {
          const a = AGENT_BY_ID[id];
          const list = byAgent.get(id) ?? [];
          const last = list.reduce<TimelineEntry | null>((l, e) => (!l || e.ts > l.ts ? e : l), null);
          const active = !!last && now - Date.parse(last.ts) < ACTIVE_MS;
          return (
            <button
              key={id}
              className={`agent-chip t-${a.tone}${selected === id ? " sel" : ""}${active ? " active" : ""}`}
              aria-haspopup="dialog"
              onClick={() => onSelect(selected === id ? null : id)}
              title={a.name}
            >
              <img src={a.img ?? undefined} alt={a.name} />
              <span className="agent-chip-name">{a.name}</span>
            </button>
          );
        })}
      </div>
      {selected && REASONING_AGENTS.includes(selected) && (
        <AgentSidebar agent={selected} entries={byAgent.get(selected) ?? []} now={now} onClose={() => onSelect(null)} />
      )}
    </div>
  );
}

// Every trace row is one of four kinds, each styled differently so you can tell at a glance
// whether the agent TALKED (to another agent / the operator) or ACTED (called a tool):
//   message  — a handoff, a question to another agent, or a final answer (speech bubble)
//   tool     — a tool call + its output (code chip + output block)
//   approval — a tool call held for a human (chip + "waiting for approval")
//   hyp      — a filed hypothesis (highlighted card)
type RowKind = "message" | "tool" | "approval" | "hyp";
const rowKind = (e: TimelineEntry): RowKind =>
  e.hypothesis ? "hyp" : e.autonomy?.mode === "needs-approval" ? "approval" : e.tool ? "tool" : "message";

function messageLabel(e: TimelineEntry): string {
  if (e.text.startsWith("Handing off to")) return `Handoff → ${e.text.replace("Handing off to ", "").replace(/\.$/, "")}`;
  if (e.text.startsWith("Asks the Investigator")) return "Question → Investigator";
  if (e.kind === "system") return "System";
  return "Message";
}

function TraceRow({ e, now }: { e: TimelineEntry; now: number }) {
  const kind = rowKind(e);
  const h = e.hypothesis;
  return (
    <li className={`tr tr-${kind}`}>
      <span className="agent-side-time">{ago(e.ts, now)}</span>
      <div className="agent-side-body">
        {kind === "hyp" && h && (
          <>
            <span className="hyp-line"><strong>Hypothesis · {h.name}</strong> <VerdictChip verdict={h.verdict} /></span>
            {h.evidence && <span className="agent-side-text">{h.evidence}</span>}
          </>
        )}
        {kind === "message" && (
          <>
            <span className="tr-label">{messageLabel(e)}</span>
            {/* A handoff's text is just the edge; the full message rides in reasoning. */}
            <p className="tr-bubble">
              {e.text.startsWith("Handing off to") ? e.reasoning || e.text : e.text.replace(/^Asks the Investigator: /, "")}
            </p>
          </>
        )}
        {(kind === "tool" || kind === "approval") && (
          <>
            <span className="tr-label">{kind === "approval" ? "Tool call · held for human approval" : "Tool call"}</span>
            <code className="agent-side-call">{e.tool}</code>
            {e.toolResult && <pre className="agent-side-out">{e.toolResult}</pre>}
          </>
        )}
        {kind !== "message" && e.reasoning && (
          <details className="tr-why">
            <summary>Model reasoning</summary>
            <p className="agent-side-reason">{e.reasoning}</p>
          </details>
        )}
      </div>
    </li>
  );
}

// The agent's real configuration, from GET /defender/agents (the same constants the pipeline runs on).
function Setup({ spec }: { spec: AgentSpec | null | undefined }) {
  if (spec === undefined) return <p className="agent-side-empty">Loading configuration…</p>;
  if (spec === null) return <p className="agent-side-empty">Configuration unavailable — is the backend running?</p>;
  return (
    <div className="setup">
      <dl className="setup-facts">
        <dt>Model</dt><dd className="mono">{spec.model}</dd>
        <dt>Tool budget</dt><dd>{spec.rounds} rounds; the last round has tools withheld so it must answer</dd>
        <dt>Temperature</dt><dd>0 (same incident → same response)</dd>
      </dl>
      <details className="setup-block" open>
        <summary>System prompt</summary>
        <pre className="agent-side-out setup-prompt">{spec.systemPrompt}</pre>
      </details>
      <div className="setup-block">
        <div className="agent-side-log-h setup-h">Tools · {spec.tools.length}</div>
        <ul className="setup-tools">
          {spec.tools.map((t) => (
            <li key={t.name}>
              <details>
                <summary>
                  <code className="agent-side-call">{t.name}</code>
                  <span className="setup-policy">{t.policy}</span>
                </summary>
                <p className="setup-desc">{t.description}</p>
                {t.runbookRef && <p className="setup-desc">Runbook step <Link href="/runbooks">{t.runbookRef}</Link> (containment-actions)</p>}
                <span className="tr-label">Arguments</span>
                {Object.keys(t.parameters?.properties ?? {}).length > 0 ? (
                  <pre className="agent-side-out">{JSON.stringify(t.parameters.properties, null, 2)}</pre>
                ) : (
                  <p className="setup-desc">None. The agent calls it bare.</p>
                )}
                <details className="tr-why">
                  <summary>Implementation (Python)</summary>
                  <pre className="agent-side-out setup-code">{t.implementation}</pre>
                </details>
              </details>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

// What the clicked agent is + does, with its live trace and its configuration as tabs — in a
// right-side panel that leaves the dashboard visible.
function AgentSidebar({
  agent, entries, now, onClose,
}: { agent: AgentId; entries: TimelineEntry[]; now: number; onClose: () => void }) {
  const a = AGENT_BY_ID[agent];
  const [tab, setTab] = useState<"trace" | "setup">("trace");
  const [specs, setSpecs] = useState<AgentSpec[] | null | undefined>(undefined);
  useEffect(() => {
    if (tab === "setup" && specs === undefined) getAgentSpecs().then(setSpecs).catch(() => setSpecs(null));
  }, [tab, specs]);
  // "Clear trace" hides this agent's rows up to now, for this viewer only (localStorage). The
  // backend timeline and decisions.jsonl audit log are untouched, so "Show all" brings them back.
  const clearKey = `trace-cleared:${agent}`;
  const [clearedAt, setClearedAt] = useState<string | null>(() => {
    try { return localStorage.getItem(clearKey); } catch { return null; }
  });
  const setCleared = (v: string | null) => {
    setClearedAt(v);
    try { if (v) localStorage.setItem(clearKey, v); else localStorage.removeItem(clearKey); } catch { /* view-only */ }
  };
  const visible = clearedAt ? entries.filter((e) => e.ts > clearedAt) : entries;
  // An agent's final answer IS its handoff message; show it once, as the handoff.
  const handedOff = new Set(entries.filter((e) => e.text.startsWith("Handing off to")).map((e) => e.reasoning));
  const recent = [...visible]
    .filter((e) => rowKind(e) !== "message" || e.text.startsWith("Handing off to") || !handedOff.has(e.text))
    .sort((x, y) => (x.ts < y.ts ? 1 : -1))
    .slice(0, 40);
  return (
    <aside
      className={`agent-side t-${a.tone}`}
      role="dialog"
      aria-modal="false"
      aria-label={`${a.name} detail`}
    >
      <header className="agent-side-head">
        {a.img && <img src={a.img} alt="" />}
        <div className="agent-side-title">
          <strong>{a.name}</strong>
          <span>{a.role}</span>
        </div>
        <button className="agent-side-x" onClick={onClose} aria-label="Close">✕</button>
      </header>
      {a.blurb && <p className="agent-side-blurb">{a.blurb}</p>}
      <div className="tabs agent-side-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "trace"} onClick={() => setTab("trace")}>Trace · {visible.length}</button>
        <button role="tab" aria-selected={tab === "setup"} onClick={() => setTab("setup")}>Setup</button>
      </div>
      {tab === "trace" && (entries.length > 0 || clearedAt) && (
        <div className="trace-tools">
          {clearedAt && <span>{entries.length - visible.length} older rows hidden</span>}
          {clearedAt && <button className="link-btn" onClick={() => setCleared(null)}>Show all</button>}
          {visible.length > 0 && (
            <button className="link-btn" onClick={() => setCleared(new Date().toISOString())}>Clear trace</button>
          )}
        </div>
      )}
      <div className="agent-side-scroll" role="tabpanel">
        {tab === "setup" ? (
          <Setup spec={specs === undefined ? undefined : specs?.find((s) => s.id === agent) ?? null} />
        ) : recent.length === 0 ? (
          <p className="agent-side-empty">{clearedAt ? "Trace cleared. New activity shows up here." : "No activity yet — waiting for a detection to reach this agent."}</p>
        ) : (
          <ol className="agent-side-log">
            {recent.map((e) => <TraceRow key={e.id} e={e} now={now} />)}
          </ol>
        )}
      </div>
    </aside>
  );
}
