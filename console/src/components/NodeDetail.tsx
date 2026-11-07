// Detail drawer for one node (and optionally one GPU). Shared by the 2D and 3D views.

import { useEffect, useRef } from "react";
import type { Asset, Cluster } from "../types";
import { AssetChip, HealthChip, utilTone } from "./Status";

export interface Selection {
  node: string;
  gpu?: number;
}

/** Assets that live on this node, matched by their Kubernetes ref. */
export function assetsOnNode(cluster: Cluster, assets: Asset[], node: string): Asset[] {
  const pods = new Set(cluster.pods.filter((p) => p.node === node).map((p) => p.name));
  return assets.filter((a) => {
    const name = a.ref.split("/").pop() ?? "";
    return a.ref === `node/${node}` || pods.has(name);
  });
}

export function NodeDetail({
  cluster,
  assets,
  sel,
  onClose,
}: {
  cluster: Cluster;
  assets: Asset[];
  sel: Selection;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  const node = cluster.nodes.find((n) => n.name === sel.node);
  const pods = cluster.pods.filter((p) => p.node === sel.node);
  const related = assetsOnNode(cluster, assets, sel.node);
  const gpus = node ? (sel.gpu === undefined ? node.gpus : node.gpus.filter((g) => g.index === sel.gpu)) : [];

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-h">
        <div className="panel-head">
          <h2 id="drawer-h" className="mono">
            {sel.node}
            {sel.gpu !== undefined && ` / GPU ${sel.gpu}`}
          </h2>
          <button ref={closeRef} className="btn" onClick={onClose}>Close</button>
        </div>
        {!node ? (
          <div className="empty"><strong>This node is no longer reported</strong></div>
        ) : (
          <>
            <div className="panel-body" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <HealthChip health={node.health} />
              {node.cordoned && <span className="chip t-contained">Cordoned</span>}
              <span className="chip t-muted">{node.role}</span>
              <span className="chip t-muted">CPU {Math.round(node.cpuPct)}%</span>
            </div>
            {gpus.map((g) => (
              <div className="gpu" key={g.index}>
                <div className="gpu-row">
                  <span className="label">GPU {g.index}, {g.model}</span>
                  <span>{Math.round(g.utilization)}%</span>
                </div>
                <div className={`meter t-${utilTone(g.utilization)}`}><i style={{ width: `${g.utilization}%` }} /></div>
                <div className="sub">
                  <span>{g.memUsedGiB.toFixed(1)} / {g.memTotalGiB.toFixed(0)} GiB</span>
                  <span>{Math.round(g.tempC)} °C</span>
                </div>
                {g.simulatedFault && <p className="sim">Simulated fault: {g.simulatedFault}</p>}
              </div>
            ))}
            <div className="panel-head"><h2>Pods on this node</h2><span className="aside">{pods.length}</span></div>
            {pods.length === 0 ? (
              <div className="empty">No pods reported on this node.</div>
            ) : (
              <ul className="pods">
                {pods.map((p) => (
                  <li key={p.namespace + p.name} className={`pod${p.quarantined ? " quarantined" : ""}`}>
                    <span>
                      <span className="pname mono">{p.namespace}/{p.name}</span>
                      <br />
                      <span className="owner">
                        {p.owner === "unknown" ? "Unknown owner" : p.owner === "law-firm" ? "Law firm" : "Platform"}
                        {p.usesGpu && ", uses GPU"}, {p.phase}
                        {p.note && `. ${p.note}`}
                      </span>
                    </span>
                    {p.quarantined ? <span className="chip t-contained">Quarantined</span> : <HealthChip health={p.health} />}
                  </li>
                ))}
              </ul>
            )}
            {related.length > 0 && (
              <>
                <div className="panel-head"><h2>Assets here</h2></div>
                <ul className="pods">
                  {related.map((a) => (
                    <li key={a.id} className="pod">
                      <span>{a.name}</span>
                      <AssetChip status={a.status} />
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </aside>
    </>
  );
}
