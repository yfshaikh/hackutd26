# Identity compromise (stolen service-account token)

**Signals:** pods or CronJobs created by the `notebook-dev` service account that no researcher launched; an exposed, unauthenticated notebook (Jupyter/Ray — ShadowRay, CVE-2023-48022).

**Severity:** high on its own; it is the **root cause** behind every other runbook here.

## Confirm
1. `describe_pod` on attacker objects — they were created with the notebook's service account.
2. `lookup_cve` — identify the exploited entry point for the record's vector.

## Contain
1. Contain the workloads first (cryptojacking / exfiltration / flood runbooks).
2. **RB-04 identity:** request `revoke_service_account` — deletes the `notebook-dev` RoleBinding. **Always needs human approval**: researchers lose job-launch access until it is re-provisioned.
3. **RB-05 node:** request `cordon_node` only if the node itself is suspected compromised. Needs approval.

## Record
Root cause = the exposed notebook + stolen token; next steps: rotate tokens, put the notebook behind auth, audit RBAC.

## Done when
The revoke is approved (or explicitly denied by a human with a reason on the record).
