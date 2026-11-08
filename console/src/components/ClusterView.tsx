import { lazy, Suspense, useCallback, useState } from "react";
import { useLive } from "../context";
import type { Cluster } from "../types";
import { Empty, NoData } from "./Empty";
import { NodeDetail, type Selection } from "./NodeDetail";
import { HealthChip, utilTone } from "./Status";

const Floor3D = lazy(() => import("../floor/Floor3D"));

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const w = 300;
  const h = 36;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - (Math.min(100, Math.max(0, v)) / 100) * (h - 2) - 1}`);
  const last = values[values.length - 1];
  return (
    <svg className={`spark t-${utilTone(last)}`} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label={`GPU utilization trend, now ${Math.round(last)}%`}>
      <polyline points={pts.join(" ")} fill="none" stroke="var(--tone)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Nodes2D({ cluster, onSelect }: { cluster: Cluster; onSelect: (s: Selection) => void }) {
  return (
    <div className="nodes">
      {cluster.gpuHistory.length > 1 && (
        <div>
          <div className="gpu-row"><span className="label">Total GPU utilization</span></div>
          <Sparkline values={cluster.gpuHistory} />
        </div>
      )}
      {cluster.nodes.map((n) => {
        const pods = cluster.pods.filter((p) => p.node === n.name);
        return (
          <div className="node" key={n.name}>
            <div className="node-head">
              <button className="btn btn-ghost mono" style={{ padding: 0, minHeight: 0 }} onClick={() => onSelect({ node: n.name })}>
                {n.name}
              </button>
              <span className="tags">
                {n.cordoned && <span className="chip t-contained">Cordoned</span>}
                <HealthChip health={n.health} />
              </span>
            </div>
            {n.gpus.map((g) => (
              <button
                key={g.index}
                className="gpu"
                style={{ display: "block", width: "100%", textAlign: "left", background: "none", border: 0, borderTop: "1px solid var(--line)", cursor: "pointer" }}
                onClick={() => onSelect({ node: n.name, gpu: g.index })}
                aria-label={`GPU ${g.index} on ${n.name}, ${Math.round(g.utilization)} percent. Open details`}
              >
                <div className="gpu-row">
                  <span className="label">GPU {g.index}, {g.model}</span>
                  <span>{Math.round(g.utilization)}%</span>
                </div>
                <div className={`meter t-${utilTone(g.utilization)}`}><i style={{ width: `${g.utilization}%` }} /></div>
                <div className="sub">
                  <span>{g.memUsedGiB.toFixed(1)} / {g.memTotalGiB.toFixed(0)} GiB</span>
                  <span>{Math.round(g.tempC)} °C</span>
                  {g.simulatedFault && <span className="sim">Simulated: {g.simulatedFault}</span>}
                </div>
              </button>
            ))}
            {pods.length > 0 && (
              <ul className="pods">
                {pods.map((p) => (
                  <li key={p.namespace + p.name} className={`pod${p.quarantined ? " quarantined" : ""}`}>
                    <span className="pname mono" title={`${p.namespace}/${p.name}`}>{p.name}</span>
                    {p.quarantined ? <span className="chip t-contained">Quarantined</span> : <HealthChip health={p.health} />}
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function ClusterView({ initialView = "2d" }: { initialView?: "2d" | "3d" }) {
  const { snapshot, connection } = useLive();
  const [view, setView] = useState(initialView);
  const [sel, setSel] = useState<Selection | null>(null);
  const cluster = snapshot?.cluster;
  const close = useCallback(() => setSel(null), []);

  return (
    <section className="panel" aria-labelledby="cl-h" style={view === "3d" ? { minHeight: 420 } : undefined}>
      <div className="panel-head">
        <h2 id="cl-h">Cluster</h2>
        <div className="view-toggle" role="group" aria-label="Cluster view">
          <button aria-pressed={view === "2d"} onClick={() => setView("2d")}>List</button>
          <button aria-pressed={view === "3d"} onClick={() => setView("3d")}>3D floor</button>
        </div>
      </div>
      {!snapshot || !cluster ? (
        <NoData connection={connection} what="Nodes and GPUs" />
      ) : cluster.nodes.length === 0 ? (
        <Empty title="No nodes reported">The cluster has not reported any nodes yet.</Empty>
      ) : view === "2d" ? (
        <Nodes2D cluster={cluster} onSelect={setSel} />
      ) : (
        <Suspense fallback={<Empty title="Loading the 3D floor…" />}>
          <Floor3D onSelect={setSel} />
        </Suspense>
      )}
      {sel && cluster && snapshot && (
        <NodeDetail cluster={cluster} assets={snapshot.assets} sel={sel} onClose={close} />
      )}
    </section>
  );
}
