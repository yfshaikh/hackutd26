# Persistence (attacker CronJob / backdoor)

**Signals:** a **CronJob not on the allowlist** (`config.CRONJOB_ALLOWLIST`); pods named `<cronjob>-<digits>-xxxxx`; a pod that **reappears after deletion**. **NOT this if** there is no non-allowlisted CronJob.

**Severity:** high.

## Confirm
1. Note any pod that respawned after containment — the verify pass reports these.
2. `describe_pod` on a spawned pod — its owner reference names the Job/CronJob that made it.
3. Record the schedule and the command the CronJob runs.

## Contain (order matters)
1. **RB-03 persist:** `delete_cronjob` the non-allowlisted CronJob **first** — otherwise it recreates what you delete. Autonomous unless the CronJob is on the allowlist (then needs approval).
2. **RB-01 contain:** `delete_pod` the pods it already spawned.
3. **RB-04 identity:** request `revoke_service_account` — the CronJob was created with the stolen token.

## Record
Category `persistence`; next steps: audit every CronJob/Deployment created by the compromised identity.

## Done when
No non-allowlisted CronJob remains and the verify pass reports nothing respawned.
