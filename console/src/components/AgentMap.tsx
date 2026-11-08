// The three AI agents, as a bare row of characters — no panel, no chrome.
// Click one to open a side panel with what it does and its own trace: each tool call as a
// chip, the tool's OUTPUT underneath it, handoffs, and the model's reasoning. A sidebar
// (not a modal) leaves the dashboard visible and usable while you read the trace.

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

// A trace row is a "tool call" row when it carries both the call and its result. For those we
// show the call as a chip and the OUTPUT below it, and drop `text` (which just repeats the call,
// e.g. "Looked up list_pods(...)"). Other rows — handoffs, the Advisor's questions to the
// Investigator, final summaries, approval requests — have no result, so `text` is their content.
const isToolRow = (e: TimelineEntry) => !!e.tool && !!e.toolResult;

// What the clicked agent is + does, then its own log newest-first — in a right-side panel that
// leaves the dashboard visible.
function AgentSidebar({
  agent, entries, now, onClose,
}: { agent: AgentId; entries: TimelineEntry[]; now: number; onClose: () => void }) {
  const a = AGENT_BY_ID[agent];
  const recent = [...entries].sort((x, y) => (x.ts < y.ts ? 1 : -1)).slice(0, 40);
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
      <div className="agent-side-log-h">Trace · {entries.length} event{entries.length === 1 ? "" : "s"}</div>
      {recent.length === 0 ? (
        <p className="agent-side-empty">No activity yet — waiting for a detection to reach this agent.</p>
      ) : (
        <ol className="agent-side-log">
          {recent.map((e) => {
            const tool = isToolRow(e);
            return (
              <li key={e.id}>
                <span className="agent-side-time">{ago(e.ts, now)}</span>
                <div className="agent-side-body">
                  {e.tool && <code className="agent-side-call">{e.tool}</code>}
                  {!tool && e.text && <span className="agent-side-text">{e.text}</span>}
                  {e.toolResult && <pre className="agent-side-out">{e.toolResult}</pre>}
                  {e.reasoning && <p className="agent-side-reason">{e.reasoning}</p>}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </aside>
  );
}
