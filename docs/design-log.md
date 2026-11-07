# HackUTD 2026: design log

The full context behind [design-summary.md](design-summary.md): the background, every track we considered, the back-and-forth, and why each decision went the way it did. The point is to keep this discussion so later sessions (and I) don't redo it.

Written 2026-11-07, during HackUTD 2026.

---

## 1. Background

### HackTX 2026: what happened last time

- **Project:** Heatsink. It was two things:
  - a **platform for building agents**: describe one in plain English, crash-test it, deploy it on Kubernetes;
  - **incident response for GPUs**: when a GPU breaks at 3am, the agents work it and call you.
- **Stack:**
  - a kind cluster, a kopf operator, and Agent and Tool CRDs;
  - a FastAPI platform API, MCP tool servers, Postgres;
  - Ed25519-signed approval grants, NetworkPolicies, RBAC;
  - a real GPU on Brev, and on-call phone calls through Cartesia.
- **Demo:** mostly incident response. A GPU ran out of memory, the agents were alerted and responded, and the on-call engineer got called. The agent-builder side was barely shown.
- **Result:** honorable mention in NMC². The NMC² judges said they wanted **evals** and **better logs**. They liked the use of Kubernetes.
- **Things that went wrong:**
  - Venue Wi-Fi blocked SSH to Brev, so we used a Cloudflare tunnel instead.
  - The on-call phone call never rang because there was no cell service; it went to voicemail.
- **An earlier conversation with the NMC² judges:** I pitched agents that provision GPU clusters for training jobs. **They pushed back**: they don't want agents to have that much control.
- **HackUTD 2025:** DataDriver (Flask + LangChain + Nemotron) won **both** NMC² and NVIDIA. NVIDIA rewards heavy use of Nemotron.

### Ground rules

- **No code from Heatsink.** It would break the rules, and I don't want to anyway. What carries over is what I *learned*: operators, CRDs, NetworkPolicies, signed approvals (there's a 9-lesson Kubernetes course in `nmc/k8s-course`).
- The NMC² judges will probably be the same people as at HackTX. **The project must not look like a repeat.**
- **Judging works like this:** judges walk around. Some are volunteers, some are from sponsors. With luck, the NMC², Winstead and NVIDIA judges each come by **separately**, so I can demo different parts to each.

---

## 2. Tracks at HackUTD 2026

I can enter **up to 3** tracks with one project.

