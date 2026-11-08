// The three AI agents, as a bare row of characters — no panel, no chrome.
// Click one to see what it does and its own trace (reasoning, handoffs, tool calls).

import { AGENT_BY_ID, agentOf, REASONING_AGENTS, type AgentId } from "../agents";
import { useLive } from "../context";
import { ago } from "../format";
import { useNow } from "../hooks";
import type { TimelineEntry } from "../types";

const ACTIVE_MS = 20_000; // an agent counts as "working" if it acted this recently

export function AgentMap({ selected, onSelect }: { selected: AgentId | null; onSelect: (a: AgentId | null) => void }) {
  const { snapshot } = useLive();
  const now = useNow(2000);
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
              aria-pressed={selected === id}
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
        <AgentCard agent={selected} entries={byAgent.get(selected) ?? []} now={now} onClose={() => onSelect(null)} />
      )}
    </div>
  );
}

// What the clicked agent is + does, then its own log newest-first.
function AgentCard({
  agent, entries, now, onClose,
}: { agent: AgentId; entries: TimelineEntry[]; now: number; onClose: () => void }) {
  const a = AGENT_BY_ID[agent];
  const recent = [...entries].sort((x, y) => (x.ts < y.ts ? 1 : -1)).slice(0, 8);
  return (
    <div className="agent-card" role="region" aria-label={`${a.name} detail`}>
      <div className="agent-card-head">
        <strong>{a.name}</strong>
        <span className="agent-card-role">{a.role}</span>
        <button className="link-btn" onClick={onClose}>Close</button>
      </div>
      {a.blurb && <p className="agent-card-blurb">{a.blurb}</p>}
      <div className="agent-card-log-h">Trace · {entries.length} event{entries.length === 1 ? "" : "s"}</div>
      {recent.length === 0 ? (
        <p className="agent-card-empty">No activity yet — waiting for a detection to reach this agent.</p>
      ) : (
        <ol className="agent-card-log">
          {recent.map((e) => (
            <li key={e.id}>
              <span className="agent-card-time">{ago(e.ts, now)}</span>
              <span className="agent-card-text">{e.tool && <code>{e.tool}</code>} {e.text}</span>
              {e.reasoning && <p className="agent-card-reason">{e.reasoning}</p>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
