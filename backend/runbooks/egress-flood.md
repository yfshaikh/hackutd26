# Egress flood (cluster used to attack someone else)

**Signals:** an unowned pod with **no GPU and no PVC**; logs with `EGRESS-FLOOD`, connection counters, a single external `target=host:port`; little or no GPU use.

**Severity:** high — the firm's infrastructure is attacking a third party (liability, provider abuse reports).

## Confirm
1. `list_pods` — find unowned pods with no GPU request.
2. `get_pod_logs` — confirm the flood pattern and the target.
3. `describe_pod` — record the command and creating identity.

## Contain
1. **RB-02 isolate:** `quarantine_pod` immediately — the deny-all egress policy stops the flood within seconds.
2. **RB-01 contain:** `delete_pod`.
3. **RB-04 identity:** request `revoke_service_account`.

## Record
Category `denial-of-service`; impact names the target and duration; next steps: notify the hosting provider and the target if required.

## Done when
No unowned pod with outbound traffic; egress back to baseline.
