import { lazy, Suspense, useCallback, useState } from "react";
import { DecisionBand } from "../components/DecisionBand";
import { Empty, NoData } from "../components/Empty";
import { NodeDetail, type Selection } from "../components/NodeDetail";
import { useLive } from "../context";

const Floor3D = lazy(() => import("../floor/Floor3D"));

export function FloorPage() {
  const { snapshot, connection } = useLive();
  const [sel, setSel] = useState<Selection | null>(null);
  const close = useCallback(() => setSel(null), []);

  return (
    <>
      <DecisionBand />
      <main className="floor-page">
        <section className="panel" aria-labelledby="floor-h">
          <div className="panel-head">
            <h2 id="floor-h">Data center floor</h2>
            <span className="aside">Drag to orbit, scroll to zoom, click a rack, GPU or pod for details</span>
          </div>
          {!snapshot ? (
            <NoData connection={connection} what="The floor" />
          ) : snapshot.cluster.nodes.length === 0 ? (
            <Empty title="No nodes reported">Racks appear here once the cluster reports its nodes.</Empty>
          ) : (
            <Suspense fallback={<Empty title="Loading the 3D floor…" />}>
              <Floor3D onSelect={setSel} />
            </Suspense>
          )}
        </section>
      </main>
      {sel && snapshot && (
        <NodeDetail
          cluster={snapshot.cluster}
          assets={snapshot.assets}
          sel={sel}
          onSelect={setSel}
          onClose={close}
        />
      )}
    </>
  );
}
