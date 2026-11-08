// Plain-English wording for the stakeholder Briefing page. The audience is the law firm's partners,
// not engineers: no pods, namespaces, tool names or CVE ids. Every translation lives here so the
// wording can be reviewed in one place.

import type { Approval, AssetStatus, IncidentRecord, Snapshot, TimelineEntry } from "./types";

export type Tone = "clean" | "invest" | "exfil" | "contained";

export interface Headline {
  title: string;
  tone: Tone;
}

/** One sentence that says where things stand. */
export function headline(s: Snapshot): Headline {
  const r: IncidentRecord | null = s.record;
  if (!r) return { title: "All clear. No active incident.", tone: "clean" };
  if (r.status === "resolved") return { title: "Resolved. The incident is closed.", tone: "clean" };
  if (r.status === "contained" || r.phase === "eradication" || r.phase === "recovery")
    return { title: "The attack is contained. Cleanup is underway.", tone: "contained" };
  return { title: "We are responding to an active attack on the firm's AI systems.", tone: "exfil" };
}

export const ASSET_PLAIN: Record<AssetStatus, { label: string; tone: string }> = {
  clean: { label: "Safe", tone: "clean" },
  investigating: { label: "Being checked", tone: "invest" },
  exfiltrated: { label: "Stolen", tone: "exfil" },
  encrypted: { label: "Locked", tone: "exfil" },
  contained: { label: "Secured", tone: "contained" },
};

// The backend's asset descriptions are written for engineers (file names, GPU models). Partners get these.
const ASSET_DESC: Record<string, string> = {
  "model-weights": "The firm's private AI model, trained on client contracts.",
  training: "The AI training work the firm is running right now.",
  notebook: "A researcher's workspace for building the firm's AI tools.",
  node: "The server that runs all of the firm's AI work.",
};

export const plainAssetDescription = (a: { id: string; description: string }) => ASSET_DESC[a.id] ?? "";

// The approval's `action` is the agent's tool call, e.g. "revoke_service_account()".
const ACTIONS: Record<string, string> = {
  revoke_service_account: "Cut off the stolen login the attacker is using",
  cordon_node: "Stop new work from starting on an affected server",
  delete_pod: "Shut down a program that belongs to the firm",
  delete_cronjob: "Remove a scheduled task the firm normally runs",
  quarantine_pod: "Isolate a program from the network",
};

const toolOf = (action: string) => action.split("(")[0].trim();

export function plainAction(a: Pick<Approval, "action">): string {
  return ACTIONS[toolOf(a.action)] ?? "Take a containment step that affects the firm's own systems";
}

/**
 * One timeline event as a sentence a partner understands, or null to leave it out. Hidden on
 * purpose: the attacker's own terminal, read-only lookups, agent handoffs and internal chatter.
 */
export function plainUpdate(e: TimelineEntry): string | null {
  if (e.traceOnly || e.kind === "attack") return null;
  const t = e.text;
  if (e.kind === "human") {
    const m = t.match(/^(Approved|Denied): (.*)\.$/);
    return m ? `${e.actor} ${m[1].toLowerCase()}: ${plainAction({ action: m[2] }).toLowerCase()}.` : null;
  }
  if (t.startsWith("Detection:")) {
    // One sentence per detection rule (backend/app/defender.py _detect), so two alerts never read the same.
    if (t.includes("mounts model-weights")) return "Unknown software is reading the firm's private AI model.";
    if (t.includes("GPU utilization")) return "The firm's AI servers are running at full power for that unknown software.";
    if (/cronjob/i.test(t)) return "We found a hidden scheduled task that nobody at the firm created.";
    return "We spotted unknown software running on the firm's AI servers.";
  }
  if (t.startsWith("Drop-site evidence")) return "Confidential model files were copied out of the firm. The client-notification clock has started.";
  if (t.startsWith("Executed approved action")) return "The approved step was carried out.";
  if (e.agent === "executor") {
    if (t.startsWith("quarantine_pod")) return "We cut the attacker's program off from the network.";
    if (t.startsWith("delete_cronjob")) return "We removed a hidden scheduled task the attacker planted.";
    if (t.startsWith("delete_pod")) return "We shut down the attacker's program.";
    return null;
  }
  if (e.autonomy?.mode === "needs-approval" && e.tool)
    return `A decision is waiting for an approver: ${plainAction({ action: e.tool }).toLowerCase()}.`;
  if (t.startsWith("Confirmed: all rogue")) return "We checked again: the attacker's programs are gone.";
  if (t.startsWith("Verification found residual")) return "Something the attacker left behind came back. We are removing it again.";
  if (e.hypothesis?.verdict === "confirmed") return `Our investigation confirmed ${plainScenario(e.hypothesis.name)}.`;
  return null;
}

// The Investigator's hypothesis names (= runbook ids), said the way a partner would say them.
const SCENARIOS: Record<string, string> = {
  cryptojacking: "the attacker was using the firm's computers to mine cryptocurrency",
  "data-exfiltration": "files were copied out of the firm",
  persistence: "the attacker planted a hidden task to come back later",
  "egress-flood": "the firm's servers were used to flood another organization's network",
};

export const plainScenario = (name: string) =>
  SCENARIOS[name.replace(/\s+/g, "-")] ?? "what the attacker was doing";
