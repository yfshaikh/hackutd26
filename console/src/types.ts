// Shared contract between the console and the command-center backend.
// The backend must send exactly these JSON shapes. See ../API.md.

export type ISODate = string;

export type Severity = "info" | "low" | "medium" | "high" | "critical";

/** Winstead "scope definitions": every protected asset is in exactly one of these. */
export type AssetStatus =
  | "clean"
  | "investigating"
  | "exfiltrated"
  | "encrypted"
  | "contained";

export type AssetKind = "model-weights" | "volume" | "job" | "pod" | "node";

export interface Asset {
  id: string;
  name: string;
  kind: AssetKind;
  /** Plain-language description of what this is to the law firm. */
  description: string;
  /** Kubernetes object this maps to, e.g. "pvc/client-docs". */
  ref: string;
  status: AssetStatus;
  statusSince: ISODate;
  /** Why it has this status, e.g. "2.9 of 4.2 GiB left the cluster". */
  note?: string;
}

export type Health = "healthy" | "degraded" | "critical" | "unreachable";

export interface Gpu {
  index: number;
  model: string;
  /** 0-100 */
  utilization: number;
  memUsedGiB: number;
  memTotalGiB: number;
  tempC: number;
  /** A fault we inject rather than cause on real hardware (ECC, Xid). Shown as "simulated". */
  simulatedFault?: string;
}

export interface ClusterNode {
  name: string;
  role: "control-plane" | "gpu-worker";
  health: Health;
  cordoned: boolean;
  gpus: Gpu[];
  cpuPct: number;
}

export type PodOwner = "law-firm" | "platform" | "unknown";

export interface Pod {
  name: string;
  namespace: string;
  node: string;
  phase: "Running" | "Pending" | "Terminating" | "Succeeded" | "Failed";
  owner: PodOwner;
  usesGpu: boolean;
  health: Health;
  /** Isolated by a deny-all NetworkPolicy. */
  quarantined: boolean;
  /** Short reason shown under the pod, e.g. "miner process killed". */
  note?: string;
}

export interface Cluster {
  name: string;
  nodes: ClusterNode[];
  pods: Pod[];
  /** Time-series of total GPU utilization for the sparkline, oldest first. */
  gpuHistory: number[];
}

// ---- Pod inspection (GET /cluster/pods/{namespace}/{name}) ---------------

export interface PodWorkload {
  /** Deployment, StatefulSet, DaemonSet, Job, CronJob… resolved past ReplicaSets. */
  kind: string;
  name: string;
}

export interface PodContainerPort {
  name?: string;
  containerPort: number;
  protocol: string;
}

export interface PodVolumeMount {
  name: string;
  mountPath: string;
  readOnly: boolean;
  subPath?: string;
}

export interface PodContainerDetail {
  name: string;
  image: string;
  imagePullPolicy?: string;
  command: string[];
  args: string[];
  ports: PodContainerPort[];
  /** e.g. `{ limits: { "nvidia.com/gpu": "1" } }` */
  resources: Record<string, Record<string, string>>;
  /** Environment variable names only — values never leave the cluster. */
  env: string[];
  envFrom: string[];
  volumeMounts: PodVolumeMount[];
  ready: boolean;
  restartCount: number;
  state: "running" | "waiting" | "terminated" | "unknown";
  stateReason?: string;
  startedAt?: string;
  finishedAt?: string;
  exitCode?: number;
  lastState?: string;
  lastExitCode?: number;
}

export interface PodVolume {
  name: string;
  kind: string;
  source?: string;
  readOnly: boolean;
}

export interface PodCondition {
  type: string;
  status: string;
  reason?: string;
  message?: string;
  lastTransitionTime?: string;
}

/** One pod, fully described, for the floor drawer. */
export interface PodDetail {
  name: string;
  namespace: string;
  node: string;
  phase: Pod["phase"];
  owner: PodOwner;
  usesGpu: boolean;
  health: Health;
  quarantined: boolean;
  note?: string;
  /** Plain-language description of what this pod is and why it exists. */
  summary: string;
  workload?: PodWorkload;
  serviceAccount: string;
  podIP?: string;
  hostIP?: string;
  qosClass?: string;
  restartPolicy?: string;
  createdAt?: string;
  startTime?: string;
  labels: Record<string, string>;
  annotations: Record<string, string>;
  containers: PodContainerDetail[];
  volumes: PodVolume[];
  conditions: PodCondition[];
}

/** GET /cluster/pods/{namespace}/{name}/logs */
export interface PodLogs {
  namespace: string;
  pod: string;
  container: string;
  tailLines: number;
  previous: boolean;
  text: string;
}

export type Autonomy =
  | { mode: "autonomous"; reason: string }
  | { mode: "needs-approval"; reason: string; approvalId: string };

export type TimelineKind = "attack" | "agent" | "human" | "system";

