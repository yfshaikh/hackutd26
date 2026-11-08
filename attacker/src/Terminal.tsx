// The laptop screen, wired to the real backend. Boot lines, then the live attack transcript
// (real code, HTTP calls, outputs over SSE) revealed one logical group at a time so it's readable.
// Flow: break in (STEP 0) -> once the token is stolen, the four payloads appear UNDER the log;
// pick ONE, its logs replace the break-in logs, the buttons hide, and you can run another attack
// (back to the picker) or reset to choose again.
import { useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import { API, getRecon, getSteps, resetAll, runStep, streamTranscript } from "./api";
import type { AttackStep, Entry, Recon, StepId } from "./api";
import LootPanel from "./LootPanel";

const PLAYBOOK: Record<StepId, string> = {
  "gain-access": "Find an unauthenticated notebook and read the pod's Kubernetes token.",
  "start-miner": "Launch a disguised GPU-cryptojacking pod with the stolen token.",
  "steal-weights": "Mount the model-weights volume and exfiltrate the weights.",
  "persistence": "Plant a CronJob that respawns the miner every minute.",
  "ddos": "Turn the foothold into a bounded in-cluster connection flood.",
};
const PAYLOADS: StepId[] = ["start-miner", "steal-weights", "persistence", "ddos"];
const PACE_MS = 140;  // delay between auto-revealed BOOT lines (attack lines are manual, via Next)

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

// Copy the raw code of a folded block. Lives in the <summary>, so it must not also toggle
// the fold — stop the click there and prevent the default <summary> behaviour.
function CopyCode({ code }: { code: string }) {
  const [done, setDone] = useState(false);
  const copy = async (e: ReactMouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(code);
      setDone(true);
      setTimeout(() => setDone(false), 1200);
    } catch { /* clipboard blocked (no https / permissions): leave the button as-is */ }
  };
  return (
    <button type="button" className="code-copy" onClick={copy} aria-label="Copy code">
      {done ? "copied" : "copy"}
    </button>
  );
}

// One revealed line in the terminal, keeping the entry kind so we can group/reveal it.
type Item = { key: string; kind: string; text: string; node: ReactNode };

// Render the revealed lines, folding each run of code (with any interleaved note
// comments) into one collapsed <details> so the scripts don't dominate the screen.
function renderItems(items: Item[]): ReactNode[] {
  const out: ReactNode[] = [];
  let i = 0;
  while (i < items.length) {
    if (items[i].kind !== "code") {
      out.push(<div key={items[i].key}>{items[i].node}</div>);
      i++;
      continue;
    }
    let last = i;
    let j = i + 1;
    while (j < items.length && (items[j].kind === "code" || items[j].kind === "note")) {
      if (items[j].kind === "code") last = j;
      j++;
    }
    const run = items.slice(i, last + 1);
    const lines = run.reduce((n, it) => n + (it.kind === "code" ? it.text.split("\n").length : 1), 0);
    const code = run.filter((it) => it.kind === "code").map((it) => it.text).join("\n");
    out.push(
      <details className="code-block" key={items[i].key}>
        <summary>
          <span>▸ code · {lines} lines</span>
          <CopyCode code={code} />
        </summary>
        {run.map((it) => <div key={it.key}>{it.node}</div>)}
      </details>,
    );
    i = last + 1;
  }
  return out;
}

const bootLines = (target?: string) => [
  { kind: "sys", text: "ZERO DAY OS 26.11 · HackUTD red team build" },
  { kind: "ok", text: "[ ok ] tailscale up  100.64.0.7" },
  { kind: "ok", text: "[ ok ] target in range  " + (target ?? "scanning…") },
  { kind: "sys", text: "Law firm: Winstead PC · k3s GPU cluster" },
  { kind: "cmd", text: "./zeroday --target lawfirm" },
];