| Track | Brief | Prize |
|---|---|---|
| **NMC²** | "Keep the World Running." Data center teams: a missed warning, an unclear handoff, or the wrong information at the wrong time turns a small issue into a major disruption. Build something that helps them stay one step ahead. | (not on slide) |
| **NVIDIA** | "Use Nemotron beyond a chatbot." Must include: beyond a chatbot (not just answering prompts), multi-step workflows (agents that plan and carry out complex tasks), tool integration (external APIs used intelligently), real-world applicability. | 1st: 2× RTX 5080 + $200 Brev credits. 2nd: 1× RTX 5080 + $200 Brev + swag. $60 Brev credit for everyone. |
| **Winstead PC** | Cyber incident response dashboard, a "command center" during and after an incident. **Required components:** (1) secure and isolated, working inside a possibly compromised network; (2) access control, with an admin who can add people; (3) incident documentation that follows standards, with real-time updates and status; (4) scope definitions: what data was compromised and its status (locked by ransomware, exfiltrated, etc.); (5) real-time communications in the dashboard. **Judging:** security (assume the attacker has access to all internal systems), ease of use under stress (people won't remember tutorials), creativity. | $1,500 / $900 / $300 |
| Photon | Human-in-the-loop texting and voice (iMessage, SMS, RCS, WhatsApp, Telegram, email, phone calls). Must use the Photon 2.0 API. Judged on vision, craft, depth, traction, heavy use of Photon. | $700 winner / $300 runner-up / $400 voice-call prize |
| Spacetime | A reactive backend (the database runs the server logic and streams changes). Spacetime must power the app's **primary functionality**. Also a separate ScrabbleBot tournament. | $2,048 / $1,024 / $512 (main) |
| State Farm | "The Worst Day, at Scale": disaster response, find those with the most urgent needs | Beats, a drone, a monitor |
| T-Mobile | "Safe Signal": protect customers from scams in new ways. Synthetic data only. | (not on slide) |

Event-wide themes: **trust** in technology, and standing up to oppressive surveillance.

---

## 3. How we got here (decisions in order)

### 3.1 First pass: NMC², NVIDIA, and probably Photon

**First recommendation:** pick tracks whose criteria can all be met by **one** project.
- NMC² and NVIDIA were the obvious core: I know the domain, and DataDriver won both last year.
- Photon looked like the best third: approvals by text message are exactly "human-in-the-loop," and iMessage works over Wi-Fi, which fixes the HackTX phone failure.

**Rejected:**
- **Spacetime.** It has to *be* the backend, so we'd be building two stacks in 24 hours. It can handle complex apps, but only by replacing everything else.
- **State Farm and T-Mobile.** Different domains; supporting them would pull the project apart.
- **Winstead, at first.** It looked too much like Heatsink. *This was reversed later (3.6).*

### 3.2 How to differentiate from Heatsink

- **First framing (mine):** Heatsink was "a platform for building agents," so this one is "the thing operators use at 3am."
- **Correction (yours):** Heatsink *also* did incident response, and that was the demo.
- **So:** depth alone isn't enough. The project needs something Heatsink didn't have. That turned out to be the **attacker vs. defender** angle (3.5).

**What this means in practice:**
- Don't lead with Kubernetes, CRDs, or an agent builder.
- Lead with the incidents.
- Ship **evals**, which is what the NMC² judges asked for.
- Tell the judges openly: "Last time you asked for evals and better logs. Here they are."

### 3.3 Nemotron: hosted, not self-hosted

- **I first suggested** running k3s on the Brev box with the NVIDIA GPU Operator and serving Nemotron inside the cluster with vLLM or NIM.
- **Your concern:** you'd spend the whole hackathon configuring it, and you doubted the judges would care.
- **Honest answer:** you were right. Self-hosting is mostly a story (privacy, an NVIDIA model on NVIDIA hardware). NVIDIA's criteria don't mention it, and it could eat 4–8 hours.
- **Decision:** use **NVIDIA's hosted Nemotron API (build.nvidia.com)**. It's free, OpenAI-compatible, and needs no setup. Self-hosting goes last on the cut list.

### 3.4 Real GPU vs. simulated, and Brev vs. Jetson

- **Your position:** real GPUs beat simulated data, as at HackTX. **Agreed.**
- **What's new:** use **pre-built defender agents**, not an agent builder.
- **What a rented GPU can't do:** ECC errors (bit flips in memory), Xid 79 (the GPU drops off the PCIe bus) and fan failure are **physical**. Software can't trigger them even on hardware you own. On Brev you also only get a virtual machine, with no access to fans or power.
- **What we can cause:**
  - out-of-memory errors,
  - runaway processes,
  - power caps (`nvidia-smi -pl`),
  - clock throttling,
  - every attack in 3.5.
- **For the rest:** inject them (DCGM may have a field-injection test mode, `dcgmi test --inject`; not yet confirmed) and **label them as simulated** in the UI. Being upfront fits the trust theme.
- **Jetson:**
  - It's an edge board with no full nvidia-smi or DCGM, so it reads as a hobby board to data-center judges.
  - Its only advantage: real physical failure on stage, like pulling the power cable or covering the fan.
  - **Decision:** Brev is the data center. Use a Jetson as a stage prop only if I already own one.

### 3.5 The attacker vs. defender idea (the core)

- **Origin:** I mentioned cryptojacking as an incident example. You turned it into a **hacker who tries to compromise the defender's GPUs, done for real**.
- **Why it works:**
  - It's the thing Heatsink didn't have.
  - It's real (actual processes and network traffic).
  - It ties all three tracks together.
- **Attack chain**, all real commands on our own firewalled box:
  1. initial access: an exposed notebook or a leaked key;
  2. a fake miner: a GPU stress tool renamed to look like `xmrig`;
  3. stealing the model weights;
  4. persistence: a cron job or a rogue pod.
- **Safety rules:**
  - Never run real mining software.
  - Attack only our own instance, and firewall it to the attacker.
  - Check Brev's terms first.
- **The attacker is a script**, so the live demo is repeatable. A Nemotron-driven attacker is a stretch goal.

### 3.6 Winstead instead of Photon

- **Your argument:** Winstead's components (isolation, access control, documentation, scope, comms) aren't overhead. They make the project more real-world, which also helps NMC² and NVIDIA.
- **My pushback:** partly agreed. The cost is **demo time**, not fit: an admin screen for adding users is invisible in a 4-minute demo.
- **What flipped it:** the attack. Winstead's "assume the attacker has access to all internal systems" becomes the architecture: the GPU cluster is compromised, so the command center runs **somewhere else**.
- **The law firm:** I first said a breached law-firm model would add a "third domain." **You were right that it doesn't.** It's the same domain (GPU incident response) with a specific customer: the attacker steals model weights fine-tuned on privileged client files, which starts the breach-notification clock. That makes it personal to Winstead for free.
- **Decision:** tracks are **NMC², NVIDIA, Winstead**. Photon is dropped. (We can still use texting for out-of-band alerts if time allows; we just don't enter that track.)

### 3.7 Kubernetes: a new role

- **At HackTX** Kubernetes ran the agents, and the NMC² judges liked it.
- **This time** Kubernetes runs the **workloads that get attacked and defended**: the law firm's model server, a training job, a notebook, all as pods on k3s on Brev. The defenders act through the Kubernetes API:
  - quarantine a pod with a NetworkPolicy,
  - cordon a node,
  - kill the miner pod,
  - rotate a secret.
- That's how real GPU data centers run, and it's not a repeat.
- **The agents** are plain processes in the command center, which runs off the attacked box.

**How a pod gets a GPU (three layers):**
1. **The NVIDIA driver** lets the operating system talk to the GPU. Brev includes it.
2. **The NVIDIA Container Toolkit** lets containers see the GPU. Containers are normally sealed off from hardware, and the toolkit passes the GPU through. Brev images usually include it.
3. **The NVIDIA device plugin** tells Kubernetes the GPU exists, so the node advertises `nvidia.com/gpu: 1` and pods that request it get scheduled there. It installs with one `kubectl apply`.

k3s detects the toolkit when it starts and configures itself to use it. Setup: install k3s, apply the plugin, run a test pod that prints `nvidia-smi`. About 1–2 hours, so do it first.

### 3.8 Autonomy: where the line is

- **Context:** the NMC² judges rejected agents that provision clusters because that **adds** power and spends money.
- **Rule:**

  > **Agents may take power away on their own. Anything that adds capacity, deletes data, or touches legitimate work needs a human.**

- **Autonomous** (reversible, affects only the attacker): kill an unknown process or miner pod, quarantine a pod with a NetworkPolicy, block an attacker IP, snapshot evidence.
- **Human approval:** cordon or drain nodes running real jobs, rotate secrets live services use, delete anything or wipe a node, notify clients or regulators.
- **This matches real security operations:** automation contains the threat and buys time, and humans decide the cleanup.
- **In the demo,** show the policy and the **reason for each decision** on screen. It shows the NMC² judges we listened.

### 3.9 The demo: judges play the attacker

- **Your idea:** the "game" is the demo. **Judges are the attacker**, and they watch the defender agents respond live.
- **My pushback on calling it a game:** operators don't want a game. A **3D data center view** that shows where the attack is happening is fine, but it's a stretch goal (start around hour 16; a 2D floor map is the fallback).
- **The attack panel:** judges get 4–5 buttons, **never a real shell**. Each button runs a real attack step.
- **The reset button:** restores the cluster in about 30 s, since judges arrive one after another.
- **The defense must visibly win within about 60 s.**
- **Three 90-second routes,** one per sponsor:
  - **NMC²:** GPU operations survive the attack, warnings are caught early, the incident record is the handoff.
  - **Winstead:** isolation, the incident record, scope, comms, access control.
  - **NVIDIA:** Nemotron's plan, its multi-step tool calls, its reasoning.

### 3.10 Winstead components: core first, the rest staged

- **Your plan:** keep attacker vs. defender as the core. Add Winstead's components as they make sense.
- **Caveat:** Winstead calls them **required**, so all five need at least a minimal version to qualify. Stage them by depth instead of leaving any out:

| Component | Now | Later |
|---|---|---|
| Secure and isolated | Command center off the attacked box | Survives a fully compromised cluster |
| Real-time comms | Live timeline for agents and humans | Chat between people |
| Incident documentation | Record auto-built as agents act | NIST 800-61 fields, PDF export |
| Scope definitions | Per-asset status (exfiltrated, encrypted, clean) | Breach-notification deadline countdowns |
| Access control | One admin can add users | Roles |

---

## 4. Ideas set aside (and why)

| Idea | Why not (for now) |
|---|---|
| Reusing Heatsink code | Against the rules; it's a fresh build |
| Amazon EKS | New AWS accounts usually have zero GPU quota, and raising it takes days. Creating a cluster takes 15–20 min, venue Wi-Fi is unreliable, and judges never see where it runs. |
| Self-hosted Nemotron (k3s, GPU Operator, vLLM or NIM) | Hours of setup for little judge value. Last on the cut list. |
| Photon track | Replaced by Winstead after the attack idea. Texting may still appear without entering the track. |
| Spacetime | Must be the primary backend, so it would mean two stacks |
| A Jetson as the main hardware | Edge board, reads as a hobby. A prop at most. |
| A "game" framing | Operators don't want a game. It's a demo mechanic plus an optional 3D view. |
| An AI attacker | Not repeatable live. Stretch goal. |
| Forcing the anti-surveillance theme | Feels forced. "Trust" fits naturally: explained, signed, human-approved, auditable actions. |

---

## 5. Cut list (first to go when time runs short)

1. An AI attacker (keep the scripted one)
2. 3D data center view (use a 2D floor map)
3. Winstead's "later" column
4. Self-hosted Nemotron

## 6. Setup checklist

- [ ] Read the HackUTD rules on prior work and preparing before the event
- [ ] Dry run: k3s on a Brev box, then the device plugin, then a pod that runs `nvidia-smi`
- [ ] Get a Nemotron API key from build.nvidia.com and make one tool call
- [ ] Check Brev's terms on attack simulations against your own instance
- [ ] Plan around venue Wi-Fi (HackTX: SSH blocked, so a Cloudflare tunnel)

## 7. How I want to work on this

- I need to **understand** the networking, Brev, and running Kubernetes GPU jobs on Brev well enough to explain them to judges.
- There are three modes, and I'll say which one:
  1. **Step by step:** do it with me and explain each step.
  2. **Autonomous:** just build it.
  3. **Autonomous, then explain:** build it, then make an artifact that explains how it works.
