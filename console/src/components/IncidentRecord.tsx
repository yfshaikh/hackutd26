import { useState, type ReactNode } from "react";
import { useLive, useSession } from "../context";
import { clock, dateTime } from "../format";
import { canEditRecord, incidentStatus, PHASES } from "../labels";
import type { IncidentRecord as IncidentRecordData, RecordAction } from "../types";
import { NoData, NoIncident } from "./Empty";
import { BreachCountdown } from "./BreachCountdown";
import { RecordEditor } from "./RecordEditor";
import { SeverityChip, VerdictChip } from "./Status";

// The NIST SP 800-61 record laid out as a case file, in the order a partner reads it:
// what happened → how we know → what we did → what's left. Fields only a human fills in
// (lessons learned, notified parties) live in their own clearly-labelled review section
// instead of showing up as a wall of "Not known yet".

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="case-sec">
      <header className="case-sec-head">
        <h3>{title}</h3>
        {hint && <span className="aside">{hint}</span>}
      </header>
      {children}
    </section>
  );
}

function Pending({ children }: { children: ReactNode }) {
  return <p className="case-pending">{children}</p>;
}

/** Phase stepper: where in the NIST lifecycle the incident is. */
function Phases({ phase }: { phase: string }) {
  const at = PHASES.findIndex((p) => p.id === phase);
  return (
    <ol className="case-phases" aria-label="Response phase">
      {PHASES.map((p, i) => (
        <li key={p.id} className={i < at ? "done" : i === at ? "now" : undefined} aria-current={i === at ? "step" : undefined}>
          {p.label}
        </li>
      ))}
    </ol>
  );
}

/** "quarantine_pod(name=x) — quarantined x (approved by Dana)" → call + outcome. */
function splitAction(text: string): { call?: string; outcome: string } {
  const m = text.match(/^([a-z_]+\([^)]*\))\s+—\s+(.*)$/s);
  return m ? { call: m[1], outcome: m[2] } : { outcome: text };
}

