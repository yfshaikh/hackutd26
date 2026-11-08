// The attacker's "what am I getting out of this" view, wired to GET /attack/loot.
//
// Two live panels, both driven by the real drop-site and sink pod logs (parsed by
// backend/app/routes_loot.py — counts and entry names only, never file contents):
//   LOOT    progress bar + MB counter while the weights upload, then the zip entry
//           listing of the stolen .pt once the drop site confirms the final size.
//   VICTIM  the in-cluster sink's accepted-connection count climbing to the 200 cap.
//
// It polls once a second (short poll, like the rest of the attacker app). After a
// Reset the backend reports zeros, so both panels disappear on their own.
import { useEffect, useState } from "react";
import { API } from "./api";

export interface LootEntry { name: string; bytes: number }
export interface LootView {
  exfil: { bytes: number; total: number; done: boolean; entries: LootEntry[] };
  ddos: { connections: number; running: boolean };
}

const EMPTY: LootView = {
  exfil: { bytes: 0, total: 0, done: false, entries: [] },
  ddos: { connections: 0, running: false },
};

const MB = 2 ** 20;
const mb = (n: number) => (n / MB).toFixed(1);
const pct = (part: number, whole: number) => (whole > 0 ? Math.min(100, Math.round((part / whole) * 100)) : 0);

export default function LootPanel({ active }: { active: boolean }) {
  const [loot, setLoot] = useState<LootView>(EMPTY);

  useEffect(() => {
    if (!active) { setLoot(EMPTY); return; }
    let stop = false;
    const tick = async () => {
      try {
        const r = await fetch(API + "/attack/loot");
        if (!r.ok) return;
        const next = (await r.json()) as LootView;
        if (!stop) setLoot(next);
      } catch { /* backend down: keep the last view */ }
    };
    tick();
    const t = setInterval(tick, 1000);
    return () => { stop = true; clearInterval(t); };
  }, [active]);

  const { exfil, ddos } = loot;
  const showExfil = exfil.total > 0 || exfil.done;
  const showDdos = ddos.connections > 0 || ddos.running;
  if (!showExfil && !showDdos) return null;

  const exfilPct = exfil.done ? 100 : pct(exfil.bytes, exfil.total);
  return (
    <div className="loot">
      {showExfil && (
        <section className="loot-card">
          <header>
            <b>loot</b>
            <span>{exfil.done ? "weights exfiltrated" : "receiving model weights"}</span>
          </header>
          <div className="loot-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={exfilPct}>
            <i style={{ width: exfilPct + "%" }} />
          </div>
          <div className="loot-meta">
            <span>{mb(exfil.bytes)} / {mb(exfil.total)} MB</span>
            <span>{exfilPct}%</span>
          </div>
          {exfil.done && exfil.entries.length > 0 && (
            <div className="loot-entries">
              <div className="loot-entries-head">{exfil.entries.length} entries inside the stolen file</div>
              <ul>
                {exfil.entries.map((e) => (
                  <li key={e.name}><code>{e.name}</code><span>{mb(e.bytes)} MB</span></li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      {showDdos && (
        <section className="loot-card">
          <header>
            <b>victim</b>
            <span>sink.drop-site.svc · in-cluster only</span>
          </header>
          <div className="loot-count">{ddos.connections}<small> / 200 connections</small></div>
          <div className="loot-track" role="progressbar" aria-valuemin={0} aria-valuemax={200} aria-valuenow={ddos.connections}>
            <i className="hot" style={{ width: pct(ddos.connections, 200) + "%" }} />
          </div>
          <div className="loot-meta">
            <span>{ddos.running ? "flood in progress" : "flood finished"}</span>
            <span>{ddos.connections >= 200 ? "cap reached" : "bounded"}</span>
          </div>
        </section>
      )}
    </div>
  );
}
