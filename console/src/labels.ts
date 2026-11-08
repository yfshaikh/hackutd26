// Plain-language labels and status styling, one place so wording stays consistent.

import type { AssetStatus, Health, IncidentPhase, IncidentStatus, Role, Severity } from "./types";

export const ASSET_STATUS: Record<AssetStatus, { label: string; glyph: string; tone: string; rank: number }> = {
  exfiltrated: { label: "Exfiltrated", glyph: "▲", tone: "exfil", rank: 0 },
  encrypted: { label: "Encrypted / locked", glyph: "■", tone: "locked", rank: 1 },
  investigating: { label: "Under investigation", glyph: "◐", tone: "invest", rank: 2 },
  contained: { label: "Contained", glyph: "◆", tone: "contained", rank: 3 },
  clean: { label: "Clean", glyph: "●", tone: "clean", rank: 4 },
};

export const SEVERITY: Record<Severity, { label: string; tone: string }> = {
  critical: { label: "Critical", tone: "exfil" },
  high: { label: "High", tone: "high" },
  medium: { label: "Medium", tone: "invest" },
  low: { label: "Low", tone: "contained" },
  info: { label: "Info", tone: "muted" },
};

export const HEALTH: Record<Health, { label: string; tone: string }> = {
  healthy: { label: "Healthy", tone: "clean" },
  degraded: { label: "Degraded", tone: "invest" },
  critical: { label: "Critical", tone: "exfil" },
  unreachable: { label: "Unreachable", tone: "muted" },
};

export const INCIDENT_STATUS: Record<IncidentStatus, { label: string; tone: string }> = {
  monitoring: { label: "Monitoring", tone: "clean" },
  open: { label: "Incident open", tone: "exfil" },
  contained: { label: "Contained", tone: "contained" },
  resolved: { label: "Resolved", tone: "clean" },
};

/** Status chip for a record. An unexpected value from the backend shows as-is instead of crashing the page. */
export const incidentStatus = (s: string) => INCIDENT_STATUS[s as IncidentStatus] ?? { label: s, tone: "muted" };

/** NIST SP 800-61 lifecycle, in order (this one really is a sequence). */
export const PHASES: { id: IncidentPhase; label: string }[] = [
  { id: "detection", label: "Detect" },
  { id: "containment", label: "Contain" },
  { id: "eradication", label: "Eradicate" },
  { id: "recovery", label: "Recover" },
  { id: "post-incident", label: "Review" },
];

export const ROLE: Record<Role, { label: string; can: string }> = {
  admin: { label: "Admin", can: "Everything, including adding users and changing roles" },
  approver: { label: "Approver", can: "Approve or deny the agent's proposed actions" },
  operator: { label: "Operator", can: "Post updates and edit the record and scope" },
  responder: { label: "Responder", can: "Approve actions, post updates, and edit the record" },
  viewer: { label: "Viewer", can: "Read only" },
};

export const ROLE_ORDER: Role[] = ["admin", "approver", "operator", "responder", "viewer"];

/** Who can approve/deny the agent's proposed actions. */
export const canAct = (r: Role | undefined) => r === "admin" || r === "responder" || r === "approver";

/** Who can post person-to-person chat and update the record/scope. */
export const canChat = (r: Role | undefined) => r === "admin" || r === "responder" || r === "operator";
export const canEditRecord = canChat;

export const RISK: Record<"low" | "medium" | "high", { label: string; tone: string }> = {
  low: { label: "Low", tone: "clean" },
  medium: { label: "Medium", tone: "invest" },
  high: { label: "High", tone: "exfil" },
};
