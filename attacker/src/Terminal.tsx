// The attacker's screen. Everything shown comes from the backend: recon from GET /attack/recon,
// step state from GET /attack, and the live transcript (real code, HTTP calls, outputs) over SSE.
import { useEffect, useMemo, useRef, useState } from "react";
import { API, getRecon, getSteps, resetAll, runStep, streamTranscript } from "./api";
import type { AttackStep, Entry, Recon, StepId } from "./api";

// What a real attacker is doing at each step, and where this was seen in the wild (see docs/system-map).
const PLAYBOOK: Record<StepId, { why: string; seen: string }> = {
  "gain-access": { why: "Find a notebook with no password and run code in it, then read the Kubernetes token every pod carries.", seen: "Kubeflow 2020 · ShadowRay" },
  "start-miner": { why: "Use the stolen token to launch a pod that grabs a GPU slice and burns it.", seen: "XMRig on hijacked GPUs · TeamTNT" },
  "steal-weights": { why: "Mount the firm's model disk in a new pod and upload the weights to a server you control.", seen: "Model theft · ShadowRay" },
  "persistence": { why: "Plant a CronJob so the miner comes back every minute, even after it's killed.", seen: "CronJob backdoor · Kubeflow 2020" },
};

type Banner = { title: string; detail: string } | null;

function lossFrom(e: Entry): Banner {
  const status = typeof e.status === "number" ? e.status : undefined;
  if (status === 401 || status === 403 || (e.kind === "output" && /\b403\b|forbidden/i.test(e.text)))
    return { title: "Access lost", detail: "The stolen token was rejected. The defender revoked it." };
  if (e.kind === "output" && /notfound|not found/i.test(e.text) && /pod|cronjob/i.test(e.text))
    return { title: "Foothold lost", detail: e.text.split("\n")[0].slice(0, 140) };
  return null;
}

function Line({ e }: { e: Entry }) {
  const time = e.ts.slice(11, 19);
  if (e.kind === "code")
    return <div className="ln"><span className="ts">{time}</span><pre className="code">{e.text}</pre></div>;
  if (e.kind === "http") {
    const s = typeof e.status === "number" ? e.status : undefined;
    const cls = s === undefined ? "" : s < 300 ? "ok" : s < 400 ? "warn" : "bad";
    return (
      <div className="ln"><span className="ts">{time}</span>
        <span className="http">{e.method ? <b>{e.method} </b> : null}{e.url ?? e.text}{s !== undefined && <span className={`st ${cls}`}> {s}</span>}</span>
        {e.url && e.text !== e.url && <span className="dim"> {e.text}</span>}
      </div>
    );
  }
  if (e.kind === "cmd") return <div className="ln"><span className="ts">{time}</span><span className="prompt">$ </span>{e.text}</div>;
  if (e.kind === "note") return <div className="ln note"><span className="ts">{time}</span># {e.text}</div>;
  return <div className="ln"><span className="ts">{time}</span><pre className="out">{e.text}</pre></div>;
}