function Actions({ actions }: { actions: RecordAction[] }) {
  if (actions.length === 0) return <Pending>No containment actions yet. The Advisor acts once the Investigator hands off.</Pending>;
  return (
    <ol className="case-actions">
      {actions.map((a, i) => {
        const { call, outcome } = splitAction(a.text);
        return (
          <li key={`${a.ts}-${i}`}>
            <time className="mono" dateTime={a.ts}>{clock(a.ts)}</time>
            <div>
              {call && <code className="case-call">{call}</code>}
              <span className="case-outcome">{outcome}</span>
              <span className="case-by">{a.by}</span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export function IncidentRecord({
  record: supplied,
  readOnly = false,
  aside,
}: {
  /** Show this record instead of the live one (e.g. an archived incident). */
  record?: IncidentRecordData | null;
  /** Archived records are read-only: hide the editor and PDF controls. */
  readOnly?: boolean;
  /** Extra side-rail content (the live scope board). */
  aside?: ReactNode;
} = {}) {
  const { snapshot, connection, apply } = useLive();
  const { user } = useSession();
  const [editing, setEditing] = useState(false);
  const r = supplied === undefined ? snapshot?.record ?? null : supplied;
  const canEdit = !readOnly && canEditRecord(user?.role);

  if (!snapshot && supplied === undefined) return <section className="panel"><NoData connection={connection} what="The incident record" /></section>;
  if (!r) return <section className="panel"><NoIncident /></section>;

  const st = incidentStatus(r.status);
  const hyps = [...(r.hypotheses ?? [])].sort((a, b) => order(a.verdict) - order(b.verdict));
  const open = r.status !== "resolved";
  const fillLater = open ? "The Advisor writes this when containment finishes." : "Not recorded.";
  const review = [r.lessonsLearned, r.incidentCommander, r.closedAt].some(Boolean) || (r.notifiedParties ?? []).length > 0;

  return (
    <div className="case">
      <section className="panel case-head">
        <div className="print-only print-head">
          <strong>NMC operator console · Client: {snapshot?.firm ?? "Client incident response"}</strong>
          <span>NIST SP 800-61 incident record · exported {dateTime(new Date().toISOString())}</span>
        </div>
        <div className="case-title">
          <div>
            <h2>{r.title}</h2>
            <p className="case-meta">
              <span className="mono">{r.id}</span>
              {r.detectedAt && <> · detected {dateTime(r.detectedAt)}{r.reportedBy && <> by {r.reportedBy}</>}</>}
              {" "}· updated {clock(r.updatedAt)}
            </p>
          </div>
          <div className="case-tools no-print">
            {canEdit && (
              <button className="btn btn-ghost" onClick={() => setEditing((v) => !v)}>
                {editing ? "Close editor" : "Edit record"}
              </button>
            )}
            {!editing && !readOnly && (
              <button className="btn" onClick={() => window.print()} title="Print or save as PDF">Export PDF</button>
            )}
          </div>
        </div>
        <div className="case-status">
          <span className={`chip t-${st.tone}`}>{st.label}</span>
          <SeverityChip severity={r.severity} />
          {r.categories.map((c) => <span key={c} className="tag">{c}</span>)}
          <Phases phase={r.phase} />
        </div>
      </section>

      {editing ? (
        <section className="panel">
          <RecordEditor record={r} onSaved={(u) => apply({ type: "record", record: u })} onCancel={() => setEditing(false)} />
        </section>
      ) : (
        <div className={`case-grid${aside ? "" : " no-aside"}`}>
          <div className="panel case-main">
            <Section title="What happened">
              {r.summary ? <p className="case-prose">{r.summary}</p> : <Pending>{fillLater}</Pending>}
              <dl className="case-pair">
                <div><dt>Business impact</dt><dd>{r.impact || <span className="case-pending">{fillLater}</span>}</dd></div>
                <div><dt>Root cause</dt><dd>{r.rootCause || r.vector || <span className="case-pending">{fillLater}</span>}</dd></div>
              </dl>
            </Section>

            <Section title="How we know" hint="the Investigator's hypotheses and the evidence behind each">
              {hyps.length === 0 ? (
                <Pending>No hypotheses filed yet. The Investigator files one per candidate explanation as it reads the cluster.</Pending>
              ) : (
                <ul className="case-hyps">
                  {hyps.map((h) => (
                    <li key={h.name} className={`v-${h.verdict}`}>
                      <div className="case-hyp-top"><strong>{h.name}</strong><VerdictChip verdict={h.verdict} /></div>
                      {h.evidence && <p>{h.evidence}</p>}
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            <Section title="What we did" hint={`${r.actionsTaken.length} action${r.actionsTaken.length === 1 ? "" : "s"}`}>
              <Actions actions={r.actionsTaken} />
            </Section>

            <Section title="Post-incident review" hint="filled in by the incident commander">
              {review ? (
                <dl className="case-pair">
                  <div><dt>Commander</dt><dd>{r.incidentCommander || "—"}</dd></div>
                  <div><dt>Notified</dt><dd>{(r.notifiedParties ?? []).join(", ") || "—"}</dd></div>
                  <div><dt>Lessons learned</dt><dd>{r.lessonsLearned || "—"}</dd></div>
                  <div><dt>Closed</dt><dd>{r.closedAt ? dateTime(r.closedAt) : "—"}</dd></div>
                </dl>
              ) : (
                <Pending>
                  Not started. After recovery, a person records who led the response, who was notified and
                  what to change{canEdit ? " — use Edit record" : ""}.
                </Pending>
              )}
            </Section>
          </div>

          <aside className="case-side">
            <section className="panel case-rail">
              <header className="case-sec-head"><h3>Client notification</h3></header>
              <p className="case-explain">
                Once client data leaves the cluster, the firm has 72 hours to notify affected clients
                (state breach-notification law). The clock starts automatically on confirmed exfiltration.
              </p>
              <BreachCountdown deadlines={r.notificationDeadlines ?? []} fallbackDueAt={r.notificationDueAt} />
            </section>

            <section className="panel case-rail">
              <header className="case-sec-head"><h3>Open items</h3></header>
              {r.nextSteps.length === 0 ? (
                <Pending>Nothing outstanding.</Pending>
              ) : (
                <ol className="case-steps">{r.nextSteps.map((s, i) => <li key={i}>{s}</li>)}</ol>
              )}
            </section>

            {aside}

            <section className="panel case-rail">
              <header className="case-sec-head"><h3>Facts</h3></header>
              <dl className="case-facts">
                <dt>Attack vector</dt><dd>{r.vector || "Not identified yet"}</dd>
                <dt>Affected systems</dt>
                <dd>{r.affectedSystems.length ? r.affectedSystems.map((s) => <code key={s} className="case-call">{s}</code>) : "None confirmed yet"}</dd>
                {(r.evidence ?? []).length > 0 && <><dt>Evidence</dt><dd><ul>{r.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul></dd></>}
              </dl>
            </section>
          </aside>
        </div>
      )}
    </div>
  );
}

const order = (v: string) => ["confirmed", "likely", "possible", "ruled_out"].indexOf(v);
