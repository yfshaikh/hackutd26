import { useState } from "react";
import type { AgentId } from "../agents";
import { AgentMap } from "../components/AgentMap";
import { Scoreboard } from "../components/Scoreboard";
import { DecisionBand } from "../components/DecisionBand";
import { Framing } from "../components/Framing";
import { ScopeBoard } from "../components/ScopeBoard";
import { Timeline } from "../components/Timeline";

export function CommandCenter() {
  const [agent, setAgent] = useState<AgentId | null>(null);

  return (
    <>
      <DecisionBand />
      <Scoreboard />
      <main className="board">
        <AgentMap selected={agent} onSelect={setAgent} />
        <Timeline agent={agent} onClear={() => setAgent(null)} />
        <aside className="side">
          {/* The war room lives on the Briefing page now; this side stays the technical scope view. */}
          <ScopeBoard />
        </aside>
      </main>
      <Framing />
    </>
  );
}
