## Inspiration

In 2024 attackers found thousands of AI clusters with their dashboards open to the internet (the ShadowRay campaign). They used them to mine crypto on other people's GPUs, steal model weights, and later rent the boxes out as DDoS bots. GPU servers are now some of the most valuable machines a company owns, and the people who run them get paged at 3 a.m. to figure out what happened.

Then make the victim a law firm. Firms are starting to run private AI on their own documents, and a breach there isn't just downtime: it's client data walking out the door, a legal clock for notifying people, and partners who need answers while email and phones can't be trusted.

So I built the thing you'd want open during that incident: AI agents that do the investigating and the safe cleanup in seconds, a human still signing off on anything risky, and a command center the attacker can't reach. I didn't want a mock-up. I wanted a real attack, on a real GPU, that the judges launch themselves.

## What it does

Judges sit at a 3D "hacker laptop" and attack a real GPU cluster running a law firm's private AI. My defender stops them.

**The client in the demo is Winstead PC.** I modeled the cluster on what a firm like Winstead would run if it hosted its own legal AI. **The workloads are synthetic, but they run for real on a real NVIDIA GPU.** The model server does actual PyTorch inference on the T4, the training job runs an actual PyTorch training loop (forward pass, backpropagation, optimizer steps), and the weights file is a real 288 MB model checkpoint on a real disk. The only thing that isn't real is the content: the models aren't trained on Winstead's documents, and there's no client data anywhere. So the GPU contention, the slowdown when the miner hits, and the 288 MB leaving the cluster are all genuine.
- **Contracts AI** (`model-server`): a transformer served on the GPU, standing in for a contract model serving the firm's lawyers.
- **Fine-tuning** (`training`): a live GPU training loop, standing in for continuous fine-tuning on the firm's documents.
- **Research notebook** (`notebook`): a real JupyterLab where analysts would prototype. It's also the way in.
- **Model weights** (`contracts-ft-v3.pt`): a real checkpoint standing in for the firm's IP, a model trained on privileged client material. This is what gets stolen.

### The problems it solves

Each scenario below is one of the attacks the judges can launch, and each is an incident a data center team really faces.

