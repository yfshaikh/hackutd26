// Who acts in this incident, in pipeline order. Mascots are HackUTD 2026 Zero Day art.
// The backend stamps every agent timeline entry with a real `agent` id (see
// backend/app/defender.py): the three Nemotron agents Triage -> Investigator -> Advisor
// reason, and the Executor identity applies the writes. agentOf() prefers that field
// and only falls back to kind/actor for the non-agent actors (attacker, detector, …).

import type { TimelineEntry } from "./types";

export type AgentId =
  | "attacker" | "cluster" | "detector"
  | "triage" | "investigator" | "advisor"
  | "people" | "executor";

export interface AgentInfo {
  id: AgentId;
  name: string;
  role: string;
  /** Mascot under /public/mascots, or null for people (initials instead). */
  img: string | null;
  tone: string;
  /** Label on the arrow to the next node. */
  edge?: string;
  /** One-paragraph "what this agent does", shown when you click it. */
  blurb?: string;
}

export const AGENTS: AgentInfo[] = [
  { id: "attacker", name: "Attacker", role: "Red team, live", img: "/mascots/raccoon.png", tone: "exfil", edge: "hits" },
  { id: "cluster", name: "Cluster", role: "GPU nodes + system", img: "/mascots/logo.png", tone: "contained", edge: "watched by" },
  { id: "detector", name: "Detector", role: "Rule-based watch", img: "/mascots/logo.png", tone: "invest", edge: "alerts" },
  { id: "triage", name: "Triage", role: "Nemotron · classify", img: "/mascots/cricket.png", tone: "invest", edge: "hands to",
    blurb: "First responder. Reads the alert and the live cluster, then sets the incident's severity, phase and category and hands off. Runs on the fast Nemotron model and only looks — it never changes the cluster." },
  { id: "investigator", name: "Investigator", role: "Nemotron · forensics", img: "/mascots/octocat-solo.png", tone: "invest", edge: "hands to",
    blurb: "Forensics. Digs through pod details and logs to map the scope — which assets were hit, and whether data was exfiltrated or persistence was planted. Also read-only." },
  { id: "advisor", name: "Advisor", role: "Nemotron · contain", img: "/mascots/panther.png", tone: "contained", edge: "proposes",
    blurb: "Containment lead. Takes the Triage and Investigator findings and proposes + runs the ranked fix. The only agent that can change the cluster, and risky actions still need a human to approve. Runs on the heavy Nemotron Ultra model." },
  { id: "people", name: "Responders", role: "Approve risky fixes", img: null, tone: "clean", edge: "approve" },
  { id: "executor", name: "Executor", role: "Write identity", img: "/mascots/pig.png", tone: "locked" },
];

// The three reasoning agents, for copy that names the pipeline.
export const REASONING_AGENTS: AgentId[] = ["triage", "investigator", "advisor"];

export const AGENT_BY_ID = Object.fromEntries(AGENTS.map((a) => [a.id, a])) as Record<AgentId, AgentInfo>;

export function agentOf(e: TimelineEntry): AgentId {
  // The backend stamps agent entries directly; trust that first.
  if (e.agent && e.agent in AGENT_BY_ID) return e.agent as AgentId;
  if (e.kind === "attack") return "attacker";
  if (e.kind === "human") return "people";
  if (e.kind === "agent") return "advisor"; // legacy entries without an agent field
  return e.actor === "Detector" ? "detector" : "cluster";
}

export const initials = (name: string) =>
  name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
