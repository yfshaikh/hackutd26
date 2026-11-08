import { Fragment, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { errorText, getMessages, listUsers, sendMessage } from "../api";
import { useLive, useSession } from "../context";
import { clock } from "../format";
import { canChat, ROLE } from "../labels";
import { plainUpdate } from "../plain";
import type { Role, TimelineEntry } from "../types";
import { NoData } from "./Empty";

/**
 * The war room: person-to-person chat for the incident's stakeholders, with plain-English
 * updates from the response team interleaved as distinct cards so the conversation and the
 * facts sit side by side. Backed by GET/POST /messages; the live SSE feed keeps it current.
 */

const QUICK = ["On it", "Need more info", "Approved on my side", "Calling the client"];

/** @name mentions in bold. */
function withMentions(text: string): ReactNode[] {
  return text.split(/(@[\w.-]+(?:\s[A-Z][\w.-]+)?)/g).map((part, i) =>
    part.startsWith("@") ? <mark key={i} className="mention">{part}</mark> : <Fragment key={i}>{part}</Fragment>,
  );
}

type Row =
  | { kind: "msg"; e: TimelineEntry; first: boolean }
  | { kind: "update"; e: TimelineEntry; text: string };

export function Chat() {
  const { snapshot, connection, apply } = useLive();
  const { user } = useSession();
  const [history, setHistory] = useState<TimelineEntry[] | null>(null);
  const [roles, setRoles] = useState<Record<string, Role>>({});
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getMessages()
      .then(setHistory)
      .catch((e) => setLoadErr(errorText(e)));
    // Role labels for everyone: the user list is admin-only, so others just see names.
    listUsers()
      .then((us) => setRoles(Object.fromEntries(us.map((u) => [u.name, u.role]))))
      .catch(() => undefined);
  }, []);

  const rows = useMemo<Row[]>(() => {
    const byId = new Map<string, TimelineEntry>();
    for (const e of history ?? []) byId.set(e.id, e);
    for (const e of snapshot?.timeline ?? []) {
      if (e.kind === "human" || plainUpdate(e)) byId.set(e.id, e);
    }
    const out: Row[] = [];
    let prev: string | null = null;
    for (const e of [...byId.values()].sort((a, b) => a.ts.localeCompare(b.ts))) {
      const update = plainUpdate(e); // includes "X approved: …" for human approval entries
      if (update) {
        out.push({ kind: "update", e, text: update });
        prev = null;
      } else if (e.kind === "human") {
        out.push({ kind: "msg", e, first: prev !== e.actor });
        prev = e.actor;
      }
    }
    return out;
  }, [history, snapshot]);

  const people = useMemo(() => {
    const names = new Set(rows.filter((r) => r.kind === "msg").map((r) => r.e.actor));
    if (user) names.delete(user.name);
    return [...names];
  }, [rows, user]);

  const allowed = canChat(user?.role);
  const roleOf = (name: string) => (name === user?.name ? user.role : roles[name]);

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    const t = text.trim();
    if (!t) return;
    setBusy(true);
    setErr(null);
    try {
      const entry = await sendMessage(t);
      apply({ type: "timeline", entry });
      setHistory((prev) => [...(prev ?? []), entry]);
      setText("");
    } catch (e) {
      setErr(`Message not sent: ${errorText(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel chat-panel" aria-labelledby="chat-h">
      <div className="panel-head">
        <h2 id="chat-h">War room</h2>
        <span className="aside">Secure channel · off the firm's network</span>
      </div>

      <div className="room-roster" aria-label="People in this room">
        {user && (
          <span className="room-person is-me">
            <span className="room-dot" aria-hidden /> {user.name} <em>{ROLE[user.role].label}</em>
          </span>
        )}
        {people.map((p) => (
          <span key={p} className="room-person">
            {p} {roleOf(p) && <em>{ROLE[roleOf(p)!].label}</em>}
          </span>
        ))}
      </div>

      {!snapshot ? (
        <NoData connection={connection} what="The war room" />
      ) : loadErr ? (
        <p className="hint">Couldn't load the conversation: {loadErr}</p>
      ) : history === null ? (
        <p className="hint">Loading the conversation…</p>
      ) : rows.length === 0 ? (
        <p className="hint room-empty">
          No messages yet. Email and phones may be compromised, so partners, IT, legal and outside responders
          coordinate here. Updates from the response team appear in this thread as they happen.
        </p>
      ) : (
        <ol className="chat-feed" aria-live="polite">
          {rows.map((r) =>
            r.kind === "update" ? (
              <li key={r.e.id} className="room-update">
                <span className="room-update-label">Update from the response team</span>
                <p>{r.text}</p>
                <time dateTime={r.e.ts}>{clock(r.e.ts)}</time>
              </li>
            ) : (
              <li key={r.e.id} className={`chat-msg${r.e.actor === user?.name ? " is-mine" : ""}${r.first ? "" : " is-cont"}`}>
                {r.first && (
                  <div className="chat-meta">
                    <strong>{r.e.actor}</strong>
                    {roleOf(r.e.actor) && <span className="room-role">{ROLE[roleOf(r.e.actor)!].label}</span>}
                    <time dateTime={r.e.ts}>{clock(r.e.ts)}</time>
                  </div>
                )}
                <p>{withMentions(r.e.text)}</p>
              </li>
            ),
          )}
        </ol>
      )}

      {snapshot && (
        allowed ? (
          <>
            <div className="room-quick" aria-label="Quick replies">
              {QUICK.map((q) => (
                <button key={q} type="button" className="room-chip" onClick={() => setText(q)}>{q}</button>
              ))}
            </div>
            <form className="chat-composer" onSubmit={submit}>
              <label className="sr-only" htmlFor="chat-input">Message everyone in the war room</label>
              <input
                id="chat-input"
                className="input"
                placeholder="Message everyone. Use @name to get someone's attention"
                value={text}
                maxLength={1000}
                autoComplete="off"
                onChange={(e) => setText(e.target.value)}
              />
              <button className="btn btn-primary" disabled={busy || !text.trim()}>
                {busy ? "Sending…" : "Send"}
              </button>
            </form>
          </>
        ) : (
          <p className="hint">
            {user?.role === "approver"
              ? "Approvers can decide actions but can't post here. Ask an operator to relay."
              : "You can read the conversation but can't post."}
          </p>
        )
      )}
      {err && <p className="hint chat-err" role="alert">{err}</p>}
    </section>
  );
}
