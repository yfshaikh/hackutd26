// Pod inspector for the floor drawer: summary, live spec, and logs.
// Everything here is one pod, fetched on demand from /cluster/pods/...

import { useEffect, useState, type ReactNode } from "react";
import { errorText, getPodDetail, getPodLogs } from "../api";
import { dateTime } from "../format";
import type { Pod, PodContainerDetail, PodDetail, PodLogs } from "../types";
import { HealthChip } from "./Status";

type Tab = "overview" | "specs" | "logs";

const OWNER_LABEL: Record<Pod["owner"], string> = {
  "law-firm": "Law firm workload",
  platform: "Platform workload",
  unknown: "Unknown owner",
};

function StateChip({ state }: { state: string }) {
  const tone = state === "running" ? "clean" : state === "waiting" ? "invest" : "muted";
  return <span className={`chip t-${tone}`}>{state}</span>;
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="field">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function resourcesText(c: PodContainerDetail): string {
  const rows = Object.entries(c.resources).flatMap(([bag, values]) =>
    Object.entries(values).map(([key, value]) => `${bag} ${key}=${value}`),
  );
  return rows.length ? rows.join(", ") : "none declared";
}

function commandText(c: PodContainerDetail): string {
  return [...c.command, ...c.args].join(" ");
}

function ContainerCard({ c }: { c: PodContainerDetail }) {
  const cmd = commandText(c);
  return (
    <article className="container-card">
      <div className="container-head">
        <strong className="mono">{c.name}</strong>
        <span className="container-meta">
          {c.stateReason && <span className="container-reason">{c.stateReason}</span>}
          <StateChip state={c.state} />
          {c.restartCount > 0 && <span className="chip t-high">{c.restartCount} restarts</span>}
          {c.state === "terminated" && c.exitCode !== undefined && (
            <span className={`chip ${c.exitCode === 0 ? "t-muted" : "t-exfil"}`}>exit {c.exitCode}</span>
          )}
        </span>
      </div>
      <div className="container-image mono">{c.image}</div>
      {cmd && <pre className="pod-cmd">{cmd}</pre>}
      <dl className="spec-grid">
        <div>
          <dt>Resources</dt>
          <dd>{resourcesText(c)}</dd>
        </div>
        {c.ports.length > 0 && (
          <div>
            <dt>Ports</dt>
            <dd>{c.ports.map((p) => `${p.name ? `${p.name}: ` : ""}${p.containerPort}/${p.protocol}`).join(", ")}</dd>
          </div>
        )}
        {c.env.length > 0 && (
          <div>
            <dt>Environment</dt>
            <dd className="mono">{c.env.join(", ")}</dd>
          </div>
        )}
        {c.envFrom.length > 0 && (
          <div>
            <dt>Env from</dt>
            <dd className="mono">{c.envFrom.join(", ")}</dd>
          </div>
        )}
        {c.volumeMounts.length > 0 && (
          <div>
            <dt>Mounts</dt>
            <dd className="mono">
              {c.volumeMounts
                .map((m) => `${m.mountPath} ← ${m.name}${m.readOnly ? " (ro)" : ""}`)
                .join(", ")}
            </dd>
          </div>
        )}
        {c.lastState && (
          <div>
            <dt>Previous run</dt>
            <dd>
              {c.lastState}
              {c.lastExitCode !== undefined && `, exit ${c.lastExitCode}`}
            </dd>
          </div>
        )}
      </dl>
    </article>
  );
}

export function PodInspector({ namespace, name, live }: { namespace: string; name: string; live?: Pod }) {
  const [detail, setDetail] = useState<PodDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [tab, setTab] = useState<Tab>("overview");

  // Fetch the full spec when the selected pod changes (or Refresh is pressed).
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    getPodDetail(namespace, name)
      .then((d) => {
        if (!alive) return;
        setDetail(d);
        setLoading(false);
      })
      .catch((e) => {
        if (!alive) return;
        setError(errorText(e));
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [namespace, name, attempt]);

  // A new pod starts on the summary tab.
  useEffect(() => setTab("overview"), [namespace, name]);

  const [container, setContainer] = useState("");
  const [tail, setTail] = useState(200);
  const [timestamps, setTimestamps] = useState(false);
  const [previous, setPrevious] = useState(false);
  const [logs, setLogs] = useState<PodLogs | null>(null);
  const [logError, setLogError] = useState<string | null>(null);
  const [logBusy, setLogBusy] = useState(false);
  const [reload, setReload] = useState(0);

  const containers = detail?.containers ?? [];
  const selectedContainer =
    container && containers.some((c) => c.name === container) ? container : (containers[0]?.name ?? "");
  const hasRestarts = containers.some((c) => c.restartCount > 0);
  const restarts = containers.reduce((sum, c) => sum + c.restartCount, 0);

  // Option changes invalidate the visible log immediately.
  useEffect(() => {
    setLogs(null);
    setLogError(null);
  }, [namespace, name, selectedContainer, tail, previous, timestamps]);

  // Fetch logs only while the Logs tab is open.
  useEffect(() => {
    if (tab !== "logs" || !selectedContainer) return;
    let alive = true;
    setLogBusy(true);
    setLogError(null);
    getPodLogs(namespace, name, {
      container: selectedContainer,
      tailLines: tail,
      previous,
      timestamps,
    })
      .then((l) => {
        if (alive) setLogs(l);
      })
      .catch((e) => {
        if (!alive) return;
        setLogs(null);
        setLogError(errorText(e));
      })
      .finally(() => {
        if (alive) setLogBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [tab, namespace, name, selectedContainer, tail, previous, timestamps, reload]);

  if (loading && !detail) {
    return (
      <div className="pod-inspector">
        {live && (
          <div className="panel-body pod-chips">
            <HealthChip health={live.health} />
            <span className="chip t-muted">{live.phase}</span>
            <span className={`chip ${live.owner === "unknown" ? "t-exfil" : "t-muted"}`}>
              {OWNER_LABEL[live.owner]}
            </span>
            {live.usesGpu && <span className="chip t-invest">GPU workload</span>}
            {live.quarantined && <span className="chip t-contained">Quarantined</span>}
          </div>
        )}
        <div className="empty">Loading pod spec…</div>
      </div>
    );
  }
  if (error && !detail) {
    return (
      <div className="empty">
        <strong>Could not read this pod</strong>
        <p>{error}</p>
        <button className="btn" onClick={() => setAttempt((n) => n + 1)}>Retry</button>
      </div>
    );
  }

  const d = detail!;
  const annotations = Object.entries(d.annotations).filter(
    ([key]) => key !== "kubectl.kubernetes.io/last-applied-configuration",
  );

  return (
    <div className="pod-inspector">
      <div className="panel-body pod-chips">
        <HealthChip health={d.health} />
        <span className="chip t-muted">{d.phase}</span>
        <span className={`chip ${d.owner === "unknown" ? "t-exfil" : "t-muted"}`}>{OWNER_LABEL[d.owner]}</span>
        {d.usesGpu && <span className="chip t-invest">GPU workload</span>}
        {d.quarantined && <span className="chip t-contained">Quarantined</span>}
        {d.workload && (
          <span className="chip t-muted mono">
            {d.workload.kind}/{d.workload.name}
          </span>
        )}
      </div>

      <p className="pod-summary">{d.summary}</p>

      {error && <p className="pod-inline-error">{error} Showing the last successful read.</p>}

      <div className="tabs" role="tablist" aria-label="Pod detail sections">
        <button role="tab" aria-selected={tab === "overview"} onClick={() => setTab("overview")}>Overview</button>
        <button role="tab" aria-selected={tab === "specs"} onClick={() => setTab("specs")}>Specs</button>
        <button role="tab" aria-selected={tab === "logs"} onClick={() => setTab("logs")}>Logs</button>
      </div>

      {tab === "overview" && (
        <div className="pod-tab">
          <dl className="pod-facts">
            <Fact label="Namespace">{d.namespace}</Fact>
            <Fact label="Node">
              <span className="mono">{d.node || "not scheduled"}</span>
            </Fact>
            <Fact label="Workload">
              {d.workload ? <span className="mono">{d.workload.kind}/{d.workload.name}</span> : "standalone pod"}
            </Fact>
            <Fact label="Containers">
              {d.containers.length}
              {restarts > 0 && ` · ${restarts} restart${restarts === 1 ? "" : "s"}`}
            </Fact>
            <Fact label="Service account">
              <span className="mono">{d.serviceAccount}</span>
            </Fact>
            <Fact label="Pod IP">
              <span className="mono">{d.podIP || "—"}</span>
              {d.hostIP && d.hostIP !== d.podIP && <span className="muted"> on {d.hostIP}</span>}
            </Fact>
            <Fact label="QoS class">{d.qosClass || "—"}</Fact>
            <Fact label="Restart policy">{d.restartPolicy || "—"}</Fact>
            <Fact label="Created">{dateTime(d.createdAt) || "—"}</Fact>
            <Fact label="Started">{dateTime(d.startTime) || "—"}</Fact>
            {d.note && <Fact label="Note">{d.note}</Fact>}
          </dl>

          {d.conditions.length > 0 && (
            <>
              <h3 className="pod-subhead">Conditions</h3>
              <ul className="pod-conditions">
                {d.conditions.map((c) => (
                  <li key={c.type}>
                    <span className="mono">{c.type}</span>
                    <span className={`chip ${c.status === "True" ? "t-clean" : "t-muted"}`}>{c.status}</span>
                    {c.reason && <span className="muted">{c.reason}</span>}
                    {c.message && <span className="muted">{c.message}</span>}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {tab === "specs" && (
        <div className="pod-tab">
          {d.containers.map((c) => (
            <ContainerCard key={c.name} c={c} />
          ))}

          <h3 className="pod-subhead">Volumes</h3>
          {d.volumes.length === 0 ? (
            <p className="muted">No volumes mounted.</p>
          ) : (
            <ul className="pod-volumes">
              {d.volumes.map((v) => (
                <li key={v.name}>
                  <span className="mono">{v.name}</span>
                  <span className="chip t-muted">{v.kind}</span>
                  {v.source && <span className="mono muted">{v.source}</span>}
                  {v.readOnly && <span className="chip t-contained">read-only</span>}
                </li>
              ))}
            </ul>
          )}

          {Object.keys(d.labels).length > 0 && (
            <details className="pod-meta-block">
              <summary>Labels ({Object.keys(d.labels).length})</summary>
              <dl className="pod-meta-list mono">
                {Object.entries(d.labels).map(([k, v]) => (
                  <div key={k}>
                    <dt>{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
            </details>
          )}

          {annotations.length > 0 && (
            <details className="pod-meta-block">
              <summary>Annotations ({annotations.length})</summary>
              <dl className="pod-meta-list mono">
                {annotations.map(([k, v]) => (
                  <div key={k}>
                    <dt>{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
            </details>
          )}
        </div>
      )}

      {tab === "logs" && (
        <div className="pod-tab">
          <div className="log-tools">
            <label>
              Container
              <select
                className="input"
                value={selectedContainer}
                onChange={(e) => setContainer(e.target.value)}
                disabled={containers.length < 2}
              >
                {containers.map((c) => (
                  <option key={c.name} value={c.name}>{c.name}</option>
                ))}
              </select>
            </label>
            <label>
              Lines
              <select className="input" value={tail} onChange={(e) => setTail(Number(e.target.value))}>
                {[100, 200, 500, 1000].map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </label>
            <label className="check">
              <input type="checkbox" checked={timestamps} onChange={(e) => setTimestamps(e.target.checked)} />
              Timestamps
            </label>
            {hasRestarts && (
              <label className="check">
                <input type="checkbox" checked={previous} onChange={(e) => setPrevious(e.target.checked)} />
                Previous run
              </label>
            )}
            <button className="btn" onClick={() => setReload((n) => n + 1)} disabled={logBusy}>
              {logBusy ? "Loading…" : "Refresh"}
            </button>
          </div>

          {logError ? (
            <div className="empty">
              <strong>No logs available</strong>
              <p>{logError}</p>
            </div>
          ) : !logs ? (
            <div className="empty">{logBusy ? "Reading logs…" : "No log lines selected."}</div>
          ) : (
            <>
              <p className="log-caption">
                Last {logs.tailLines} lines · <span className="mono">{logs.container}</span>
                {logs.previous && " · previous run"}
              </p>
              <pre className="pod-logs" aria-live="polite">
                {logs.text.trim() || "No output yet."}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}