export default function Terminal({ booted, onClose }: { booted: boolean; onClose: () => void }) {
  const [steps, setSteps] = useState<AttackStep[] | null>(null);
  const [recon, setRecon] = useState<Recon | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [live, setLive] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [chosen, setChosen] = useState<StepId | null>(null);
  const [reveal, setReveal] = useState(0);
  const everAccessed = useRef(false);
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
  const items = useMemo<Item[]>(() => {
    const real = entries.filter((e) => (chosen ? e.step === chosen : e.step === "gain-access" || e.step === ""));
    const list: Item[] = [];
    if (!chosen) bootLines(recon?.target).forEach((b, i) => list.push({ key: "boot" + i, kind: b.kind, text: b.text, node: <div className={"ln " + b.kind}>{linkify(b.text)}</div> }));
    real.forEach((e) => list.push({ key: e.id, kind: e.kind, text: e.text, node: entryNode(e) }));
    return list;
  }, [entries, chosen, recon?.target]);

  // Logical groups for the Next button: a note/cmd starts a group and absorbs the
  // http/code/out lines under it, so a comment and the call it describes reveal together.
  const groups = useMemo(() => {
    const ends: number[] = [];
    let i = 0;
    while (i < items.length) {
      if (items[i].kind === "note" || items[i].kind === "cmd") {
        let j = i + 1;
        while (j < items.length && items[j].kind !== "note" && items[j].kind !== "cmd") j++;
        ends.push(j);
        i = j;
      } else {
        ends.push(i + 1);
        i++;
      }
    }
    return ends;
  }, [items]);

  // Remember that access was granted at least once, so returning to the picker can
  // skip the boot/break-in replay and show the menu immediately.
  useEffect(() => { if (access) everAccessed.current = true; }, [access]);

  // The boot intro auto-plays; attack lines wait for the Next button so the operator can
  // read each one. Reset the reveal when the focus step changes or the lid closes.
  const BOOT_LEN = chosen ? 0 : bootLines().length;
  useEffect(() => {
    // Returning from a finished attack: jump straight to the already-seen break-in log
    // (and its settled "choose one attack" menu) instead of replaying it from zero.
    if (everAccessed.current && access && !chosen) setReveal(items.length);
    else setReveal(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusStep]);
  useEffect(() => { if (!booted) setReveal(0); }, [booted]);
  useEffect(() => {
    if (!booted || reveal >= BOOT_LEN) return;
    const t = setTimeout(() => setReveal((c) => c + 1), PACE_MS);
    return () => clearTimeout(t);
  }, [booted, reveal, BOOT_LEN]);
  const visible = items.slice(0, reveal);
  const pending = items.length - reveal;                      // unrevealed lines
  const remainingGroups = groups.filter((end) => end > reveal).length; // unrevealed groups
  const stepping = booted && reveal >= BOOT_LEN && pending > 0; // past the intro, lines to step
  const settled = pending <= 0 && items.length > 0;
  // Reveal the next whole logical group (end index of the first group past the cursor).
  const advance = () => setReveal((c) => groups.find((end) => end > c) ?? items.length);

  useEffect(() => { if (follow.current && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [visible.length]);

  const banner = useMemo(() => {
    for (let i = entries.length - 1; i >= 0; i--) { const b = lossFrom(entries[i]); if (b) return b; }
    return null;
  }, [entries]);

  async function act(id: StepId) {
    setBusy(id); setErr(null);
    if (id !== "gain-access") setChosen(id); // commit to one attack; its logs replace the break-in logs
    try {
      // A break-in starts from a clean slate: reset restores the stolen token's permissions, so a
      // revoke approved in a previous run doesn't leave the next attack dead on arrival (no pod, no
      // logs, nothing to demo). gain-access is the first step of every run, so reset lives here.
      if (id === "gain-access") { everAccessed.current = false; await resetAll(); setEntries([]); }
      const r = await runStep(id); setSteps(r.attack); if (!r.ok) setErr(r.message);
    }
    catch (e) { setErr(`Request failed: ${(e as Error).message}`); }
    finally { setBusy(null); refresh(); }
  }
  async function reset() {
    everAccessed.current = false;
    setBusy("reset"); setErr(null); setChosen(null);
    try { const r = await resetAll(); setSteps(r.attack); setEntries([]); }
    catch (e) { setErr(`Reset failed: ${(e as Error).message}`); }
    finally { setBusy(null); refresh(); onClose(); }  // reset also closes the laptop
  }
  // "Run another attack": start a fresh break-in rather than reusing the old foothold. This
  // resets the cluster (restoring the stolen token) and re-establishes access, so a revoke
  // approved in the last run can't leave the next attack dead. The laptop stays open.
  function backToMenu() {
    setErr(null);
    setChosen(null);
    act("gain-access");
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
          {renderItems(visible)}
          {access && !chosen && settled && <div className="ln big">ACCESS GRANTED</div>}
          {booted && !settled && <span className="caret" aria-hidden />}
        </div>
      )}

      {access && <LootPanel active={connected && access} />}

      {connected && booted && (
        <div className="actions">
          {stepping ? (
            <button className="act next-btn" onClick={advance}>Next&nbsp;▸{remainingGroups > 1 ? ` · ${remainingGroups} more` : ""}</button>
          ) : !access ? (
            busy ? (
              <span className="act-head">exploiting…</span>
            ) : (
              <>
                <span className="act-head">step 0 — break in</span>
                <button className="act danger" disabled={gain?.status !== "ready"} onClick={() => act("gain-access")} title={PLAYBOOK["gain-access"]}>Gain access</button>
              </>
            )
          ) : !chosen ? (
            settled ? (
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
            ) : (
              <span className="act-head ok">access ✓ — waiting for next line…</span>
            )
          ) : runningChosen ? (
            <span className="act-head">running attack…</span>
          ) : (
            <>
              <span className="act-head ok">attack complete</span>
              <button className="act" disabled={!!busy} onClick={backToMenu}>▸ run another attack</button>
              <button className="act ghost" disabled={busy === "reset"} onClick={reset}>⟲ reset &amp; close</button>
            </>
          )}
          {err && <p className="err">{err}</p>}
        </div>
      )}
    </>
  );
}
