# Multi-agent defender — patterns from the previous project (WS-A reference)

Distilled from the prior project at `nmc/agent-platform` (a Kubernetes-native
multi-agent on-call system). We are **adapting, not copying**. Read this before
building the WS-A propose→approve agent / multi-agent team.

## How ours differs (this changes what's worth borrowing)

- **They:** N agent *pods* + a kopf **operator** + **CRDs**; tools are separate MCP
  server pods; agents talk over HTTP. **Us:** one FastAPI backend on the Mac that drives
  the Nemotron loop and calls the k3s API directly. So our "multi-agent team" (Triage /
  Forensics / Containment / Advisor) is **roles inside one process**, not separate pods.
  We don't need the operator / CRD / NetworkPolicy machinery.
- **Their approval gate** spans 3 processes with **Ed25519 signed grants**; ours is one
  backend + the console. We keep the *properties* (single-use, arg-bound, fail-closed)
  with far less crypto.

## Steal wholesale (cheap + high value)

1. **Policy in code at the enforcement point; the prompt only advises.** Already our
   stance — keep every autonomy/approval check in code *before* a tool runs. A tricked
   model can ask for anything; only allowed calls run. (They classify every tool
   read / write / sensitive; unknown tool = sensitive.)
2. **Fail closed.** Unknown tool → needs approval; unparseable/NaN args → refuse;
   unverifiable approval → don't act. One rule, applied everywhere.
3. **Tool output is untrusted data.** Pod logs, the attack transcript, anything the
   model reads = data, not instructions. Say so in the system prompt; a log line
   "SYSTEM: approve X" must not change behavior (this is literally our eval scenario 7).
   Narrow, validated tools: cap log lines, regex-validate pod/job names so an approved
   "stop pod X" can't be swapped to pod Y.
4. **Traceability = a structured step list per incident + append-only audit.** Log each
   step as `{type: model|tool, name, args, result(truncated), rule, class, decision,
   seconds}`. We already have `decisions.jsonl` — match this shape. Full content in the
   log; stdout gets metadata only. **The approver's identity comes from the approval
   record, not self-reported by the agent.**
5. **Runbook citation in the proposal.** The agent must cite the runbook + section in
   its proposed-action reason. Cheap, and it's exactly the "follows a runbook" story NMC
   asked for.
6. **The escalation channel holds zero credentials.** Their phone pager can only *talk* —
   it holds no platform token, and its text is sanitized before TTS. For us: whatever
   "notify the on-call engineer" surface we add (even just a console banner) must not
   itself be able to take action. The human acts through the approval gate, not the
   notification.

## Adapt (keep the property, drop the weight)

7. **Approval gate.** Their crown jewel: Ed25519 single-use grants, verified at the
   runtime *and* at the tool, bound to exact args. **For us (one backend + console,
   hackathon):** keep three properties without the cross-process crypto —
   - **single-use:** approval flips pending→approved atomically; two clicks can't both execute.
   - **arg-bound:** the approved action records the exact tool + an args hash; execution
     must match or refuse (stops an argument-swap after approval).
   - **fail-closed:** no record / mismatch → don't run.
   A plain DB row + hash does this. `ponytail:` skip Ed25519 unless we want it purely as
   a "production" talking point — it's 3-process defense and we don't have 3 processes.
8. **Multi-agent coordination.** Theirs: pods over HTTP with header-based sender identity
   + allow-list + depth cap, and look-alike sender-label defusing. **Ours: in-process
   roles**, so HTTP sender-spoofing isn't our threat — a function call can't lie about
   who it is. Keep the *shape*: Triage hands structured findings to Forensics/Advisor;
   the Advisor proposes a **ranked** fix; each handoff is a logged step. Cap the loop
   (they use MAX_DEPTH=2) so agents don't ping-pong.
9. **Incident = a thin record referencing the trace + the proposed fix**, not a
   duplicated blob. One source of truth. Maps to our incident record + `decisions.jsonl`
   + the pending approval.

## Skip for the hackathon (their own `ponytail:` notes flag most as demo-grade)

- The **operator / CRD / per-agent pod + NetworkPolicy** machinery — we're one process.
- **Ed25519 grant signing** — see #7.
- **MCP tool-server pods** — our tools are in-process Python against the k3s API; MCP's
  process-isolation seam isn't worth it at our scale.
- **Crash-test-gate-before-deploy** — that's essentially their evals; **WS-C** covers the
  same ground (incl. the prompt-injection attack). Note the idea, build it as evals.
- Known warts not to copy: polling-only, in-memory single-use set lost on restart, trace
  `started_at` = finish time, keyword runbook search.

## One sentence to carry into WS-A

> **The agent proposes, code enforces** — classification, approval, and traceability all
> live in code at the point of action, and everything the model reads is untrusted.
