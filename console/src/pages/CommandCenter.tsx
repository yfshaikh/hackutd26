import { useState } from "react";
import type { AgentId } from "../agents";
import { AgentMap } from "../components/AgentMap";
import { Chat } from "../components/Chat";
import { DecisionBand } from "../components/DecisionBand";
import { Framing } from "../components/Framing";
import { IncidentRecord } from "../components/IncidentRecord";
import { ScopeBoard } from "../components/ScopeBoard";
import { Timeline } from "../components/Timeline";
import { useLive } from "../context";

// Cluster health lives on the Floor page, so it isn't duplicated as a side tab here.
const TABS = [
  { id: "scope", label: "Scope", Panel: ScopeBoard },
  { id: "record", label: "Record", Panel: IncidentRecord },
  { id: "chat", label: "Chat", Panel: Chat },
] as const;

export function CommandCenter() {
  const { snapshot } = useLive();
  const [agent, setAgent] = useState<AgentId | null>(null);
  const [tab, setTab] = useState<(typeof TABS)[number]["id"]>("scope");
  const hit = snapshot?.assets.filter((a) => a.status !== "clean").length ?? 0;
  const Panel = TABS.find((t) => t.id === tab)!.Panel;

  return (
    <>
      <DecisionBand />
      <main className="board">
        <AgentMap selected={agent} onSelect={setAgent} />
        <Timeline agent={agent} onClear={() => setAgent(null)} />
        <aside className="side">
          <div className="tabs" role="tablist" aria-label="Incident details">
            {TABS.map((t) => (
              <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}>
                {t.label}
                {t.id === "scope" && hit > 0 && <span className="tab-badge">{hit}</span>}
              </button>
            ))}
          </div>
          <div className="side-body" role="tabpanel">
            <Panel />
          </div>
        </aside>
      </main>
      <Framing />
    </>
  );
}
