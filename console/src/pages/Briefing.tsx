// The partners' front door: where things stand in plain English, what needs their decision,
// the legal clock, what's affected, and the war room to coordinate in. The Command center stays
// the NMC operators' technical view; this page never shows pods, tool calls or CVE ids.

import { useState } from "react";
import { approve, deny, errorText } from "../api";
import { BreachCountdown } from "../components/BreachCountdown";
import { Chat } from "../components/Chat";
import { useLive, useSession } from "../context";
import { ago, clock } from "../format";
import { useNow } from "../hooks";
import { canAct } from "../labels";
import { ASSET_PLAIN, headline, plainAction, plainAssetDescription, plainUpdate } from "../plain";
import { Link } from "../router";
import type { Approval } from "../types";

function Decision({ a }: { a: Approval }) {
  const { apply } = useLive();
  const { user } = useSession();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const act = async (kind: "approve" | "deny") => {
    setBusy(true);
    setErr(null);
    try {
      apply({ type: "approval", approval: await (kind === "approve" ? approve(a.id) : deny(a.id)) });
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <li className="brief-decision">
      <div>
        <strong>{plainAction(a)}</strong>
        <p><span className="brief-k">What this means for the firm:</span> {a.impact}</p>
        <p className="brief-sub">Asked {clock(a.requestedAt)} by the response team</p>
      </div>
      {canAct(user?.role) ? (
        <div className="brief-actions">
          <button className="btn btn-primary" disabled={busy} onClick={() => act("approve")}>Approve</button>
          <button className="btn" disabled={busy} onClick={() => act("deny")}>Deny</button>
        </div>
      ) : (
        <p className="brief-sub">An approver needs to decide this.</p>
      )}
      {err && <p className="chat-err" role="alert">{err}</p>}
    </li>
  );
}

export function Briefing() {
  const { snapshot } = useLive();
  const now = useNow(30_000);
  if (!snapshot) return <main className="page brief"><p className="hint">Connecting…</p></main>;

  const r = snapshot.record;
  const h = headline(snapshot);
  const pending = snapshot.approvals.filter((a) => a.status === "pending");
  const updates = snapshot.timeline
    .map((e) => ({ e, text: plainUpdate(e) }))
    .filter((u): u is { e: typeof u.e; text: string } => !!u.text)
    .sort((a, b) => b.e.ts.localeCompare(a.e.ts))
    .slice(0, 12);
  const hasClock = !!r && ((r.notificationDeadlines ?? []).length > 0 || !!r.notificationDueAt);

  return (
    <main className="brief">
      <div className="brief-main">
        <section className={`brief-head t-${h.tone}`} aria-live="polite">
          <h1>{h.title}</h1>
          <p>
            {r ? `Detected ${ago(r.detectedAt, now)}.` : "The response team is watching the firm's AI systems."}
            {pending.length > 0 && <strong> {pending.length} decision{pending.length === 1 ? " needs" : "s need"} you.</strong>}
          </p>
          {r?.summary && <p className="brief-summary">{r.summary}</p>}
        </section>

        <section className="brief-comms" aria-label="How to reach each other">
          <span className="brief-pill t-exfil">Email: unreliable</span>
          <span className="brief-pill t-exfil">Phone lines: down</span>
          <span className="brief-pill t-clean">This console: secure, off the firm's network</span>
          <p>Use this page to coordinate. Assume the attacker can read normal email.</p>
        </section>

        <section className="panel brief-sec">
          <h2>What we need from you</h2>
          {pending.length === 0 ? (
            <p className="brief-none">Nothing right now. Decisions appear here the moment the team needs one.</p>
          ) : (
            <ol className="brief-decisions">{pending.map((a) => <Decision key={a.id} a={a} />)}</ol>
          )}
        </section>

        {hasClock && r && (
          <section className="panel brief-sec">
            <h2>Deadline</h2>
            <p className="brief-explain">Clients must be notified within 72 hours of their data leaving the firm.</p>
            <BreachCountdown deadlines={r.notificationDeadlines ?? []} fallbackDueAt={r.notificationDueAt} />
          </section>
        )}

        <section className="panel brief-sec">
          <h2>What's affected</h2>
          <ul className="brief-assets">
            {snapshot.assets.map((a) => {
              const s = ASSET_PLAIN[a.status];
              return (
                <li key={a.id}>
                  <div>
                    <strong>{a.name}</strong>
                    <span>{plainAssetDescription(a)}</span>
                  </div>
                  <span className={`chip t-${s.tone}`}>{s.label}</span>
                </li>
              );
            })}
          </ul>
        </section>

        <section className="panel brief-sec">
          <h2>Latest updates</h2>
          {updates.length === 0 ? (
            <p className="brief-none">No updates yet. The team posts here as the response moves forward.</p>
          ) : (
            <ol className="brief-updates">
              {updates.map(({ e, text }) => (
                <li key={e.id} className={e.severity && e.severity !== "info" ? `sev-${e.severity}` : undefined}>
                  <time dateTime={e.ts}>{clock(e.ts)}</time>
                  <span>{text}</span>
                </li>
              ))}
            </ol>
          )}
          {r && <Link className="brief-link" href="/record">Read the full incident record</Link>}
        </section>
      </div>

      <aside className="brief-room">
        <Chat />
      </aside>
    </main>
  );
}
