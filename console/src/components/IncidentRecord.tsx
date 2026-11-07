import type { ReactNode } from "react";
import { useLive } from "../context";
import { countdown, dateTime, clock } from "../format";
import { useNow } from "../hooks";
import { incidentStatus, PHASES } from "../labels";
import { Empty, NoData, NoIncident } from "./Empty";
import { SeverityChip } from "./Status";

function Field({ label, children, empty }: { label: string; children?: ReactNode; empty?: boolean }) {
  return (
    <div className="field">
      <dt>{label}</dt>
      <dd>{empty ? <span className="pending">Not known yet</span> : children}</dd>
    </div>
  );
}

export function IncidentRecord() {
  const { snapshot, connection } = useLive();
  const now = useNow();
  const r = snapshot?.record ?? null;

  return (
    <section className="panel area-record" aria-labelledby="rec-h">
      <div className="panel-head">
        <h2 id="rec-h">Incident record</h2>
        <span className="aside">NIST SP 800-61 fields{r ? `, updated ${clock(r.updatedAt)}` : ""}</span>
      </div>
      {!snapshot ? (
        <NoData connection={connection} what="The incident record" />
      ) : !r ? (
        <NoIncident />
      ) : (
        <>
          <div className="record-title">
            <h3>{r.title}</h3>
            <span className="id mono">{r.id}</span>
          </div>
          <dl className="record" key={r.updatedAt}>
            <Field label="Status">
              <span className={`chip t-${incidentStatus(r.status).tone}`}>{incidentStatus(r.status).label}</span>{" "}
              {PHASES.find((p) => p.id === r.phase)?.label ?? r.phase} phase
            </Field>
            <Field label="Severity">
              <SeverityChip severity={r.severity} />
            </Field>
            <Field label="Detected" empty={!r.detectedAt}>
              {dateTime(r.detectedAt)}
              {r.reportedBy && <> by {r.reportedBy}</>}
            </Field>
            <Field label="Category" empty={r.categories.length === 0}>
              {r.categories.join(", ")}
            </Field>
            <Field label="Attack vector" empty={!r.vector}>
              {r.vector}
            </Field>
            <Field label="Affected systems" empty={r.affectedSystems.length === 0}>
              <ul>
                {r.affectedSystems.map((s) => (
                  <li key={s} className="mono">{s}</li>
                ))}
              </ul>
            </Field>
            {r.notificationDueAt && (
              <Field label="Client notice due">
                <span className="deadline">{countdown(r.notificationDueAt, now)}</span> ({dateTime(r.notificationDueAt)})
              </Field>
            )}
            <Field label="Actions taken" empty={r.actionsTaken.length === 0}>
              <ol>
                {r.actionsTaken.map((a, i) => (
                  <li key={i}>
                    {a.text}
                    <div className="act-meta">
                      {clock(a.ts)}, {a.by}
                    </div>
                  </li>
                ))}
              </ol>
            </Field>
            <Field label="Next steps" empty={r.nextSteps.length === 0}>
              <ol>
                {r.nextSteps.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ol>
            </Field>
          </dl>
        </>
      )}
      {snapshot && r && r.actionsTaken.length === 0 && r.affectedSystems.length === 0 && (
        <Empty title="Record opened">Fields fill in as agents and responders act.</Empty>
      )}
    </section>
  );
}
