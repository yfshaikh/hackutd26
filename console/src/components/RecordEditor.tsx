import { useState, type FormEvent } from "react";
import { errorText, patchRecord } from "../api";
import { fromLocalInput, toLocalInput } from "../format";
import { INCIDENT_STATUS, PHASES, SEVERITY } from "../labels";
import type {
  IncidentPhase,
  IncidentRecord,
  IncidentRecordPatch,
  IncidentStatus,
  NotificationDeadline,
  Severity,
} from "../types";

const PHASE_OPTIONS: IncidentPhase[] = ["preparation", ...PHASES.map((p) => p.id)];
const DEADLINE_STATUS = ["upcoming", "due", "met", "overdue"] as const;

const lines = (v: string) => v.split("\n").map((x) => x.trim()).filter(Boolean);
const csv = (v: string) => v.split(",").map((x) => x.trim()).filter(Boolean);

function serializeDeadlines(ds: NotificationDeadline[]): string {
  return ds
    .map((d) => [d.label, d.dueAt, d.jurisdiction ?? "", d.status].join(" | "))
    .join("\n");
}

function parseDeadlines(text: string): NotificationDeadline[] {
  return lines(text).map((line, i) => {
    const [label, dueAt, jurisdiction, status] = line.split("|").map((x) => x.trim());
    if (!label || !dueAt) {
      throw new Error(`Deadline line ${i + 1}: use "Label | ISO timestamp | jurisdiction | status"`);
    }
    const d = new Date(dueAt);
    if (Number.isNaN(d.getTime())) throw new Error(`Deadline line ${i + 1}: invalid date "${dueAt}"`);
    const s = (status || "upcoming") as NotificationDeadline["status"];
    if (!DEADLINE_STATUS.includes(s)) {
      throw new Error(`Deadline line ${i + 1}: status must be one of ${DEADLINE_STATUS.join(", ")}`);
    }
    return { label, dueAt: d.toISOString(), jurisdiction: jurisdiction || undefined, status: s };
  });
}

/**
 * Full NIST SP 800-61 record editor. The defender keeps the record current, but
 * a human incident commander can fill in the fields a machine cannot infer:
 * impact, root cause, evidence, notified parties, lessons learned and deadlines.
 */
