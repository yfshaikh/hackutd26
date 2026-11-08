import { Chat } from "../components/Chat";
import { ClusterView } from "../components/ClusterView";
import { DecisionBand } from "../components/DecisionBand";
import { Framing } from "../components/Framing";
import { IncidentRecord } from "../components/IncidentRecord";
import { ScopeBoard } from "../components/ScopeBoard";
import { Timeline } from "../components/Timeline";

export function CommandCenter() {
  return (
    <>
      <DecisionBand />
      <Framing />
      <main className="board">
        <ScopeBoard />
        <ClusterView />
        <Timeline />
        <div className="area-right">
          <IncidentRecord />
          <Chat />
        </div>
      </main>
    </>
  );
}
