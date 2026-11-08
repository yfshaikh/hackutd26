import { useEffect, useMemo, useState, type FormEvent } from "react";
import { errorText, getMessages, sendMessage } from "../api";
import { useLive, useSession } from "../context";
import { clock } from "../format";
import { canChat } from "../labels";
import type { TimelineEntry } from "../types";
import { NoData } from "./Empty";

/**
 * Person-to-person chat on the incident. Backed by GET/POST /messages, which use
 * the human timeline entries; the live SSE feed keeps it current without polling.
 */
export function Chat() {
  const { snapshot, connection, apply } = useLive();
  const { user } = useSession();
  const [history, setHistory] = useState<TimelineEntry[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getMessages()
      .then(setHistory)
      .catch((e) => setLoadErr(errorText(e)));
  }, []);

  const live = useMemo(
    () => (snapshot?.timeline ?? []).filter((e) => e.kind === "human"),
    [snapshot],
  );
  const messages = useMemo(() => {
    const byId = new Map<string, TimelineEntry>();
    for (const e of history ?? []) byId.set(e.id, e);
    for (const e of live) byId.set(e.id, e);
    return [...byId.values()].sort((a, b) => a.ts.localeCompare(b.ts));
  }, [history, live]);

  const allowed = canChat(user?.role);

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
        <span className="aside">
          {messages.length === 0
            ? "Email & phones are down — coordinate here"
            : `${messages.length} message${messages.length === 1 ? "" : "s"}`}
        </span>
      </div>
      {!snapshot ? (
        <NoData connection={connection} what="People chat" />
      ) : loadErr ? (
        <p className="hint">Couldn't load chat history: {loadErr}</p>
      ) : history === null ? (
        <p className="hint">Loading chat history…</p>
      ) : messages.length === 0 ? (
        <p className="hint">No messages yet. With email and phones down, stakeholders — legal, IT, execs — coordinate the response here.</p>
      ) : (
        <ol className="chat-feed" aria-live="polite">
          {messages.map((m) => (
            <li key={m.id} className="chat-msg">
              <div className="chat-meta">
                <strong>{m.actor}</strong>
                <time dateTime={m.ts}>{clock(m.ts)}</time>
              </div>
              <p>{m.text}</p>
            </li>
          ))}
        </ol>
      )}
      {snapshot && (
        allowed ? (
          <form className="chat-composer" onSubmit={submit}>
            <label className="sr-only" htmlFor="chat-input">Message the incident team</label>
            <input
              id="chat-input"
              className="input"
              placeholder="Message the incident team"
              value={text}
              maxLength={1000}
              autoComplete="off"
              onChange={(e) => setText(e.target.value)}
            />
            <button className="btn btn-primary" disabled={busy || !text.trim()}>
              {busy ? "Sending…" : "Send"}
            </button>
          </form>
        ) : (
          <p className="hint">
            {user?.role === "approver"
              ? "Approvers can decide actions but not post chat. Ask an operator."
              : "Viewers can read the chat but can't post."}
          </p>
        )
      )}
      {err && <p className="hint chat-err" role="alert">{err}</p>}
    </section>
  );
}