export function RecordEditor({
  record,
  onSaved,
  onCancel,
}: {
  record: IncidentRecord;
  onSaved: (r: IncidentRecord) => void;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState(record.title);
  const [status, setStatus] = useState<IncidentStatus>(record.status);
  const [phase, setPhase] = useState<IncidentPhase>(record.phase);
  const [severity, setSeverity] = useState<Severity>(record.severity);
  const [summary, setSummary] = useState(record.summary ?? "");
  const [impact, setImpact] = useState(record.impact ?? "");
  const [rootCause, setRootCause] = useState(record.rootCause ?? "");
  const [vector, setVector] = useState(record.vector ?? "");
  const [commander, setCommander] = useState(record.incidentCommander ?? "");
  const [detectedAt, setDetectedAt] = useState(toLocalInput(record.detectedAt));
  const [notificationDueAt, setNotificationDueAt] = useState(toLocalInput(record.notificationDueAt));
  const [closedAt, setClosedAt] = useState(toLocalInput(record.closedAt));
  const [categories, setCategories] = useState(record.categories.join(", "));
  const [affected, setAffected] = useState(record.affectedSystems.join(", "));
  const [nextSteps, setNextSteps] = useState(record.nextSteps.join("\n"));
  const [evidence, setEvidence] = useState((record.evidence ?? []).join("\n"));
  const [containment, setContainment] = useState((record.containmentMeasures ?? []).join("\n"));
  const [parties, setParties] = useState((record.notifiedParties ?? []).join(", "));
  const [lessons, setLessons] = useState(record.lessonsLearned ?? "");
  const [deadlines, setDeadlines] = useState(serializeDeadlines(record.notificationDeadlines ?? []));

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    setOk(null);
    try {
      const body = {
        title: title.trim(),
        status,
        phase,
        severity,
        summary: summary.trim(),
        impact: impact.trim(),
        rootCause: rootCause.trim(),
        vector: vector.trim(),
        incidentCommander: commander.trim(),
        detectedAt: fromLocalInput(detectedAt) ?? null,
        notificationDueAt: fromLocalInput(notificationDueAt) ?? null,
        closedAt: fromLocalInput(closedAt) ?? null,
        categories: csv(categories),
        affectedSystems: csv(affected),
        nextSteps: lines(nextSteps),
        evidence: lines(evidence),
        containmentMeasures: lines(containment),
        notifiedParties: csv(parties),
        lessonsLearned: lessons.trim(),
        notificationDeadlines: parseDeadlines(deadlines),
      };
      const updated = await patchRecord(body as IncidentRecordPatch);
      onSaved(updated);
      setOk("Record saved.");
    } catch (e2) {
      setErr(errorText(e2));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="record-editor" onSubmit={submit}>
      <div className="editor-grid">
        <label>
          Title
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} required />
        </label>
        <label>
          Incident commander
          <input className="input" value={commander} onChange={(e) => setCommander(e.target.value)} placeholder="Name or team" />
        </label>
        <label>
          Status
          <select className="input" value={status} onChange={(e) => setStatus(e.target.value as IncidentStatus)}>
            {(Object.keys(INCIDENT_STATUS) as IncidentStatus[]).map((s) => (
              <option key={s} value={s}>{INCIDENT_STATUS[s].label}</option>
            ))}
          </select>
        </label>
        <label>
          NIST phase
          <select className="input" value={phase} onChange={(e) => setPhase(e.target.value as IncidentPhase)}>
            {PHASE_OPTIONS.map((p) => (
              <option key={p} value={p}>{p.replace("-", " ")}</option>
            ))}
          </select>
        </label>
        <label>
          Severity
          <select className="input" value={severity} onChange={(e) => setSeverity(e.target.value as Severity)}>
            {(Object.keys(SEVERITY) as Severity[]).map((s) => (
              <option key={s} value={s}>{SEVERITY[s].label}</option>
            ))}
          </select>
        </label>
        <label>
          Detected at
          <input className="input" type="datetime-local" value={detectedAt} onChange={(e) => setDetectedAt(e.target.value)} />
        </label>
        <label>
          Notification due
          <input className="input" type="datetime-local" value={notificationDueAt} onChange={(e) => setNotificationDueAt(e.target.value)} />
        </label>
        <label>
          Closed at
          <input className="input" type="datetime-local" value={closedAt} onChange={(e) => setClosedAt(e.target.value)} />
        </label>
        <label className="wide">
          Summary
          <textarea className="input" rows={2} value={summary} onChange={(e) => setSummary(e.target.value)} placeholder="What happened, in two sentences." />
        </label>
        <label className="wide">
          Business impact
          <textarea className="input" rows={2} value={impact} onChange={(e) => setImpact(e.target.value)} placeholder="Client data, model IP, billable work, regulatory exposure." />
        </label>
        <label className="wide">
          Root cause
          <textarea className="input" rows={2} value={rootCause} onChange={(e) => setRootCause(e.target.value)} placeholder="Initial access and the condition that allowed it." />
        </label>
        <label className="wide">
          Attack vector
          <input className="input" value={vector} onChange={(e) => setVector(e.target.value)} placeholder="e.g. over-privileged notebook service-account token" />
        </label>
        <label>
          Categories (comma-separated)
          <input className="input" value={categories} onChange={(e) => setCategories(e.target.value)} placeholder="unauthorized-access, data-exfiltration" />
        </label>
        <label>
          Affected systems (comma-separated)
          <input className="input" value={affected} onChange={(e) => setAffected(e.target.value)} placeholder="pvc/model-weights, pod/notebook" />
        </label>
        <label className="wide">
          Evidence (one per line)
          <textarea className="input" rows={3} value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="Log lines, object names, hashes." />
        </label>
        <label className="wide">
          Containment measures (one per line)
          <textarea className="input" rows={3} value={containment} onChange={(e) => setContainment(e.target.value)} placeholder="What was isolated, deleted or revoked." />
        </label>
        <label className="wide">
          Next steps (one per line)
          <textarea className="input" rows={3} value={nextSteps} onChange={(e) => setNextSteps(e.target.value)} />
        </label>
        <label>
          Notified parties (comma-separated)
          <input className="input" value={parties} onChange={(e) => setParties(e.target.value)} placeholder="Client GC, cyber insurer, regulator" />
        </label>
        <label>
          Lessons learned
          <input className="input" value={lessons} onChange={(e) => setLessons(e.target.value)} placeholder="What changes after this incident" />
        </label>
        <label className="wide">
          Breach deadlines — one per line: Label | ISO timestamp | jurisdiction | status
          <textarea
            className="input mono"
            rows={3}
            value={deadlines}
            onChange={(e) => setDeadlines(e.target.value)}
            placeholder={"GDPR 72h | 2026-11-10T14:00:00Z | EU | upcoming\nClient contract | 2026-11-09T14:00:00Z | NY | upcoming"}
          />
        </label>
      </div>
      {err && <div className="notice t-exfil" role="alert">{err}</div>}
      {ok && <div className="notice t-clean" role="status">{ok}</div>}
      <div className="editor-actions">
        <button className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : "Save record"}</button>
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>Close editor</button>
      </div>
    </form>
  );
}
