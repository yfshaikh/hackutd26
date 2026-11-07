import { useState, type FormEvent } from "react";
import { errorText, sendMessage } from "../api";
import { useLive, useSession } from "../context";
import { clock } from "../format";
import { canAct } from "../labels";
import type { TimelineEntry, TimelineKind } from "../types";
import { NoData } from "./Empty";
import { SeverityChip } from "./Status";

/** Transcript-line colouring mirrors the attacker terminal: note=why, http=call, etc. */
const TX_LABEL: Record<string, string> = {
  note: "why", code: "code", http: "call", output: "output", cmd: "shell",
};

function hasDetail(e: TimelineEntry): boolean {
  return Boolean(
    e.reasoning || e.toolResult || e.podLogs ||
    (e.toolArgs && Object.keys(e.toolArgs).length) ||
    (e.transcript && e.transcript.length),
  );
}

function Detail({ e }: { e: TimelineEntry }) {
  return (
    <div className="entry-detail">
      {e.reasoning && (
        <div className="detail-block">
          <span className="detail-label">Nemotron reasoning</span>
          <p className="reasoning">{e.reasoning}</p>
        </div>
      )}
      {e.toolArgs && Object.keys(e.toolArgs).length > 0 && (
        <div className="detail-block">
          <span className="detail-label">Tool call arguments</span>
          <pre className="detail-pre">{JSON.stringify(e.toolArgs, null, 2)}</pre>
        </div>
      )}
      {e.toolResult && (
        <div className="detail-block">
          <span className="detail-label">Result</span>
          <pre className="detail-pre">{e.toolResult}</pre>
        </div>
      )}
      {e.podLogs && (
        <div className="detail-block">
          <span className="detail-label">Pod logs</span>
          <pre className="detail-pre">{e.podLogs}</pre>
        </div>
      )}
      {e.transcript && e.transcript.length > 0 && (
        <div className="detail-block">
          <span className="detail-label">Attacker transcript that caused this</span>
          <ol className="tx-lines">
            {e.transcript.map((t, i) => (
              <li key={i} className={`tx tx-${t.kind}`}>
                <span className="tx-kind">{TX_LABEL[t.kind] ?? t.kind}</span>
                <pre className="tx-text">{t.text}</pre>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

const FILTERS: { id: "all" | TimelineKind; label: string }[] = [
  { id: "all", label: "All" },
  { id: "attack", label: "Attacks" },
  { id: "agent", label: "Agents" },
  { id: "human", label: "People" },
];

function Entry({ e }: { e: TimelineEntry }) {
  const a = e.autonomy;
  const [open, setOpen] = useState(false);
  const detail = hasDetail(e);
  const txCount = e.transcript?.length ?? 0;
  return (
    <li className={`entry k-${e.kind}`}>
      <time dateTime={e.ts}>{clock(e.ts)}</time>
      <div>
        <div className="who">
          {e.actor}
          {e.severity && e.severity !== "info" && <SeverityChip severity={e.severity} />}
        </div>
        <p className="text">{e.text}</p>
        {e.tool && <code className="tool">{e.tool}</code>}
        {a && (
          <p className="policy">
            {a.mode === "autonomous" ? (
              <span className="chip mode-auto">Autonomous</span>
            ) : (
              <span className="chip mode-ask">Needs approval</span>
            )}
            <span className="why">{a.reason}</span>
          </p>
        )}
        {detail && (
          <button
            className="detail-toggle"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "Hide detail" : e.kind === "attack" && txCount
              ? `Show what the attacker did (${txCount})`
              : "Show detail"}
          </button>
        )}
        {detail && open && <Detail e={e} />}
      </div>
    </li>
  );
}

function Composer() {
  const { apply, connection } = useLive();
  const { user } = useSession();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!canAct(user?.role)) return <p className="hint">Viewers can read the timeline but can't post.</p>;
  if (connection !== "live") return <p className="hint">Messages can be sent once the command center is back.</p>;

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    const t = text.trim();
    if (!t) return;
    setBusy(true);
    setErr(null);
    try {
      const entry = await sendMessage(t);
      apply({ type: "timeline", entry });
      setText("");
    } catch (e) {
      setErr(`Message not sent: ${errorText(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit}>
      {err && <p className="hint" role="alert" style={{ color: "var(--exfil)", fontWeight: 700 }}>{err}</p>}
      <div className="composer">
        <label className="sr-only" htmlFor="msg">Message to the team</label>
        <input
          id="msg"
          className="input"
          placeholder="Message the team and agents"
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={1000}
          autoComplete="off"
        />
        <button className="btn btn-primary" disabled={busy || !text.trim()}>
          {busy ? "Sending…" : "Send"}
        </button>
      </div>
    </form>
  );
}

export function Timeline() {
  const { snapshot, connection } = useLive();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["id"]>("all");
  const entries = (snapshot?.timeline ?? [])
    .filter((e) => filter === "all" || e.kind === filter)
    .slice()
    .sort((a, b) => b.ts.localeCompare(a.ts));

  return (
    <section className="panel timeline-panel area-timeline" aria-labelledby="tl-h">
      <div className="panel-head">
        <h2 id="tl-h">Live timeline</h2>
        <div className="filters" role="group" aria-label="Filter timeline">
          {FILTERS.map((f) => (
            <button key={f.id} aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
              {f.label}
            </button>
          ))}
        </div>
      </div>
      {!snapshot ? (
        <NoData connection={connection} what="The timeline" />
      ) : entries.length === 0 ? (
        <div className="empty">
          <strong>{filter === "all" ? "Nothing has happened yet" : "No entries of this kind"}</strong>
          <span>Attack events, agent actions and team messages appear here, newest first.</span>
        </div>
      ) : (
        <ol className="feed" aria-live="polite">
          {entries.map((e) => (
            <Entry key={e.id} e={e} />
          ))}
        </ol>
      )}
      {snapshot && <Composer />}
    </section>
  );
}
