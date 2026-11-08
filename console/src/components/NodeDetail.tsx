// Detail drawer for one node (and optionally one GPU or one pod). Shared by the
// 2D list and the 3D floor: click a rack/GPU for node details, click a pod (or a
// sled in 3D) for its full spec, summary and logs.

import { useEffect, useRef } from "react";
import type { Asset, Cluster, Pod } from "../types";
import { PodInspector } from "./PodDetail";
import { AssetChip, HealthChip, utilTone } from "./Status";

export interface Selection {
  node: string;
  gpu?: number;
  /** Selected pod name, with its namespace. Both are set together. */
  pod?: string;
  namespace?: string;
}

/** Assets that live on this node, matched by their Kubernetes ref. */
export function assetsOnNode(cluster: Cluster, assets: Asset[], node: string): Asset[] {
  const pods = new Set(cluster.pods.filter((p) => p.node === node).map((p) => p.name));
  return assets.filter((a) => {
    const name = a.ref.split("/").pop() ?? "";
    return a.ref === `node/${node}` || pods.has(name);
  });
}

export function PodRow({ pod, onOpen }: { pod: Pod; onOpen: (p: Pod) => void }) {
  return (
    <li className={`pod${pod.quarantined ? " quarantined" : ""}`}>
      <button
        className="pod-open"
        onClick={() => onOpen(pod)}
        aria-label={`Inspect pod ${pod.namespace}/${pod.name}`}
      >
        <span className="pod-what">
          <span className="pname mono">{pod.namespace}/{pod.name}</span>
          <br />
          <span className="owner">
            {pod.owner === "unknown" ? "Unknown owner" : pod.owner === "law-firm" ? "Law firm" : "Platform"}
            {pod.usesGpu && ", uses GPU"}, {pod.phase}
            {pod.note && `. ${pod.note}`}
          </span>
        </span>
        <span className="pod-side">
          {pod.quarantined ? <span className="chip t-contained">Quarantined</span> : <HealthChip health={pod.health} />}
          <span className="pod-chev" aria-hidden>›</span>
        </span>
      </button>
    </li>
  );
}

export function NodeDetail({
  cluster,
  assets,
  sel,
  onSelect,
  onClose,
}: {
  cluster: Cluster;
  assets: Asset[];
  sel: Selection;
  onSelect: (s: Selection) => void;
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
  const livePod = sel.pod
    ? cluster.pods.find((p) => p.name === sel.pod && (!sel.namespace || p.namespace === sel.namespace))
    : undefined;
  const namespace = sel.namespace ?? livePod?.namespace ?? "lawfirm";

  // GPU workloads first when a GPU is selected: Kubernetes does not expose which
  // GPU slot a pod got, but "requests a GPU" is the useful division.
  const nodePods = cluster.pods.filter((p) => p.node === sel.node);
  const gpuPods = nodePods.filter((p) => p.usesGpu);
  const otherPods = nodePods.filter((p) => !p.usesGpu);
  const gpuView = sel.gpu !== undefined;
  const related = assetsOnNode(cluster, assets, sel.node);
  const gpus = node ? (sel.gpu === undefined ? node.gpus : node.gpus.filter((g) => g.index === sel.gpu)) : [];

  const openPod = (p: Pod) => onSelect({ node: p.node || sel.node, namespace: p.namespace, pod: p.name });
  const backToNode = () => onSelect({ node: sel.node, gpu: sel.gpu });
  const podRows = (list: Pod[]) => (
    <ul className="pods">
      {list.map((p) => (
        <PodRow key={p.namespace + p.name} pod={p} onOpen={openPod} />
      ))}
    </ul>
  );

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-h">
        <div className="panel-head drawer-head">
          <div className="drawer-heading">
            {sel.pod && (
              <button className="link-btn drawer-back" onClick={backToNode}>
                ← {sel.node}
              </button>
            )}
            <h2 id="drawer-h" className="mono">
              {sel.pod ? `${namespace}/${sel.pod}` : sel.node}
              {!sel.pod && sel.gpu !== undefined && ` / GPU ${sel.gpu}`}
            </h2>
          </div>
          <button ref={closeRef} className="btn" onClick={onClose}>Close</button>
        </div>

        {sel.pod ? (
          <PodInspector key={`${namespace}/${sel.pod}`} namespace={namespace} name={sel.pod} live={livePod} />
        ) : !node ? (
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
            {gpuView ? (
              <>
                <div className="panel-head">
                  <h2>GPU workloads</h2>
                  <span className="aside">{gpuPods.length} request a GPU</span>
                </div>
                <p className="pod-hint">
                  Kubernetes does not pin a pod to a GPU index. Click a pod for its spec and logs.
                </p>
                {gpuPods.length === 0 ? (
                  <div className="empty">No pod on this node requests a GPU right now.</div>
                ) : (
                  podRows(gpuPods)
                )}
                {otherPods.length > 0 && (
                  <>
                    <div className="panel-head">
                      <h2>Other pods on this node</h2>
                      <span className="aside">{otherPods.length}</span>
                    </div>
                    {podRows(otherPods)}
                  </>
                )}
              </>
            ) : (
              <>
                <div className="panel-head">
                  <h2>Pods on this node</h2>
                  <span className="aside">{nodePods.length}</span>
                </div>
                {nodePods.length === 0 ? (
                  <div className="empty">No pods reported on this node.</div>
                ) : (
                  podRows(nodePods)
                )}
              </>
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