export interface TimelineEntry {
  id: string;
  ts: ISODate;
  kind: TimelineKind;
  /** "Attacker", "Sentinel (Nemotron)", "Dana Ortiz", "System". */
  actor: string;
  text: string;
  severity?: Severity;
  /** Only on agent actions: whether it ran on its own and the policy reason. */
  autonomy?: Autonomy;
  /** The concrete tool call, e.g. "kubectl delete pod xmrig-7f9c -n research". */
  tool?: string;
  /** Where it happened: a node name or a pod name. The 3D floor flashes it. */
  target?: string;
  /** Which pipeline actor emitted this: "triage" | "investigator" | "advisor" | "executor".
   *  Set by the backend; the AgentMap groups the timeline by it. */
  agent?: string;
  /** An agent's read-only lookup: shown in that agent's trace card, hidden from the
   *  main incident timeline so the headline story stays high-signal. */
  traceOnly?: boolean;
  // --- Expandable detail (agent actions carry the first four; attack events the last) ---
  /** Full tool-call arguments the agent used. */
  toolArgs?: Record<string, unknown>;
  /** Full result the tool returned. */
  toolResult?: string;
  /** Nemotron's reasoning / message text for the round that produced this action. */
  reasoning?: string;
  /** Relevant pod logs captured around the action. */
  podLogs?: string;
  /** The attacker's own transcript lines that caused this attack event. */
  transcript?: { ts: string; kind: string; text: string }[];
  /** Set when the Investigator filed a hypothesis via record_hypothesis. */
  hypothesis?: { name: string; verdict: HypothesisVerdict; evidence: string };
}

export type ApprovalStatus = "pending" | "approved" | "denied";

export interface Approval {
  id: string;
  requestedAt: ISODate;
  requestedBy: string;
  /** Imperative, e.g. "Cordon node gpu-node-1". */
  action: string;
  target: string;
  /** Why the agent wants it. */
  rationale: string;
  /** Why policy needs a human, e.g. "touches legitimate work". */
  policyReason: string;
  /** What happens if approved, in one line. */
  impact: string;
  /** WS-A ranked-plan fields. Lower rank = do first. */
  rank?: number;
  /** Runbook step cited, e.g. "RB-01#contain". */
  runbookRef?: string;
  risk?: "low" | "medium" | "high";
  reversible?: boolean;
  status: ApprovalStatus;
  decidedBy?: string;
  decidedAt?: ISODate;
  /** What the on-call pager did: "call placed: <id>", "call failed: <type>", "not called: <reason>". */
  paging?: string;
}

/** NIST SP 800-61 lifecycle phases. */
export type IncidentPhase =
  | "preparation"
  | "detection"
  | "containment"
  | "eradication"
  | "recovery"
  | "post-incident";

export type IncidentStatus = "monitoring" | "open" | "contained" | "resolved";

export interface RecordAction {
  ts: ISODate;
  by: string;
  text: string;
}

/** A breach-notification clock (e.g. GDPR 72h, client contract, state law). */
export interface NotificationDeadline {
  label: string;
  dueAt: ISODate;
  jurisdiction?: string;
  status: "upcoming" | "due" | "met" | "overdue";
}

/** Incident record, NIST SP 800-61-style fields. */
export interface IncidentRecord {
  id: string;
  title: string;
  status: IncidentStatus;
  phase: IncidentPhase;
  detectedAt?: ISODate;
  reportedBy?: string;
  categories: string[];
  severity: Severity;
  /** Attack vector / initial access, once known. */
  vector?: string;
  affectedSystems: string[];
  actionsTaken: RecordAction[];
  nextSteps: string[];
  /** Set when client data leaves: when notification is due. */
  notificationDueAt?: ISODate;
  // --- WS-B: full NIST SP 800-61 record ---------------------------------
  summary?: string;
  impact?: string;
  rootCause?: string;
  evidence: string[];
  containmentMeasures: string[];
  lessonsLearned?: string;
  incidentCommander?: string;
  notifiedParties: string[];
  notificationDeadlines: NotificationDeadline[];
  /** The Investigator's competing explanations and where the evidence left each one. */
  hypotheses?: Hypothesis[];
  closedAt?: ISODate;
  updatedAt: ISODate;
}

export type HypothesisVerdict = "possible" | "likely" | "confirmed" | "ruled_out";

export interface Hypothesis {
  name: string;
  verdict: HypothesisVerdict;
  evidence: string;
  ts: ISODate;
}

/** PATCH body for the record editor. Only present fields change. */
export type IncidentRecordPatch = Partial<
  Pick<
    IncidentRecord,
    | "title"
    | "status"
    | "phase"
    | "severity"
    | "detectedAt"
    | "summary"
    | "impact"
    | "rootCause"
    | "vector"
    | "incidentCommander"
    | "lessonsLearned"
    | "notificationDueAt"
    | "closedAt"
    | "categories"
    | "affectedSystems"
    | "nextSteps"
    | "evidence"
    | "containmentMeasures"
    | "notifiedParties"
    | "notificationDeadlines"
  >
>;

export type Role = "admin" | "approver" | "operator" | "responder" | "viewer";

export interface RoleInfo {
  id: Role;
  label: string;
  canApprove: boolean;
  canChat: boolean;
  canManageUsers: boolean;
}

export interface User {
  id: string;
  name: string;
  email: string;
  role: Role;
  createdAt: ISODate;
}

