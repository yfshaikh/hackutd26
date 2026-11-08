import { useState } from "react";
import type { AgentId } from "../agents";
import { AgentMap } from "../components/AgentMap";
import { Chat } from "../components/Chat";
import { Scoreboard } from "../components/Scoreboard";
import { DecisionBand } from "../components/DecisionBand";
import { Framing } from "../components/Framing";
import { ScopeBoard } from "../components/ScopeBoard";
import { Timeline } from "../components/Timeline";
import { useLive } from "../context";

// The incident record has its own top-level page now (/record).
const TABS = [
  { id: "scope", label: "Scope", Panel: ScopeBoard },
  { id: "chat", label: "War room", Panel: Chat },
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
      <Scoreboard />
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
