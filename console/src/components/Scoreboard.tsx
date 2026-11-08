// The measurable outcome, up top: how fast we contained it, how much ran autonomously, and the
// GPU compute protected. Polls GET /defender/metrics; only shows once an incident is detected.
import { useEffect, useState } from "react";
import { getMetrics } from "../api";
import type { DefenderMetrics } from "../types";

const fmtSecs = (s: number | null) =>
  s == null ? "—" : s < 90 ? `${s.toFixed(0)}s` : `${(s / 60).toFixed(1)}m`;

export function Scoreboard() {
  const [m, setM] = useState<DefenderMetrics | null>(null);
  useEffect(() => {
    let on = true;
    const load = () => getMetrics().then((d) => on && setM(d)).catch(() => {});
    load();
    const t = setInterval(load, 3000);
    return () => { on = false; clearInterval(t); };
  }, []);
  if (!m || !m.detectedAt) return null; // nothing to show before an incident

  const baselineMin = Math.round(m.manualBaselineSeconds / 60);
  const a = m.containmentActions;
  return (
    <section className="scoreboard" aria-label="Incident outcome">
      <div className="score-tile hero">
        <span className="score-val">{fmtSecs(m.timeToContainSeconds)}</span>
        <span className="score-label">time to contain</span>
        <span className="score-sub">
          {m.speedupVsManual ? `${m.speedupVsManual}× faster than ~${baselineMin}m manual` : `goal: beat ~${baselineMin}m manual`}
        </span>
      </div>
      <div className="score-tile">
        <span className="score-val">{a.autonomous}<i> / {a.approved}</i></span>
        <span className="score-label">containment actions</span>
        <span className="score-sub">autonomous / human-approved</span>
      </div>
      <div className="score-tile">
        <span className="score-val">{m.gpuHoursSaved.toFixed(2)}<i> h</i></span>
        <span className="score-label">GPU compute protected</span>
        <span className="score-sub">${m.dollarsSaved.toFixed(2)} saved · ${m.gpuUsdPerHour}/hr</span>
      </div>
      <div className="score-tile">
        <span className="score-val">{m.approvals.meanTimeToApproveSeconds != null ? fmtSecs(m.approvals.meanTimeToApproveSeconds) : "—"}</span>
        <span className="score-label">human decision time</span>
        <span className="score-sub">{m.approvals.total} approval{m.approvals.total === 1 ? "" : "s"} requested</span>
      </div>
    </section>
  );
}