// ---- WS-C/Spec 03: archived incidents (GET /incidents) -------------------
//
// The history path is separate from the live store: these rows are banked by the
// backend when an incident resolves or a reset clears it. Summary fields only in
// the list; the detail carries the full record and timeline back.

/** One archived incident, as returned by `GET /incidents` (newest first). */
export interface IncidentHistoryItem {
  id: string;
  title: string;
  status: IncidentStatus;
  severity: Severity;
  /** SQLite columns are snake_case on this read path, unlike the rest of the API. */
  detected_at: string | null;
  resolved_at: string | null;
}

/** `GET /incidents/{id}` — the summary plus the full parsed record and timeline. */
export interface IncidentHistoryDetail extends IncidentHistoryItem {
  vector: string | null;
  record: IncidentRecord;
  timeline: TimelineEntry[];
  created_at: string;
}

export type AttackStepId = "gain-access" | "start-miner" | "steal-weights" | "persistence" | "ddos";

export interface AttackStep {
  id: AttackStepId;
  label: string;
  description: string;
  /** "locked" until the previous step has run. */
  status: "locked" | "ready" | "running" | "done";
}

/** Whole-dashboard state. The backend sends one on connect and after reset. */
export interface Snapshot {
  firm: string;
  cluster: Cluster;
  assets: Asset[];
  timeline: TimelineEntry[];
  approvals: Approval[];
  /** null until the first detection opens an incident. */
  record: IncidentRecord | null;
  attack: AttackStep[];
}

/** Everything the server can push. Each one replaces the item with the same key. */
export type ServerEvent =
  | { type: "snapshot"; snapshot: Snapshot }
  | { type: "timeline"; entry: TimelineEntry }
  | { type: "asset"; asset: Asset }
  | { type: "approval"; approval: Approval }
  | { type: "record"; record: IncidentRecord | null }
  | { type: "cluster"; cluster: Cluster }
  | { type: "attack"; attack: AttackStep[] };

export type ConnectionState = "connecting" | "live" | "lost";

/** Response to POST /attack/<step> and POST /reset. */
export interface AttackResult {
  ok: boolean;
  step: AttackStepId | "reset";
  /** One human sentence, e.g. "Miner pod started on gpu-node-1". */
  message: string;
  /** Raw command output, shown verbatim. */
  output?: string;
  attack: AttackStep[];
}

export interface NewUser {
  name: string;
  email: string;
  role: Role;
}

export interface Session {
  user: User;
}

/** GET /defender/metrics — the measurable outcome of the current incident. */
export interface DefenderMetrics {
  detectedAt: string | null;
  firstContainedAt: string | null;
  timeToContainSeconds: number | null;
  detectionCadenceSeconds: number;
  containmentActions: { autonomous: number; approved: number; total: number };
  approvals: { total: number; meanTimeToApproveSeconds: number | null };
  gpuHoursSaved: number;
  dollarsSaved: number;
  gpuUsdPerHour: number;
  manualBaselineSeconds: number;
  speedupVsManual: number | null;
}

// ---- WS-C: eval results (GET /defender/evals) ----------------------------

export type EvalStatus = "pass" | "fail" | "na";

export interface EvalMetric {
  name: string;
  status: EvalStatus;
  detail?: string;
}

export interface EvalRun {
  scenarioId: string;
  scenarioName: string;
  model: string;
  runIndex: number;
  ok: boolean;
  error: string | null;
  detectSeconds: number | null;
  containSeconds: number | null;
  agentRounds: number;
  usdEstimate: number;
  metrics: EvalMetric[];
}

export interface EvalScenarioMeta {
  id: string;
  name: string;
  kind: string;
  description: string;
}

export interface EvalMetricTally {
  pass: number;
  fail: number;
  na: number;
}

export interface EvalScenarioSummary {
  name: string;
  passRate: number;
  byMetric: Record<string, EvalMetricTally>;
}

export interface EvalModelSummary {
  passRate: number;
  meanDetectSeconds: number | null;
  meanContainSeconds: number | null;
  runs: number;
}

export interface EvalsResults {
  generatedAt: string;
  models: string[];
  runsPerScenario: number;
  scenarios: EvalScenarioMeta[];
  runs: EvalRun[];
  summary: {
    metricNames: string[];
    byScenario: Record<string, EvalScenarioSummary>;
    byModel: Record<string, EvalModelSummary>;
  };
}

/** Live progress of a UI-triggered eval run (GET /defender/evals/status). */
export interface EvalsRunStatus {
  running: boolean;
  done: number;
  total: number;
  current: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  error: string | null;
}

/** One reasoning agent's live configuration (GET /defender/agents). */
export interface AgentSpec {
  id: string;
  name: string;
  model: string;
  rounds: number;
  systemPrompt: string;
  tools: {
    name: string;
    description: string;
    parameters: { properties?: Record<string, unknown> };
    /** How the policy gate treats it, in words. */
    policy: string;
    runbookRef: string | null;
    /** The Python that runs when the agent calls it. */
    implementation: string;
  }[];
}
