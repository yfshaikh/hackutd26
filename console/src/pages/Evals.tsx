// WS-C: the evals page. Shows pass-rate per metric per scenario and a model comparison from
// GET /defender/evals, and lets you RUN the suite from here (POST /defender/evals/run, polling
// /defender/evals/status) instead of the command line.
import { useCallback, useEffect, useState } from "react";
import { errorText, evalsStatus, getEvals, runEvals } from "../api";
import { Empty } from "../components/Empty";
import type { EvalMetricTally, EvalsResults, EvalsRunStatus } from "../types";

// Short column headers for the nine metrics, in the canonical order.
const METRIC_LABEL: Record<string, string> = {
  time_to_detect: "Detect",
  time_to_contain: "Contain",
  persistence_removed: "Persistence",
  root_cause_addressed: "Root cause",
  policy_compliance: "Policy",
  no_collateral_damage: "No collateral",
  correct_scope: "Scope",
  valid_record: "Record",
  cost: "Cost",
};

const metricLabel = (name: string): string => METRIC_LABEL[name] ?? name.replace(/_/g, " ");

// A tally -> a pass-rate chip. graded = pass + fail (na is excluded from the ratio).
function cellTone(t: EvalMetricTally): { tone: string; text: string; label: string } {
  const graded = t.pass + t.fail;
  if (graded === 0) return { tone: "t-muted", text: "—", label: "not applicable" };
  const text = `${t.pass}/${graded}`;
  if (t.pass === graded) return { tone: "t-clean", text, label: `${text} passed` };
  if (t.pass === 0) return { tone: "t-exfil", text, label: `${text} passed` };
  return { tone: "t-invest", text, label: `${text} passed` };
}

const pct = (r: number) => `${Math.round(r * 100)}%`;
const secs = (n: number | null) => (n == null ? "—" : `${n.toFixed(1)}s`);

export function Evals() {
  const [state, setState] = useState<
    { kind: "loading" } | { kind: "error"; msg: string } | { kind: "ready"; data: EvalsResults | null }
  >({ kind: "loading" });
  const [run, setRun] = useState<EvalsRunStatus | null>(null);
  const [starting, setStarting] = useState(false);

  const load = useCallback(() => {
    getEvals()
      .then((data) => setState({ kind: "ready", data }))
      .catch((e) => setState({ kind: "error", msg: errorText(e) }));
  }, []);

  useEffect(() => { load(); }, [load]);

  // Also pick up a run already in flight (e.g. started from the CLI or another tab).
  useEffect(() => { evalsStatus().then(setRun).catch(() => {}); }, []);

  // While a run is in flight, poll its status; reload results when it finishes.
  useEffect(() => {
    if (!run?.running) return;
    const t = window.setInterval(async () => {
      try {
        const s = await evalsStatus();
        setRun(s);
        if (!s.running) { window.clearInterval(t); load(); }
      } catch { /* keep polling */ }
    }, 2000);
    return () => window.clearInterval(t);
  }, [run?.running, load]);

  const start = async () => {
    setStarting(true);
    try {
      setRun(await runEvals());
    } catch (e) {
      setRun({ running: false, done: 0, total: 0, current: null, startedAt: null, finishedAt: null, error: errorText(e) });
    } finally {
      setStarting(false);
    }
  };

  const running = !!run?.running;
  const runButton = (
    <button className="btn btn-primary" onClick={start} disabled={running || starting}>
      {running ? "Running…" : starting ? "Starting…" : "Run evals"}
    </button>
  );
  const banner =
    run && (running || run.error) ? (
      <div className={`eval-run${run.error ? " err" : ""}`} role="status">
        {run.error
          ? `Run failed: ${run.error}`
          : `Running the suite on the live cluster — scenario ${Math.min(run.done + 1, run.total || 1)} of ${run.total || "?"}${run.current ? ` · ${run.current}` : ""}…`}
      </div>
    ) : null;

  const data = state.kind === "ready" ? state.data : null;
  const aside = data
    ? `${new Date(data.generatedAt).toLocaleString()} · ${data.runsPerScenario} run(s) per scenario · ${data.models.length} model(s)`
    : "Measure the defender across every attack scenario";

  let body = null;
  if (state.kind === "loading") body = <Empty title="Loading eval results…" />;
  else if (state.kind === "error") body = <Empty title="Couldn't load eval results"><span>{state.msg}</span></Empty>;
  else if (!data)
    body = (
      <Empty title="No eval results yet">
        <span>Run the suite to measure the defender across every scenario. Each one runs for real on the cluster, so a full run takes a few minutes.</span>
      </Empty>
    );
  else body = <Results data={data} />;

  return (
    <main className="evals">
      <section className="panel">
        <div className="panel-head">
          <h2>Evaluations</h2>
          <span className="aside">{aside}</span>
          {runButton}
        </div>
        {banner && <div className="panel-body">{banner}</div>}
      </section>
      {body}
    </main>
  );
}

function Results({ data }: { data: EvalsResults }) {
  const { scenarios, summary } = data;
  const metricNames = summary.metricNames;
  return (
    <>
      <section className="panel">
        <div className="panel-head"><h2>Pass rate by scenario and metric</h2></div>
        <div className="panel-body evals-scroll">
          <table className="evals-grid">
            <thead>
              <tr>
                <th scope="col" className="evals-rowhead">Scenario</th>
                {metricNames.map((m) => <th scope="col" key={m} title={m}>{metricLabel(m)}</th>)}
              </tr>
            </thead>
            <tbody>
              {scenarios.map((s) => {
                const row = summary.byScenario[s.id];
                return (
                  <tr key={s.id}>
                    <th scope="row" className="evals-rowhead">
                      <span className="evals-sid">{s.id}</span> {s.name}
                      <span className="evals-rate">{row ? pct(row.passRate) : "—"}</span>
                    </th>
                    {metricNames.map((m) => {
                      const tally = row?.byMetric[m] ?? { pass: 0, fail: 0, na: 0 };
                      const c = cellTone(tally);
                      return (
                        <td key={m}>
                          <span className={`chip ${c.tone}`} aria-label={`${metricLabel(m)}: ${c.label}`}>{c.text}</span>
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head"><h2>Model comparison</h2><span className="aside">speed vs. accuracy</span></div>
        <div className="panel-body evals-scroll">
          <table className="evals-grid">
            <thead>
              <tr>
                <th scope="col" className="evals-rowhead">Model</th>
                <th scope="col">Pass rate</th>
                <th scope="col">Mean detect</th>
                <th scope="col">Mean contain</th>
                <th scope="col">Runs</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(summary.byModel).map(([model, m]) => (
                <tr key={model}>
                  <th scope="row" className="evals-rowhead evals-model">{model}</th>
                  <td>{pct(m.passRate)}</td>
                  <td>{secs(m.meanDetectSeconds)}</td>
                  <td>{secs(m.meanContainSeconds)}</td>
                  <td>{m.runs}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
