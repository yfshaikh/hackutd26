# HackUTD 2026: design summary

One page. The full reasoning and the back-and-forth behind each decision are in [design-log.md](design-log.md).

## The project

A live **attacker vs. defender** exercise on real GPUs. An attacker compromises a GPU cluster that runs a law firm's private AI model. Defender agents built on **Nemotron** detect the attack, contain it, figure out what was taken, and document the incident. Humans approve anything risky. All of this is shown in a command center that runs **outside** the compromised machines.

At the judging table, **the judges play the attacker**.

## Tracks (up to 3)

| Track | What they want | How we hit it |
|---|---|---|
| **NMC²**: "Keep the world running" | Help data center teams stay one step ahead: missed warnings, unclear handoffs, wrong information at the wrong time | The GPU fleet keeps running through an attack, warnings are caught early, and the incident record is the handoff |
| **NVIDIA**: Nemotron beyond a chatbot | Multi-step workflows, tool integration, real-world use | Nemotron agents plan and carry out detect → contain → scope → document through real tools (Kubernetes API, GPU metrics, process and network data) |
| **Winstead PC**: cyber incident response dashboard | Secure and isolated, access control, incident documentation, scope definitions, real-time comms. Judged on security, ease of use under stress, creativity | The command center *is* that dashboard, and the law firm is the victim customer |

We dropped Photon, Spacetime, State Farm and T-Mobile. See the log for why.

## Architecture

```
  ┌──────────── Brev GPU box (the "data center", gets attacked) ───────────┐
  │  k3s Kubernetes + NVIDIA device plugin                                  │
  │   pods: law firm model server (GPU) · training job (GPU) · notebook     │
  │   attacker lands here → fake miner, weight theft, persistence           │
  └───────────────▲──────────────────────────────────────┬─────────────────┘
                  │ actions via Kubernetes API            │ telemetry: GPU metrics,
                  │ (quarantine, kill, block, cordon)     │ processes, network, k8s events
  ┌───────────────┴──────────────────────────────────────▼─────────────────┐
  │  Command center (separate machine, assumes the cluster is hostile)     │
  │   Nemotron defender agents · autonomy policy · approvals               │
  │   dashboard: live timeline, incident record, scope, chat, users        │
  │   attack panel (judges click) · reset button                           │
  └────────────────────────────────────────────────────────────────────────┘
```

- **Kubernetes runs the workloads that get attacked** (not the agents, as at HackTX). Defense happens through the Kubernetes API.
- **Nemotron** comes from NVIDIA's hosted API (build.nvidia.com). Self-hosting it is a stretch goal only.
- **The GPU is real** (Brev). Hardware faults we can't physically cause (ECC, Xid 79, fans) are injected and **labeled as simulated** in the UI.

## Attack scenarios (all real commands, on our own box only)

1. **Initial access**: an exposed notebook or a leaked key.
2. **Cryptojacking**: a GPU stress tool disguised as a miner. Never run real mining software.
3. **Exfiltration**: the law firm's fine-tuned model weights get copied out.
4. **Persistence**: a cron job or a rogue pod that brings the attacker back.

## Autonomy policy

> **Agents may take power away on their own. Anything that adds capacity, deletes data, or touches legitimate work needs a human.**

| Autonomous (reversible, hits only the attacker) | Human approval |
|---|---|
| Kill an unknown process or miner pod | Cordon or drain a node running real jobs |
| Quarantine a pod with a NetworkPolicy | Rotate secrets that live services use |
| Block an attacker IP | Delete anything, wipe a node |
| Snapshot evidence | Notify clients or regulators |

Every decision shows its reason on screen.

## Winstead's components, staged

| Component | Now | Later |
|---|---|---|
| Secure and isolated | Command center runs off the attacked box | Survives a fully compromised cluster |
| Real-time comms | Live timeline shared by agents and humans | Chat between people |
| Incident documentation | Record auto-built as agents act | NIST 800-61 fields, PDF export |
| Scope definitions | Per-asset status (exfiltrated, encrypted, clean) | Breach-notification deadline countdowns |
| Access control | One admin can add users | Roles |

## Demo

- **The judge is the attacker**, using the attack panel (4–5 buttons). The defense visibly wins within about 60 s. Reset takes about 30 s between judges.
- **Three 90-second routes, one per sponsor:**
  - NMC²: operations survive the attack.
  - Winstead: incident record, scope, isolation.
  - NVIDIA: Nemotron's plan and its tool calls.
- **Evals**: score the agents on scripted incidents (for example, "found the root cause in 10 of 12"). The NMC² judges asked for this at HackTX.

## Cut list (first to go)

1. An AI attacker (keep the scripted one)
2. 3D data center view (fall back to a 2D floor map)
3. Winstead "later" column
4. Self-hosted Nemotron

## Setup checklist

- [ ] Read the HackUTD rules on prior work and pre-event prep
- [ ] Dry run: k3s on a Brev box, device plugin, a pod that runs `nvidia-smi`
- [ ] Get a Nemotron API key from build.nvidia.com and make one tool call
- [ ] Check Brev's terms on running attack simulations on your own instance
