import { ASSET_STATUS, HEALTH, SEVERITY } from "../labels";
import type { AssetStatus, Health, HypothesisVerdict, Severity } from "../types";

// Confirmed = the bad thing is real (red); ruled out = good news (green).
const VERDICT: Record<HypothesisVerdict, { label: string; tone: string }> = {
  confirmed: { label: "Confirmed", tone: "exfil" },
  likely: { label: "Likely", tone: "high" },
  possible: { label: "Possible", tone: "invest" },
  ruled_out: { label: "Ruled out", tone: "clean" },
};

export function VerdictChip({ verdict }: { verdict: HypothesisVerdict }) {
  const v = VERDICT[verdict] ?? VERDICT.possible;
  return <span className={`chip t-${v.tone}`}>{v.label}</span>;
}

export function AssetChip({ status }: { status: AssetStatus }) {
  const s = ASSET_STATUS[status];
  return (
    <span className={`chip t-${s.tone}`}>
      <span className="glyph" aria-hidden>{s.glyph}</span>
      {s.label}
    </span>
  );
}

export function SeverityChip({ severity }: { severity: Severity }) {
  const s = SEVERITY[severity];
  return <span className={`chip t-${s.tone}`}>{s.label}</span>;
}

export function HealthChip({ health }: { health: Health }) {
  const h = HEALTH[health];
  return <span className={`chip t-${h.tone}`}>{h.label}</span>;
}

/** GPU utilization tone: calm until it is unusually high. */
export function utilTone(u: number): string {
  if (u >= 90) return "exfil";
  if (u >= 70) return "invest";
  return "clean";
}
