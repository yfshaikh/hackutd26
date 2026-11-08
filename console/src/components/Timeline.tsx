import { useState } from "react";
import { AGENT_BY_ID, agentOf, initials, type AgentId } from "../agents";
import { useLive } from "../context";
import { clock } from "../format";
import { SEVERITY } from "../labels";
import type { TimelineEntry } from "../types";
import { NoData } from "./Empty";

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

function Entry({ e }: { e: TimelineEntry }) {
  const a = e.autonomy;
  const [open, setOpen] = useState(false);
  const agent = AGENT_BY_ID[agentOf(e)];
  const sev = e.severity && e.severity !== "info" ? SEVERITY[e.severity] : null;
  return (
    <li className={`entry k-${e.kind}${open ? " open" : ""}`}>
      <button className="entry-row" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <time dateTime={e.ts}>{clock(e.ts)}</time>
        <span className={`entry-avatar t-${agent.tone}`} aria-hidden>
          {agent.img ? <img src={agent.img} alt="" /> : initials(e.actor)}
        </span>
        <span className="entry-main">
          <span className="who">{agent.id === "executor" ? "Executor" : e.actor}</span>
          <span className="text">{e.text}</span>
        </span>
        {a?.mode === "needs-approval" && agent.id !== "executor" && <span className="chip mode-ask">Asked approval</span>}
        {sev && <span className={`sev-dot t-${sev.tone}`} title={`${sev.label} severity`}><span className="sr-only">{sev.label}</span></span>}
        <span className="chev" aria-hidden />
      </button>
      {open && (
        <div className="entry-body">
          <p className="text-full">{e.text}</p>
          {e.tool && <code className="tool">{e.tool}</code>}
          {a && (
            <p className="policy">
              <span className={`chip ${a.mode === "autonomous" ? "mode-auto" : "mode-ask"}`}>
                {a.mode === "autonomous" ? "Ran on its own" : "Needed approval"}
              </span>
              <span className="why">{a.reason}</span>
            </p>
          )}
          {hasDetail(e) && <Detail e={e} />}
        </div>
      )}
    </li>
  );
}

export function Timeline({ agent, onClear }: { agent: AgentId | null; onClear: () => void }) {
  const { snapshot, connection } = useLive();
  const entries = (snapshot?.timeline ?? [])
    .filter((e) => !e.traceOnly) // read-only lookups live in the agent's trace, not the main story
    .filter((e) => !agent || agentOf(e) === agent)
    .slice()
    .sort((a, b) => b.ts.localeCompare(a.ts));

  return (
    <section className="panel timeline-panel" aria-labelledby="tl-h">
      <div className="panel-head">
        <h2 id="tl-h">Live timeline</h2>
        <span className="aside">
          {agent ? <>Only {AGENT_BY_ID[agent].name} · <button className="link-btn" onClick={onClear}>show all</button></> : "Newest first · click a row for detail"}
        </span>
      </div>
      {!snapshot ? (
        <NoData connection={connection} what="The timeline" />
      ) : entries.length === 0 ? (
        <div className="empty">
          <strong>{agent ? `Nothing from ${AGENT_BY_ID[agent].name} yet` : "Nothing has happened yet"}</strong>
          <span>Attack events, agent actions and team messages appear here, newest first.</span>
        </div>
      ) : (
        <ol className="feed" aria-live="polite">
          {entries.map((e) => (
            <Entry key={e.id} e={e} />
          ))}
        </ol>
      )}
    </section>
  );
}
