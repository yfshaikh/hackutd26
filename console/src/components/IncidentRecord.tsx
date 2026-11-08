import { useState, type ReactNode } from "react";
import { useLive, useSession } from "../context";
import { dateTime, clock } from "../format";
import { canEditRecord, incidentStatus, PHASES } from "../labels";
import type { IncidentRecord as IncidentRecordData } from "../types";
import { Empty, NoData, NoIncident } from "./Empty";
import { BreachCountdown } from "./BreachCountdown";
import { RecordEditor } from "./RecordEditor";
import { SeverityChip } from "./Status";

function Field({ label, children, empty }: { label: string; children?: ReactNode; empty?: boolean }) {
  return (
    <div className="field">
      <dt>{label}</dt>
      <dd>{empty ? <span className="pending">Not known yet</span> : children}</dd>
    </div>
  );
}

function List({ items }: { items: string[] }) {
  return (
    <ul>
      {items.map((s, i) => (
        <li key={`${s}-${i}`} className={s.includes("/") || s.includes(":") ? "mono" : undefined}>{s}</li>
      ))}
    </ul>
  );
}

export function IncidentRecord({
  record: supplied,
  readOnly = false,
  showActions = true,
}: {
  /** Show this record instead of the live one (e.g. an archived incident). */
  record?: IncidentRecordData | null;
  /** Archived records are read-only: hide the editor and PDF controls. */
  readOnly?: boolean;
  /** The Incident page renders actions in its own prominent panel, so hide the field here. */
  showActions?: boolean;
} = {}) {
  const { snapshot, connection, apply } = useLive();
  const { user } = useSession();
  const [editing, setEditing] = useState(false);
  const live = snapshot?.record ?? null;
  const r = supplied === undefined ? live : supplied;
  const canEdit = !readOnly && canEditRecord(user?.role);

  return (
    <section className="panel" aria-labelledby="rec-h">
      <div className="panel-head">
        <h2 id="rec-h">Incident record</h2>
        <div className="panel-tools">
          <span className="aside">NIST SP 800-61{r ? `, updated ${clock(r.updatedAt)}` : ""}</span>
          {r && canEdit && (
            <button className="btn btn-ghost no-print" onClick={() => setEditing((v) => !v)}>
              {editing ? "Close editor" : "Edit record"}
            </button>
          )}
          {r && !editing && !readOnly && (
            <button className="btn no-print" onClick={() => window.print()} title="Print or save as PDF">
              Export PDF
            </button>
          )}
        </div>
      </div>

      {!snapshot && supplied === undefined ? (
        <NoData connection={connection} what="The incident record" />
      ) : !r ? (
        <NoIncident />
      ) : editing ? (
        <RecordEditor
          record={r}
          onSaved={(updated) => apply({ type: "record", record: updated })}
          onCancel={() => setEditing(false)}
        />
      ) : (
        <>
          <div className="print-only print-head">
            <strong>NMC operator console · Client: {snapshot?.firm ?? "Client incident response"}</strong>
            <span>NIST SP 800-61 incident record · exported {dateTime(new Date().toISOString())}</span>
          </div>
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
            <Field label="Commander" empty={!r.incidentCommander}>
              {r.incidentCommander}
            </Field>
            <Field label="Detected" empty={!r.detectedAt}>
              {dateTime(r.detectedAt)}
              {r.reportedBy && <> by {r.reportedBy}</>}
            </Field>
            <Field label="Summary" empty={!r.summary}>
              {r.summary}
            </Field>
            <Field label="Category" empty={r.categories.length === 0}>
              {r.categories.join(", ")}
            </Field>
            <Field label="Attack vector" empty={!r.vector}>
              {r.vector}
            </Field>
            <Field label="Affected systems" empty={r.affectedSystems.length === 0}>
              <List items={r.affectedSystems} />
            </Field>
            <Field label="Business impact" empty={!r.impact}>
              {r.impact}
            </Field>
            <Field label="Root cause" empty={!r.rootCause}>
              {r.rootCause}
            </Field>
            <Field label="Evidence" empty={(r.evidence ?? []).length === 0}>
              <List items={r.evidence ?? []} />
            </Field>
            <Field label="Containment" empty={(r.containmentMeasures ?? []).length === 0}>
              <List items={r.containmentMeasures ?? []} />
            </Field>
            <div className="field field-wide">
              <dt>Breach deadlines</dt>
              <dd>
                <BreachCountdown
                  deadlines={r.notificationDeadlines ?? []}
                  fallbackDueAt={r.notificationDueAt}
                />
              </dd>
            </div>
            {showActions && (
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
            )}
            <Field label="Next steps" empty={r.nextSteps.length === 0}>
              <ol>
                {r.nextSteps.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ol>
            </Field>
            <Field label="Notified" empty={(r.notifiedParties ?? []).length === 0}>
              {(r.notifiedParties ?? []).join(", ")}
            </Field>
            <Field label="Lessons learned" empty={!r.lessonsLearned}>
              {r.lessonsLearned}
            </Field>
            <Field label="Closed" empty={!r.closedAt}>
              {dateTime(r.closedAt)}
            </Field>
          </dl>
          <p className="record-foot no-print">
            <strong>Survives a compromised cluster.</strong> This record and the approval path run
            in the operator console off the attacked box; wiping the cluster cannot erase them.
          </p>
        </>
      )}
      {snapshot && r && !editing && !readOnly && r.actionsTaken.length === 0 && r.affectedSystems.length === 0 && (
        <Empty title="Record opened">Fields fill in as agents and responders act.</Empty>
      )}
    </section>
  );
}
