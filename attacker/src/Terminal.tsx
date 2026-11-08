// The laptop screen, wired to the real backend. Boot lines, then the live attack transcript
// (real code, HTTP calls, outputs over SSE) revealed one line at a time so it's readable.
// Flow: break in (STEP 0) -> once the token is stolen, the four payloads appear UNDER the log;
// pick ONE, its logs replace the break-in logs, the buttons hide, and you reset to choose again.
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { API, getRecon, getSteps, resetAll, runStep, streamTranscript } from "./api";
import type { AttackStep, Entry, Recon, StepId } from "./api";

const PLAYBOOK: Record<StepId, string> = {
  "gain-access": "Find an unauthenticated notebook and read the pod's Kubernetes token.",
  "start-miner": "Launch a disguised GPU-cryptojacking pod with the stolen token.",
  "steal-weights": "Mount the model-weights volume and exfiltrate the weights.",
  "persistence": "Plant a CronJob that respawns the miner every minute.",
  "ddos": "Turn the foothold into a bounded in-cluster connection flood.",
};
const PAYLOADS: StepId[] = ["start-miner", "steal-weights", "persistence", "ddos"];
const PACE_MS = 150;  // delay between revealed log lines (readable)
const CATCHUP = 10;   // reveal faster when more than this many are queued, so it never lags

const isURL = (s: string) => /^https?:\/\//.test(s) || /^\d{1,3}(?:\.\d{1,3}){3}:\d+$/.test(s);
function linkify(text: string): ReactNode[] {
  return text.split(/(https?:\/\/[^\s]+|\d{1,3}(?:\.\d{1,3}){3}:\d+)/g).map((p, i) =>
    isURL(p)
      ? <a key={i} className="link" href={p.startsWith("http") ? p : "http://" + p} target="_blank" rel="noreferrer">{p}</a>
      : <span key={i}>{p}</span>);
}
const jHref = (t?: string) => (t ? (t.startsWith("http") ? t : "http://" + t) : undefined);

// A banner when the defender cuts us off, read from real responses.
function lossFrom(e: Entry): { title: string; detail: string } | null {
  const s = typeof e.status === "number" ? e.status : undefined;
  if (s === 401 || s === 403 || (e.kind === "output" && /\b403\b|forbidden/i.test(e.text)))
    return { title: "Access lost", detail: "The stolen token was rejected. The defender revoked it." };
  if (e.kind === "output" && /notfound|not found/i.test(e.text) && /pod|cronjob/i.test(e.text))
    return { title: "Foothold lost", detail: e.text.split("\n")[0].slice(0, 140) };
  return null;
}

function entryNode(e: Entry): ReactNode {
  if (e.kind === "http") {
    const s = typeof e.status === "number" ? e.status : undefined;
    const cls = s === undefined ? "" : s < 300 ? "ok" : s < 400 ? "warn" : "bad";
    return (
      <div className={"ln http" + (s && s >= 400 ? " err" : "")}>
        {e.method ? <b>{e.method} </b> : null}
        {e.url ? <a className="link" href={e.url} target="_blank" rel="noreferrer">{e.url}</a> : e.text}
        {s !== undefined && <span className={"st " + cls}> {s}</span>}
      </div>
    );
  }
  if (e.kind === "code") return <div className="ln code">{e.text}</div>;
  if (e.kind === "cmd") return <div className="ln cmd">{linkify(e.text)}</div>;
  if (e.kind === "note") return <div className="ln note">{linkify(e.text)}</div>;
  return <div className="ln out">{linkify(e.text)}</div>;
}

const bootLines = (target?: string) => [
  { kind: "sys", text: "ZERO DAY OS 26.11 · HackUTD red team build" },
  { kind: "ok", text: "[ ok ] tailscale up  100.64.0.7" },
  { kind: "ok", text: "[ ok ] target in range  " + (target ?? "scanning…") },
  { kind: "sys", text: "Law firm: Halloran & Vance LLP · k3s GPU cluster" },
  { kind: "cmd", text: "./zeroday --target lawfirm" },
];

