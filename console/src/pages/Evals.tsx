// WS-C: the evals page. Read-only. Shows pass-rate per metric per scenario and a
// model comparison, from GET /defender/evals. Renders only what the endpoint returns.
import { useEffect, useState } from "react";
import { errorText, getEvals } from "../api";
import { Empty } from "../components/Empty";
import type { EvalMetricTally, EvalsResults } from "../types";

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

function metricLabel(name: string): string {
  return METRIC_LABEL[name] ?? name.replace(/_/g, " ");
}

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

  useEffect(() => {
    let live = true;
    getEvals()
      .then((data) => live && setState({ kind: "ready", data }))
      .catch((e) => live && setState({ kind: "error", msg: errorText(e) }));
    return () => {
      live = false;
    };
  }, []);

  if (state.kind === "loading") return <Empty title="Loading eval results…" />;
  if (state.kind === "error")
    return (
      <Empty title="Couldn't load eval results">
        <span>{state.msg}</span>
      </Empty>
    );
  if (!state.data)
    return (
      <Empty title="No eval results yet">
        <span>
          Run the suite to measure the defender across every scenario:
        </span>
        <code>uv run python -m evals --runs N</code>
      </Empty>
    );

  const { generatedAt, models, runsPerScenario, scenarios, summary } = state.data;
  const metricNames = summary.metricNames;

  return (
    <main className="evals">
      <section className="panel">
        <div className="panel-head">
          <h2>Evaluations</h2>
          <span className="aside">
            {new Date(generatedAt).toLocaleString()} · {runsPerScenario} run(s) per scenario ·{" "}
            {models.length} model(s)
          </span>
        </div>
        <div className="panel-body">
          <p className="hint" style={{ padding: 0 }}>
            Every scenario runs for real on the cluster and is scored on nine metrics. A cell shows how
            many runs passed out of the runs where the metric applied.
          </p>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Pass rate by scenario and metric</h2>
        </div>
        <div className="panel-body evals-scroll">
          <table className="evals-grid">
            <thead>
              <tr>
                <th scope="col" className="evals-rowhead">Scenario</th>
                {metricNames.map((m) => (
                  <th scope="col" key={m} title={m}>{metricLabel(m)}</th>
                ))}
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
                          <span className={`chip ${c.tone}`} aria-label={`${metricLabel(m)}: ${c.label}`}>
                            {c.text}
                          </span>
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
        <div className="panel-head">
          <h2>Model comparison</h2>
          <span className="aside">speed vs. accuracy</span>
        </div>
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
    </main>
  );
}
