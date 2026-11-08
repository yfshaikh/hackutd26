"""Pydantic models mirroring console/src/types.ts exactly (camelCase fields).

FastAPI serializes these to JSON with the field names as written, so the
names here are the wire contract. Do not rename without updating types.ts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel

Severity = Literal["info", "low", "medium", "high", "critical"]
AssetStatus = Literal["clean", "investigating", "exfiltrated", "encrypted", "contained"]
AssetKind = Literal["model-weights", "volume", "job", "pod", "node"]
Health = Literal["healthy", "degraded", "critical", "unreachable"]
PodOwner = Literal["law-firm", "platform", "unknown"]
TimelineKind = Literal["attack", "agent", "human", "system"]
ApprovalStatus = Literal["pending", "approved", "denied"]
IncidentPhase = Literal[
    "preparation", "detection", "containment", "eradication", "recovery", "post-incident"
]
IncidentStatus = Literal["monitoring", "open", "contained", "resolved"]
Role = Literal["admin", "approver", "operator", "responder", "viewer"]
AttackStepId = Literal["gain-access", "start-miner", "steal-weights", "persistence", "ddos"]
AttackStepStatus = Literal["locked", "ready", "running", "done"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Asset(BaseModel):
    id: str
    name: str
    kind: AssetKind
    description: str
    ref: str
    status: AssetStatus
    statusSince: str
    note: Optional[str] = None


class Gpu(BaseModel):
    index: int
    model: str
    utilization: float
    memUsedGiB: float
    memTotalGiB: float
    tempC: float
    simulatedFault: Optional[str] = None


class ClusterNode(BaseModel):
    name: str
    role: Literal["control-plane", "gpu-worker"]
    health: Health
    cordoned: bool
    gpus: list[Gpu]
    cpuPct: float


class Pod(BaseModel):
    name: str
    namespace: str
    node: str
    phase: Literal["Running", "Pending", "Terminating", "Succeeded", "Failed"]
    owner: PodOwner
    usesGpu: bool
    health: Health
    quarantined: bool
    note: Optional[str] = None


class Cluster(BaseModel):
    name: str
    nodes: list[ClusterNode]
    pods: list[Pod]
    gpuHistory: list[float]


class Autonomy(BaseModel):
    mode: Literal["autonomous", "needs-approval"]
    reason: str
    approvalId: Optional[str] = None


class TranscriptRef(BaseModel):
    """A line from the attacker's own transcript, shown on the defender's attack entries."""
    ts: str
    kind: str          # cmd | code | http | output | note
    text: str


class TimelineEntry(BaseModel):
    id: str
    ts: str
    kind: TimelineKind
    actor: str
    text: str
    severity: Optional[Severity] = None
    autonomy: Optional[Autonomy] = None
    tool: Optional[str] = None
    target: Optional[str] = None
    # Which actor in the pipeline emitted this: one of the three reasoning agents
    # (triage|investigator|advisor) or the write identity (executor). The console
    # groups the timeline by this instead of guessing from kind/actor/tool.
    agent: Optional[str] = None
    # True for an agent's read-only lookup (list_pods, get_pod_logs, …): it shows in
    # that agent's trace so the investigation is visible, but is kept OUT of the main
    # incident timeline so the headline story stays high-signal.
    traceOnly: Optional[bool] = None
    # --- Task 3: expandable detail -----------------------------------------
    # On agent actions: the full tool call and result, plus Nemotron's reasoning
    # for that round, and relevant pod logs. On attack events: the attacker
    # transcript lines that caused it.
    toolArgs: Optional[dict] = None
    toolResult: Optional[str] = None
    reasoning: Optional[str] = None
    podLogs: Optional[str] = None
    transcript: Optional[list[TranscriptRef]] = None


class Approval(BaseModel):
    id: str
    requestedAt: str
    requestedBy: str
    action: str
    target: str
    rationale: str
    policyReason: str
    impact: str
    # WS-A ranked-plan fields: let the console render proposed actions as a ranked
    # remediation plan (sort by rank) with a cited runbook step. Optional so older
    # approvals and non-plan callers still validate.
    rank: Optional[int] = None
    runbookRef: Optional[str] = None
    risk: Optional[Literal["low", "medium", "high"]] = None
    reversible: Optional[bool] = None
    status: ApprovalStatus
    decidedBy: Optional[str] = None
    decidedAt: Optional[str] = None


class RecordAction(BaseModel):
    ts: str
    by: str
    text: str


class NotificationDeadline(BaseModel):
    """A breach-notification clock (e.g. GDPR 72h, client contract, state law)."""

    label: str
    dueAt: str
    jurisdiction: Optional[str] = None
    status: Literal["upcoming", "due", "met", "overdue"] = "upcoming"


class IncidentRecord(BaseModel):
    id: str
    title: str
    status: IncidentStatus
    phase: IncidentPhase
    detectedAt: Optional[str] = None
    reportedBy: Optional[str] = None
    categories: list[str] = []
    severity: Severity = "info"
    vector: Optional[str] = None
    affectedSystems: list[str] = []
    actionsTaken: list[RecordAction] = []
    nextSteps: list[str] = []
    notificationDueAt: Optional[str] = None
    # --- WS-B: full NIST SP 800-61 record (all additive/optional) -----------
    summary: Optional[str] = None
    impact: Optional[str] = None
    rootCause: Optional[str] = None
    evidence: list[str] = []
    containmentMeasures: list[str] = []
    lessonsLearned: Optional[str] = None
    incidentCommander: Optional[str] = None
    notifiedParties: list[str] = []
    notificationDeadlines: list[NotificationDeadline] = []
    closedAt: Optional[str] = None
    updatedAt: str


class IncidentRecordPatch(BaseModel):
    """PATCH body for the record editor. Only fields present in the request change."""

    title: Optional[str] = None
    status: Optional[IncidentStatus] = None
    phase: Optional[IncidentPhase] = None
    severity: Optional[Severity] = None
    detectedAt: Optional[str] = None
    summary: Optional[str] = None
    impact: Optional[str] = None
    rootCause: Optional[str] = None
    vector: Optional[str] = None
    incidentCommander: Optional[str] = None
    lessonsLearned: Optional[str] = None
    notificationDueAt: Optional[str] = None
    closedAt: Optional[str] = None
    categories: Optional[list[str]] = None
    affectedSystems: Optional[list[str]] = None
    nextSteps: Optional[list[str]] = None
    evidence: Optional[list[str]] = None
    containmentMeasures: Optional[list[str]] = None
    notifiedParties: Optional[list[str]] = None
    notificationDeadlines: Optional[list[NotificationDeadline]] = None


class RoleInfo(BaseModel):
    id: Role
    label: str
    canApprove: bool
    canChat: bool
    canManageUsers: bool


class SetRoleBody(BaseModel):
    role: Role


class ScopePatch(BaseModel):
    status: AssetStatus
    note: Optional[str] = None


class User(BaseModel):
    id: str
    name: str
    email: str
    role: Role
    createdAt: str


class AttackStep(BaseModel):
    id: AttackStepId
    label: str
    description: str
    status: AttackStepStatus


class Snapshot(BaseModel):
    firm: str
    cluster: Cluster
    assets: list[Asset]
    timeline: list[TimelineEntry]
    approvals: list[Approval]
    record: Optional[IncidentRecord] = None
    attack: list[AttackStep]


class AttackResult(BaseModel):
    ok: bool
    step: str
    message: str
    output: Optional[str] = None
    attack: list[AttackStep]


class NewUser(BaseModel):
    name: str
    email: str
    role: Role


class Session(BaseModel):
    user: User


class LoginBody(BaseModel):
    email: str
    password: str


class MessageBody(BaseModel):
    text: str
