import { ASSET_STATUS, HEALTH, SEVERITY } from "../labels";
import type { AssetStatus, Health, Severity } from "../types";

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
