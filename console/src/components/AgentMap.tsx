// The three AI agents, as a bare row of characters — no panel, no chrome.
// Click one to open a modal with what it does and its own trace (reasoning, handoffs,
// tool calls). A modal (not an inline panel) keeps it readable over the busy dashboard.

import { useEffect } from "react";
import { AGENT_BY_ID, agentOf, REASONING_AGENTS, type AgentId } from "../agents";
import { useLive } from "../context";
import { ago } from "../format";
import { useNow } from "../hooks";
import type { TimelineEntry } from "../types";

const ACTIVE_MS = 20_000; // an agent counts as "working" if it acted this recently

export function AgentMap({ selected, onSelect }: { selected: AgentId | null; onSelect: (a: AgentId | null) => void }) {
  const { snapshot } = useLive();
  const now = useNow(2000);

  // Close the modal on Escape. (Hook must run every render, so it sits above the early return.)
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
        <AgentModal agent={selected} entries={byAgent.get(selected) ?? []} now={now} onClose={() => onSelect(null)} />
      )}
    </div>
  );
}

// What the clicked agent is + does, then its own log newest-first — in a modal overlay.
function AgentModal({
  agent, entries, now, onClose,
}: { agent: AgentId; entries: TimelineEntry[]; now: number; onClose: () => void }) {
  const a = AGENT_BY_ID[agent];
  const recent = [...entries].sort((x, y) => (x.ts < y.ts ? 1 : -1)).slice(0, 25);
  return (
    <div className="agent-modal-backdrop" onClick={onClose}>
      <div
        className={`agent-modal t-${a.tone}`}
        role="dialog"
        aria-modal="true"
        aria-label={`${a.name} detail`}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="agent-modal-head">
          {a.img && <img src={a.img} alt="" />}
          <div className="agent-modal-title">
            <strong>{a.name}</strong>
            <span>{a.role}</span>
          </div>
          <button className="agent-modal-x" onClick={onClose} aria-label="Close">✕</button>
        </header>
        {a.blurb && <p className="agent-modal-blurb">{a.blurb}</p>}
        <div className="agent-modal-log-h">Trace · {entries.length} event{entries.length === 1 ? "" : "s"}</div>
        {recent.length === 0 ? (
          <p className="agent-modal-empty">No activity yet — waiting for a detection to reach this agent.</p>
        ) : (
          <ol className="agent-modal-log">
            {recent.map((e) => (
              <li key={e.id}>
                <span className="agent-modal-time">{ago(e.ts, now)}</span>
                <span className="agent-modal-text">{e.tool && <code>{e.tool}</code>} {e.text}</span>
                {e.reasoning && <p className="agent-modal-reason">{e.reasoning}</p>}
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
