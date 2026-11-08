# Gallery captions

Upload the PNGs in `png/` (Devpost's gallery doesn't take SVG). The SVGs are the editable sources; `generate.py` rebuilds them.

1. **01-system-overview.png**: The command center (attacker app, operator console and backend with three Nemotron agents) runs on my laptop, off the attacked box. It reaches the Brev GPU VM only through a private Tailscale tunnel, and calls Nemotron, NVD/CoinGecko and Cartesia from outside.

2. **02-inside-the-brev-vm.png**: One rented AWS T4 VM running single-node k3s. The law firm's model server, training job and exposed notebook share the GPU through 8 time-sliced slots, next to the operator's tools and the attacker's drop server and DDoS victim. Nothing leaves the VM.

3. **03-attack-path.png**: A judge clicks an attack. My backend sends Python into the unauthenticated Jupyter kernel, which reads the pod's mounted token and asks the Kubernetes API to create a miner, an exfil pod, a persistence CronJob or a DDoS pod. Revoking one RoleBinding turns every call into 403.

4. **04-defender-pipeline.png**: Cheap rules detect every 4 seconds. Three Nemotron agents then run in order: Triage (Nano) classifies, Investigator (Nano) builds evidence with CVE and cost lookups, Advisor (Ultra) contains. A verify pass re-checks the cluster and sends the Advisor back if anything respawned.

5. **05-guardrails.png**: The AI never holds an admin key. Every tool call passes a per-agent allowlist and a policy check. Safe, reversible fixes run immediately. Risky ones wait for a role-checked human approval, with Cartesia phoning the on-call engineer, and RBAC on the executor identity has the last word.

6. **06-three-mistakes.png**: The breach comes from three real misconfigurations: Jupyter with no auth, an auto-mounted token, and a Role that can create pods. Fixing any one stops the attack. Separate namespaces, admission policy and GPU quotas would have limited the damage further.

7. **07-law-firm-under-attack.png**: The client is Winstead PC. The workloads are synthetic but run for real on the T4: live PyTorch inference, a real training loop, and a real 288 MB checkpoint standing in for the firm's IP, with no client data anywhere. The scope board shows what happened to each: the weights were exfiltrated (starting the 72-hour notification clock), the notebook was contained, and the firm's real work stayed clean.

8. **08-winstead-brief-built.png**: Winstead's five required components (secure and isolated, access control, incident documentation, scope definitions, real-time comms) mapped to what the command center actually does, plus how it answers the three judging criteria: security, ease of use and creativity.
