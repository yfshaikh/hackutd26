// The one place that always answers "what do I do now?".
// If a human decision is pending it takes over in hazard yellow with Approve / Deny.

import { useState } from "react";
import { API_URL, approve, deny, errorText } from "../api";
import { useLive, useSession } from "../context";
import { ago, clock } from "../format";
import { useNow } from "../hooks";
import { canAct, RISK } from "../labels";
import { Link } from "../router";
import type { Approval } from "../types";
import { PhaseTrack } from "./TopBar";

function ApprovalCard({ a, first }: { a: Approval; first: boolean }) {
  const { apply } = useLive();
  const { user } = useSession();
  const now = useNow();
  const [busy, setBusy] = useState<"approve" | "deny" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(first);
  const allowed = canAct(user?.role);
  const risk = a.risk ? RISK[a.risk] : null;

  const decide = async (kind: "approve" | "deny") => {
    setBusy(kind);
    setErr(null);
    try {
      const updated = await (kind === "approve" ? approve(a.id) : deny(a.id));
      apply({ type: "approval", approval: updated });
    } catch (e) {
      setErr(`${kind === "approve" ? "Approve" : "Deny"} did not go through: ${errorText(e)}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <li className={`approval${open ? " open" : ""}`} aria-label={`Approval needed: ${a.action}`}>
      <button className="approval-row" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {typeof a.rank === "number" && <span className="rank" title="Ranked remediation step">{a.rank}</span>}
        <span className="approval-action mono">{a.action}</span>
        {risk && <span className={`chip t-${risk.tone}`}>{risk.label} risk</span>}
        <span className="approval-ago">{ago(a.requestedAt, now)}</span>
        <span className="chev" aria-hidden />
      </button>
      <div className="actions">
        {allowed ? (
          <>
            <button className="btn btn-approve" disabled={busy !== null} onClick={() => decide("approve")}>
              {busy === "approve" ? "Approving…" : "Approve"}
            </button>
            <button className="btn btn-deny" disabled={busy !== null} onClick={() => decide("deny")}>
              {busy === "deny" ? "Denying…" : "Deny"}
            </button>
          </>
        ) : (
          <span className="readonly">{user?.role === "operator" ? "Operators can't approve" : "Read only"}</span>
        )}
      </div>
      {open && (
        <dl className="approval-detail">
          <dt>Why</dt><dd>{a.rationale}</dd>
          <dt>Needs a human</dt><dd>{a.policyReason}</dd>
          <dt>If approved</dt><dd>{a.impact}</dd>
          <dt>Asked by</dt>
          <dd>
            {a.requestedBy}
            {a.runbookRef && <> · <span className="mono">{a.runbookRef}</span></>}
            {a.reversible !== undefined && <> · {a.reversible ? "reversible" : "not reversible"}</>}
            {a.target && <> · <span className="mono">{a.target}</span></>}
          </dd>
        </dl>
      )}
      {err && <p className="err" role="alert">{err}</p>}
    </li>
  );
}

export function DecisionBand() {
  const { connection, snapshot } = useLive();

  if (!snapshot) {
    return (
      <section className={`band band-calm ${connection === "connecting" ? "t-muted" : "t-exfil"}`} aria-live="polite">
        <span className="band-title">
          {connection === "connecting" ? "Connecting to the command center…" : "Not connected to the command center"}
        </span>
        <span className="band-sub">
          Trying <code>{API_URL}</code>. Nothing below is shown until it answers. Retrying automatically.
        </span>
      </section>
    );
  }

  const pending = snapshot.approvals.filter((a) => a.status === "pending");
  const ranked = pending.some((a) => typeof a.rank === "number");
  const ordered = ranked
    ? pending
        .slice()
        .sort((a, b) => (a.rank ?? Number.MAX_SAFE_INTEGER) - (b.rank ?? Number.MAX_SAFE_INTEGER)
          || a.requestedAt.localeCompare(b.requestedAt))
    : pending;
  const stale = connection !== "live";

  if (pending.length > 0) {
    return (
      <section className="band band-hazard" aria-live="assertive">
        <div className="band-head">
          <span className="band-pulse" aria-hidden />
          <span className="band-title">
            {pending.length === 1 ? "1 decision needs you" : `${pending.length} decisions need you`}
          </span>
          <span className="band-sub">
            {ranked ? "Ranked by the runbook, do #1 first. Click a step for the reasoning." : "Agents already did what they could alone."}
          </span>
          {snapshot.record && <PhaseTrack phase={snapshot.record.phase} />}
        </div>
        <ol className="approvals">
          {ordered.map((a, i) => (
            <ApprovalCard key={a.id} a={a} first={i === 0} />
          ))}
        </ol>
      </section>
    );
  }

  const r = snapshot.record;
  let tone = "t-clean";
  let title = "All clear";
  let sub = <>No incidents yet. Launch an attack from the <Link href="/attack">attack panel</Link> to start one.</>;
  if (r && r.status === "open") {
    tone = "t-invest";
    title = "Agents are responding. Nothing needs you right now.";
    sub = <>{r.nextSteps[0] ? `Next: ${r.nextSteps[0]}` : "Watch the timeline; decisions will appear here."}</>;
  } else if (r && r.status === "contained") {
    tone = "t-clean";
    title = "Contained. Nothing needs you right now.";
    sub = <>{r.nextSteps[0] ? `Next: ${r.nextSteps[0]}` : "Review the incident record."}</>;
  } else if (r && r.status === "resolved") {
    title = "Incident resolved";
    sub = <>Review the incident record. Updated {clock(r.updatedAt)}.</>;
  }

  return (
    <section className={`band band-calm ${stale ? "t-invest" : tone}`} aria-live="polite">
      <span className="band-dot" aria-hidden />
      <span className="band-title">{stale ? "Connection lost. Showing the last known state." : title}</span>
      <span className="band-sub">{stale ? <>Reconnecting to <code>{API_URL}</code>…</> : sub}</span>
      {r && <PhaseTrack phase={r.phase} />}
    </section>
  );
}
