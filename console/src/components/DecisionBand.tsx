// The one place that always answers "what do I do now?".
// If a human decision is pending it takes over in hazard yellow with Approve / Deny.

import { useState } from "react";
import { API_URL, approve, deny, errorText } from "../api";
import { useLive, useSession } from "../context";
import { ago, clock } from "../format";
import { useNow } from "../hooks";
import { canAct } from "../labels";
import { Link } from "../router";
import type { Approval } from "../types";

function ApprovalCard({ a }: { a: Approval }) {
  const { apply } = useLive();
  const { user } = useSession();
  const now = useNow();
  const [busy, setBusy] = useState<"approve" | "deny" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const allowed = canAct(user?.role);

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
    <article className="approval" aria-label={`Approval needed: ${a.action}`}>
      <h3>{a.action}</h3>
      <p className="why">{a.rationale}</p>
      <p className="policy">Needs a human: {a.policyReason}</p>
      <p className="meta">
        If approved: {a.impact} Asked by {a.requestedBy}, {ago(a.requestedAt, now)}.
      </p>
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
          <span className="readonly">Viewers can't decide. Ask a responder.</span>
        )}
      </div>
      {err && <p className="err" role="alert">{err}</p>}
    </article>
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
  const stale = connection !== "live";

  if (pending.length > 0) {
    return (
      <section className="band band-hazard" aria-live="assertive">
        <div className="band-head">
          <span className="band-title">
            {pending.length === 1 ? "1 action is waiting for your decision" : `${pending.length} actions are waiting for your decision`}
          </span>
          <span className="band-sub">Agents have already done what they could on their own.</span>
        </div>
        <div className="approvals">
          {pending.map((a) => (
            <ApprovalCard key={a.id} a={a} />
          ))}
        </div>
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
      <span className="band-title">{stale ? "Connection lost. Showing the last known state." : title}</span>
      <span className="band-sub">{stale ? <>Reconnecting to <code>{API_URL}</code>…</> : sub}</span>
    </section>
  );
}
