import { ClusterView } from "../components/ClusterView";
import { DecisionBand } from "../components/DecisionBand";
import { IncidentRecord } from "../components/IncidentRecord";
import { ScopeBoard } from "../components/ScopeBoard";
import { Timeline } from "../components/Timeline";

export function CommandCenter() {
  return (
    <>
      <DecisionBand />
      <main className="board">
        <ScopeBoard />
        <ClusterView />
        <Timeline />
        <IncidentRecord />
      </main>
    </>
  );
}