- **Cryptojacking.** **When** an attacker hijacks the cluster's GPUs to mine crypto, **the on-call data center engineer** struggles to **notice and stop it** because the miner hides under an innocent name like `kube-sync`, nobody watches GPU graphs at 3 a.m., and the first sign is usually a customer's training job running slow. **My solution helps them** by catching the unknown pod pinning the GPU within one 4-second detection pass, then killing the miner automatically and pricing the stolen compute, **improving time-to-contain** (the scoreboard compares it with a 15-minute manual baseline) and **dollars of GPU time protected**.
- **Model-weight exfiltration.** **When** an attacker copies a customer's model weights out of the cluster, **the data center team** struggles to **say exactly what left and when** because the theft looks like a routine pod reading a volume, and there's no record tying the bytes to a destination. **My solution helps them** by flagging any pod other than the model server that mounts the weights, confirming the transfer from the drop server's own log ("302 MB left the cluster to the attacker's server"), marking the asset exfiltrated and starting the 72-hour notification clock, **improving time to an accurate, evidence-backed scope** (checked by the correct-scope eval).
- **Persistence.** **When** an attacker plants a CronJob that respawns the miner every minute, **the on-call engineer** struggles to **make the cleanup stick** because deleting the miner looks like a fix until it quietly comes back, often after the engineer has gone back to sleep. **My solution helps them** by flagging any CronJob that isn't on the allowlist, deleting it along with what it spawned, then re-scanning the cluster and sending the agent back if anything returned, **improving persistence removed and the miner staying gone** (checked by the persistence-removed eval).
- **DDoS from inside the cluster.** **When** an attacker turns the hijacked GPU box into a DDoS bot, **the data center team** struggles to **stop the outbound attack fast** because the flood comes from an ordinary-looking pod, and every minute it runs means abuse reports and liability toward a third party. **My solution helps them** by detecting the unowned pod, quarantining it with a deny-all network policy that cuts the flood within seconds, and then removing it, **improving time-to-contain** for an attack that hurts someone else.
- **The stolen identity behind all of them.** **When** every one of these attacks is launched through one stolen Kubernetes identity (the exposed notebook's token), **the on-call engineer** struggles to **fix the root cause safely** because revoking it also breaks the researchers who rely on that notebook, and they're away from their desk. **My solution helps them** by ranking revocation as the root-cause fix, holding it for a human, phoning them through Cartesia, and showing one Approve/Deny with the reasoning a click away, **improving root cause addressed with zero risky actions taken without approval** (checked by the root-cause and policy-compliance evals).

### The attack (all real, all on my own box)
1. **Gain access**: break into an exposed JupyterLab that has no password and steal the pod's Kubernetes identity.
2. **Start miner**: use that identity to launch a GPU pod disguised as `xmrig`. The firm's training job slows down.
3. **Steal weights**: launch a pod that mounts the model's disk and uploads the 288 MB weights file to an attacker server.
4. **Persistence**: plant a CronJob that respawns the miner every minute.
5. **DDoS**: turn the hijacked box against a victim server.

### The defense
- A **rule-based detector** checks the cluster every 4 seconds and wakes the AI only when something is wrong.
- **Three Nemotron agents** work the case in order. **Triage** classifies the incident. **Investigator** forms hypotheses, gathers evidence, looks up the exploited CVE on NVD and prices the stolen GPU time. **Advisor** writes a ranked containment plan and executes it: kill the miner, quarantine pods, delete the CronJob, revoke the stolen identity.
- **Guardrails.** The AI never holds an admin key. Safe, reversible actions run immediately. Risky ones become Approve/Deny cards, and Cartesia phones the on-call engineer.
- **The agents check their own work.** After containing, the backend re-scans the cluster. If the CronJob respawned the miner, the Advisor goes back in.
- **An out-of-band command center** for a firm whose email and phones are compromised.

### How the agents are designed

| Element | What I built |
|---|---|
| **Use case (templates)** | Incident response for GPU clusters. Each attack type has a **runbook** (cryptojacking, data exfiltration, egress flood, identity compromise, persistence, containment actions) that the agents pull with a `get_runbook` tool before acting. The same runbooks are readable in the console. |
| **Connectors** | Native function-calling tools, no MCP: the **Kubernetes API** (pods, logs, network policies, RBAC), **GPU telemetry** (`nvidia-smi`), **NVD** for CVEs, **CoinGecko** for the cost of stolen compute, and **Cartesia** for voice paging. Every external lookup falls back to cached data, so the demo still works offline. |
| **Knowledge base** | The runbooks, plus the live incident record and timeline, which every agent's handoff builds on. |
| **Hardware resources** | One Brev-rented AWS T4 VM. The NVIDIA device plugin time-slices it into 8 GPU slots for the firm's workloads (and the attacker). The models run on NVIDIA-hosted Nemotron, so the GPU stays the asset being defended. |
| **Trigger** | No chat box. The rule-based detector invokes the pipeline when it sees an unknown pod, a pod mounting the weights, an unexpected CronJob, or a GPU spike from an unknown pod. New findings in the same pass are batched into one run. |
| **Model** | **Nemotron 3 Ultra** for the Advisor, which plans and acts, and **Nemotron 3 Nano** for Triage and Investigator, which are fast and cheap. Temperature 0. |
| **Budget** | Round caps per agent (Triage 6, Investigator 8, Advisor 8). On the last round tools are withheld so the agent must answer. Verify gets at most 2 extra passes. Phone pages are capped at one per 2 minutes. The evals report model calls and estimated dollars per incident. |
| **Guardrails** | Per-agent tool allowlists, so only the Advisor can change anything. A policy check sorts every action into "run now" or "needs a human", and anything unrecognized needs a human. Two least-privilege Kubernetes identities with 1-hour tokens. Role-checked approvals, idempotent approval cards, failing closed if an identity is unavailable, and a prompt-injection test. |
| **System prompt** | One per agent, each with the scenario, its job, its tools and its rules (for example, the Investigator must state competing hypotheses and pick each next read to tell them apart, and the Advisor must pull the runbook first). All three are visible in the console's agent panel along with the model and tool list. |
| **Evaluations (reproducibility)** | An eval harness with **8 scenarios × 9 metrics**. Scenarios include benign look-alikes, a legitimate GPU spike, a prompt injection hidden in pod logs, and a dedicated **reproducibility** scenario that runs the full attack chain twice and compares the agents' decisions (temperature 0 keeps them consistent; any difference is measured). Metrics include time to detect and contain, persistence removed, root cause addressed, policy compliance, no collateral damage, correct scope, a valid record, and cost. The evals run from the UI. |

### For Winstead PC: the cyber incident response dashboard

| Required component | What I built |
|---|---|
| **01 Secure and isolated** | The command center runs **off the attacked cluster**, with its own login (scrypt-hashed passwords, HttpOnly session cookie), reached only over a private Tailscale tunnel. An attacker who fully owns the cluster still can't erase the record or approve an action. |
| **02 Access control** | Admins add people and assign roles (admin, approver, responder, operator, viewer). Roles are enforced on the server, not just hidden in the UI. |
| **03 Incident documentation** | A full **NIST SP 800-61** incident record that the agents and the team fill in live: summary, vector, affected systems, evidence, containment, actions taken, lessons learned. It's editable, exports to PDF, and runs **breach-notification countdowns**, with a 72-hour clock starting the moment exfiltration is confirmed. |
| **04 Scope definitions** | Every asset is **clean, under investigation, exfiltrated, encrypted/locked, or contained**, with the evidence behind it. Status is always color + symbol + word, so it reads under stress. |
| **05 Real-time communications** | An **out-of-band war room** chat that updates live, a **plain-English Briefing page** for partners (what happened, what needs your decision, the legal clock), and **Cartesia phone calls** to the on-call engineer when a decision is waiting. |

**Against the judging criteria:**
- **Security:** I assume the attacker controls everything inside: the cluster, the notebook, even the AI's inputs (I test a prompt injection). The dashboard, the record and the approval path live elsewhere, and the AI itself only ever holds narrowly scoped keys.
- **Ease of use:** one band at the top always answers "what do I do now?" Decisions are a single Approve/Deny with the reasoning one click away. Partners get the plain-English Briefing page instead of the technical console.
- **Creativity:** the judges attack the firm live, and AI agents do the forensics and fill in the incident record as it happens.

### For NVIDIA: Nemotron beyond a chatbot
- **Beyond a chatbot:** no one prompts the agents. A detector wakes them, and they take real, policy-gated actions on a live Kubernetes cluster.
- **Multi-step workflows:** three Nemotron agents plan and execute detect → scope → contain → verify, handing off to each other. The Advisor can consult the Investigator mid-run.
- **Tool integration:** the Kubernetes API, GPU telemetry, NVD, CoinGecko and Cartesia, each called when the evidence calls for it.
- **Real-world applicability:** GPU cryptojacking and model-weight theft are real attack classes (ShadowRay), and the defense uses real least-privilege patterns.

### For NMC²: keep the world running
- **Missed warnings:** a detector checks the cluster every 4 seconds and the agents act within seconds, so nobody has to catch a GPU graph at 3 a.m.
- **Unclear handoffs:** every agent's reasoning, tool call and handoff is on the timeline, and the incident record *is* the handoff to the next shift.
- **Wrong information at the wrong time:** operators get the technical console, partners get plain English, and the on-call engineer gets a phone call only when a human decision is actually needed.
- **The fleet keeps running:** the defender removes the attacker without touching the firm's real workloads, and the evals check exactly that.

## How I built it

- **The data center:** a Brev-rented AWS `g4dn.xlarge` with a Tesla T4, running **k3s**. The NVIDIA device plugin **time-slices** the one T4 into 8 GPU slots, so the model server, training job, telemetry and the attacker's miner all compete for it. The firm's workloads, the exposed notebook and the attacker's drop server are plain Kubernetes manifests.
- **Networking:** **Tailscale**. The vulnerable notebook is exposed only on my private tailnet, never the public internet, through a tiny `socat` relay pod.
- **The attack** runs Python inside the notebook's Jupyter kernel. That code reads the mounted service-account token and calls the Kubernetes API with plain `urllib`, exactly as a real intruder would.
- **The command center** is a **FastAPI** backend with server-sent events, running on my laptop, off the attacked box. It handles detection, the three-agent pipeline, the policy gate, approvals, the incident record and **SQLite** incident history.
- **The agents** run on **NVIDIA Nemotron 3** with tool calling. Their Kubernetes identities are two ServiceAccounts whose 1-hour tokens are minted in memory through the TokenRequest API.
- **Front ends:** **React + TypeScript + Vite** for the operator console (with a **three.js** 3D data-center floor) and the attacker's 3D laptop.

## Challenges I ran into

- **Making a real attack safe.** Everything runs on one box I control. The notebook is exposed only to my tailnet, and the DDoS target is hard-coded to an in-cluster server with capped connections. Along the way I found that the Brev image ships its own JupyterLab listening publicly with no token, so I turned it off.
- **Persistence beat my first defender.** Deleting the miner wasn't enough while the CronJob kept respawning it. That led to the verify-and-reconverge pass.
- **Agents repeating themselves.** The Advisor runs once per detection cycle and kept filing the same approval. I made approvals idempotent.
- **Misclassification.** Triage labeled incidents before it had looked at anything. Runbooks per attack type and evidence-first prompts fixed it.
- **Kubernetes timing.** A deleted GPU pod lingers for tens of seconds while it shuts down, which made the detector re-escalate attacks that were already handled.
- **Securing the defender itself.** Reviewing my own code, I found the agent clients could silently fall back to admin credentials. They now fail closed.

## Accomplishments that I'm proud of

- **Nothing is faked.** It's a real GPU, a real unauthenticated JupyterLab, real stolen-token API calls, and a real weights file leaving the cluster. When the defender revokes the identity, the attacker's terminal gets a real `403 Forbidden`.
- **The AI is genuinely boxed in.** It can propose anything, but RBAC and the policy gate decide what actually happens, and a human approves anything that touches legitimate work.
- **Judges can play it**, and the defender handles attacks in any order, including several at once.
- **I measured it** with an eval harness instead of trusting one good demo run.
- **I built it solo**: the cluster, the attack chain, the agents, the evals and both front ends.

## What I learned

- In Kubernetes, **"can create pods" is close to "owns the namespace."** A pod you create can mount any volume and run as any service account there.
- **Rules detect, AI reasons.** Cheap deterministic detection every few seconds, with expensive models only after a rule fires, is faster, cheaper and easier to trust.
- **Approval gates live in code, not in the cluster.** RBAC limits the blast radius, but "a human must approve" is enforced by my backend. That's why the backend runs off the attacked box.
- GPU time-slicing shares a card with **no isolation**, which is exactly why cryptojacking hurts real workloads.

## What's next for Zero Day Command Center

- Enforce approvals inside the cluster too, with admission policies and Pod Security, so even a compromised backend couldn't bypass them.
- Expose the agents' tools as MCP connectors, and let them search past incidents as a knowledge base.
- Detect the DDoS by actual network egress rather than "an unknown pod appeared".
- Watch the loot arrive and the victim get hammered live on the attacker's laptop.
- A ransomware scenario, so the scope board's "encrypted/locked" status gets exercised too.
- Stakeholder presence and task assignment in the war room ("who owns notifying the client?").
- Self-host Nemotron with NIM on the cluster's own GPUs, and run it across multiple nodes with network storage.
