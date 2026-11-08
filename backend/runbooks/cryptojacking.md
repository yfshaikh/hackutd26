# Cryptojacking (stolen GPU compute)

**Signals:** an unowned pod (no `owner` label) requesting `nvidia.com/gpu`; GPU utilization pinned near 100%; a process disguised with a benign name (`kube-sync`, `log-rotate`); miner strings (`xmrig`, `stratum+tcp`, matrix-multiply loops) in its logs.

**Severity:** high. Raise to critical if the same token also touched data (see data-exfiltration).

## Confirm
1. `list_pods` — find pods with `owner=none` and a GPU request.
2. `describe_pod` on each — record the image, command and which service account created it.
3. `get_pod_logs` — look for miner output or iteration counters.
4. `gpu_status` — confirm the utilization the pod is driving.
5. `mining_impact` — size the stolen compute in dollars for the record.

## Contain (in this order)
1. **RB-02 isolate:** `quarantine_pod` each rogue pod (deny-all NetworkPolicy cuts the pool connection). Autonomous.
2. **RB-01 contain:** `delete_pod` each rogue pod. Autonomous for unowned pods only.
3. Check for something that will recreate it — if a non-allowlisted CronJob exists, run the persistence runbook.
4. **RB-04 identity:** request `revoke_service_account` — the stolen token is the root cause. Needs human approval.

## Record
Set categories `cryptojacking`, `unauthorized-access`; vector = the exploited entry point + CVE; impact = $/hour from `mining_impact` × hours pinned.

## Done when
No unowned GPU pod, GPU back to baseline, revoke requested or approved.
