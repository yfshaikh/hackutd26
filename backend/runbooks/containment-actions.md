# Containment actions (RB-01 … RB-05)

The individual actions the scenario runbooks call for. The approval cards in the console cite these ids. The backend's policy gate decides whether each runs on its own or waits for a human — the agent cannot override it.

## RB-01 contain — `delete_pod`
Terminates a pod. **Autonomous** only when the pod has no `owner` label (attacker-made). Owned pods (`law-firm`, `platform`) always need human approval. Not reversible. Quarantine first if the pod may still be sending data.

## RB-02 isolate — `quarantine_pod`
Applies a deny-all ingress + egress NetworkPolicy to one pod. **Autonomous**, reversible, and affects only that pod. The fastest way to stop mining-pool traffic, exfiltration or a flood.

## RB-03 persist — `delete_cronjob`
Deletes a CronJob. **Autonomous** when it is not on the allowlist; allowlisted (legitimate) CronJobs need approval. Do this before deleting the pods a CronJob spawns.

## RB-04 identity — `revoke_service_account`
Deletes the `notebook-dev` RoleBinding so the stolen token stops working. **Always needs human approval** — it breaks the researchers' notebook. High risk, not reversible without re-provisioning.

## RB-05 node — `cordon_node`
Stops new pods scheduling on a node; running pods keep running. **Always needs human approval.** Use only when the node itself is suspected.