export default function Terminal({ booted }: { booted: boolean }) {
  const [steps, setSteps] = useState<AttackStep[] | null>(null);
  const [recon, setRecon] = useState<Recon | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [live, setLive] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [chosen, setChosen] = useState<StepId | null>(null);
  const [reveal, setReveal] = useState(0);
  const logRef = useRef<HTMLDivElement>(null);
  const follow = useRef(true);

  const refresh = () => {
    getSteps().then(setSteps).catch(() => setSteps(null));
    getRecon().then(setRecon).catch(() => setRecon(null));
  };
  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000);
    const stop = streamTranscript({
      history: setEntries,
      entry: (e) => setEntries((xs) => [...xs, e]),
      cleared: () => setEntries([]),
      connected: setLive,
    });
    return () => { clearInterval(t); stop(); };
  }, []);

  const connected = live || steps !== null;
  const gain = (steps ?? []).find((s) => s.id === "gain-access");
  const access = gain?.status === "done";
  const focusStep = chosen ?? "gain-access";

  // Lines in focus: boot preamble + break-in entries, OR just the chosen attack's entries.
  const items = useMemo(() => {
    const real = entries.filter((e) => (chosen ? e.step === chosen : e.step === "gain-access" || e.step === ""));
    const list: { key: string; node: ReactNode }[] = [];
    if (!chosen) bootLines(recon?.target).forEach((b, i) => list.push({ key: "boot" + i, node: <div className={"ln " + b.kind}>{linkify(b.text)}</div> }));
    real.forEach((e) => list.push({ key: e.id, node: entryNode(e) }));
    return list;
  }, [entries, chosen, recon?.target]);

  // Reveal one line at a time (fast catch-up for big bursts) once the screen has booted.
  useEffect(() => { setReveal(0); }, [focusStep]);
  useEffect(() => {
    if (!booted || reveal >= items.length) return;
    const gap = items.length - reveal > CATCHUP ? 40 : PACE_MS;
    const t = setTimeout(() => setReveal((c) => c + 1), gap);
    return () => clearTimeout(t);
  }, [booted, reveal, items.length]);
  const visible = items.slice(0, reveal);
  const settled = reveal >= items.length && items.length > 0;

  useEffect(() => { if (follow.current && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [visible.length]);

  const banner = useMemo(() => {
    for (let i = entries.length - 1; i >= 0; i--) { const b = lossFrom(entries[i]); if (b) return b; }
    return null;
  }, [entries]);

  async function act(id: StepId) {
    setBusy(id); setErr(null);
    if (id !== "gain-access") setChosen(id); // commit to one attack; its logs replace the break-in logs
    try { const r = await runStep(id); setSteps(r.attack); if (!r.ok) setErr(r.message); }
    catch (e) { setErr(`Request failed: ${(e as Error).message}`); }
    finally { setBusy(null); refresh(); }
  }
  async function reset() {
    setBusy("reset"); setErr(null); setChosen(null);
    try { const r = await resetAll(); setSteps(r.attack); setEntries([]); }
    catch (e) { setErr(`Reset failed: ${(e as Error).message}`); }
    finally { setBusy(null); refresh(); }
  }

  const stepLabel = chosen
    ? (steps ?? []).find((s) => s.id === chosen)?.label ?? ""
    : access ? "FOOTHOLD: lawfirm/notebook" : "";
  const runningChosen = !!chosen && (busy === chosen || (steps ?? []).find((s) => s.id === chosen)?.status === "running");

  return (
    <>
      <div className="bar">
        <b className={connected ? "live" : "off"} /><b /><b />
        <span className="who">raccoon@zeroday: ~/ops</span>
        <span className="step">{stepLabel}</span>
      </div>

      {connected && recon && (
        <div className="recon">
          <span>target <a className="link" href={jHref(recon.target)} target="_blank" rel="noreferrer">{recon.target}</a></span>
          <span>jupyter <b className={recon.jupyter?.reachable ? "ok" : ""}>{recon.jupyter?.reachable ? "open · no password" : "unreachable"}</b></span>
          <span>gpu <b>{recon.gpu?.model ? `${recon.gpu.model} · ${recon.gpu.utilization ?? "?"}%` : "?"}</b></span>
          <span>identity <b>{recon.identity.namespace}/{recon.identity.serviceAccount}</b></span>
        </div>
      )}

      {banner && <div className="banner"><strong>{banner.title}</strong><span>{banner.detail}</span></div>}

      {!connected ? (
        <div className="empty"><h2>No connection</h2><p>The attack backend at <code>{API}</code> isn't answering. Start it and this fills in.</p></div>
      ) : (
        <div
          className="log"
          ref={logRef}
          onScroll={(ev) => { const el = ev.currentTarget; follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40; }}
          aria-live="polite"
        >
          {visible.map((it) => <div key={it.key}>{it.node}</div>)}
          {access && !chosen && settled && <div className="ln big">ACCESS GRANTED</div>}
          {booted && !settled && <span className="caret" aria-hidden />}
        </div>
      )}

      {connected && booted && (
        <div className="actions">
          {!access ? (
            (settled || busy) && (
              <>
                <span className="act-head">step 0 — break in</span>
                <button className="act danger" disabled={gain?.status !== "ready" || !!busy} onClick={() => act("gain-access")} title={PLAYBOOK["gain-access"]}>
                  {busy === "gain-access" || gain?.status === "running" ? "exploiting…" : "Gain access"}
                </button>
              </>
            )
          ) : !chosen && settled ? (
            <>
              <span className="act-head ok">access ✓ — choose one attack</span>
              {PAYLOADS.map((id) => {
                const s = (steps ?? []).find((x) => x.id === id);
                return (
                  <button key={id} className={"act" + (s?.status === "done" ? " done" : "")} disabled={!!busy} onClick={() => act(id)} title={PLAYBOOK[id]}>
                    {s?.label ?? id}
                  </button>
                );
              })}
              <button className="act ghost" disabled={!!busy} onClick={reset}>⟲ reset</button>
            </>
          ) : chosen ? (
            <>
              <span className={"act-head" + (runningChosen ? "" : " ok")}>{runningChosen ? "running attack…" : "attack complete"}</span>
              <button className="act ghost" disabled={busy === "reset"} onClick={reset}>⟲ reset &amp; choose again</button>
            </>
          ) : null}
          {err && <p className="err">{err}</p>}
        </div>
      )}
    </>
  );
}