export default function Terminal({ onClose }: { onClose: () => void }) {
  const [steps, setSteps] = useState<AttackStep[] | null>(null);
  const [recon, setRecon] = useState<Recon | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [live, setLive] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [follow, setFollow] = useState(true);
  const feed = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    if (follow && feed.current) feed.current.scrollTop = feed.current.scrollHeight;
  }, [entries, follow]);

  // The most recent sign that the defender cut us off, taken from real responses.
  const banner = useMemo(() => {
    for (let i = entries.length - 1; i >= 0; i--) { const b = lossFrom(entries[i]); if (b) return b; }
    return null;
  }, [entries]);

  async function act(id: StepId) {
    setBusy(id); setErr(null);
    try { const r = await runStep(id); setSteps(r.attack); if (!r.ok) setErr(r.message); }
    catch (e) { setErr(`Request failed: ${(e as Error).message}`); }
    finally { setBusy(null); refresh(); }
  }
  async function reset() {
    setConfirmReset(false); setBusy("reset"); setErr(null);
    try { const r = await resetAll(); setSteps(r.attack); } catch (e) { setErr(`Reset failed: ${(e as Error).message}`); }
    finally { setBusy(null); refresh(); }
  }

  const connected = live || steps !== null;
  const rules = recon?.identity?.rules;

  return (
    <div className="term">
      <header className="bar">
        <span className="host">kali@redbox</span>
        <span className="sep">→</span>
        <span className="target">{recon?.target ?? "no target"}</span>
        <span className={`dot ${connected ? "on" : ""}`} title={connected ? "Connected to backend" : "Backend unreachable"} />
        <button className="ghost" onClick={onClose}>Close laptop</button>
      </header>

      {!connected ? (
        <div className="empty">
          <h2>No connection</h2>
          <p>The attack backend at <code>{API}</code> isn't answering. Start it, then this screen fills in by itself.</p>
        </div>
      ) : (
        <div className="grid">
          <aside className="side">
            <section className="card">
              <h3>Target</h3>
              <dl>
                <dt>Jupyter</dt>
                <dd className={recon?.jupyter?.reachable ? "ok" : "dim"}>{recon ? (recon.jupyter?.reachable ? "open, no password" : "not reachable") : "…"}</dd>
                <dt>GPU</dt>
                <dd>{recon?.gpu?.model ? `${recon.gpu.model} · ${recon.gpu.utilization ?? "?"}% busy` : "unknown"}</dd>
                <dt>Identity</dt>
                <dd>{recon ? `${recon.identity.namespace}/${recon.identity.serviceAccount}` : "…"}</dd>
              </dl>
              {Array.isArray(rules) && rules.length > 0 && (
                <details><summary>Stolen permissions ({rules.length})</summary><pre className="out small">{JSON.stringify(rules, null, 1)}</pre></details>
              )}
            </section>

            <section className="steps">
              {(steps ?? []).map((s, i) => {
                const p = PLAYBOOK[s.id];
                const running = busy === s.id || s.status === "running";
                return (
                  <button key={s.id} className={`step ${s.status}`} disabled={s.status !== "ready" || !!busy} onClick={() => act(s.id)}>
                    <span className="num">{i + 1}</span>
                    <span className="body">
                      <span className="label">{s.label}{running ? " · running" : s.status === "done" ? " · done" : ""}</span>
                      <span className="why">{p?.why ?? s.description}</span>
                      {p && <span className="seen">Seen in the wild: {p.seen}</span>}
                    </span>
                  </button>
                );
              })}
            </section>

            {err && <p className="err" role="alert">{err}</p>}

            <div className="reset">
              {confirmReset ? (
                <>
                  <span>Remove everything the attack created?</span>
                  <button className="danger" onClick={reset}>Reset</button>
                  <button className="ghost" onClick={() => setConfirmReset(false)}>Cancel</button>
                </>
              ) : (
                <button className="ghost" disabled={!!busy} onClick={() => setConfirmReset(true)}>{busy === "reset" ? "Resetting…" : "Reset cluster"}</button>
              )}
            </div>
          </aside>

          <main className="feedwrap">
            {banner && (
              <div className="banner" role="alert"><strong>{banner.title}</strong><span>{banner.detail}</span></div>
            )}
            <div
              className="feed"
              ref={feed}
              onScroll={(ev) => {
                const el = ev.currentTarget;
                setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
              }}
              aria-live="polite"
            >
              {entries.length === 0 ? (
                <p className="dim">Nothing yet. Run step 1 and every command, request and response shows up here as it happens.</p>
              ) : entries.map((e) => <Line key={e.id} e={e} />)}
            </div>
            {!follow && <button className="jump" onClick={() => setFollow(true)}>Jump to latest</button>}
          </main>
        </div>
      )}
    </div>
  );
}
