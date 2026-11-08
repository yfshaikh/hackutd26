# Data exfiltration (model weights / client data leaving the cluster)

**Signals:** a pod other than `model-server` **mounting the `model-weights` PVC**; `curl`/`PUT`/upload in its command; outbound transfer to an unknown host; drop-site evidence (`received … model.safetensors`). **NOT this if** nothing mounts the weights.

**Severity:** critical. **Legal clock:** confirmed exfiltration of client data starts the 72-hour client-notification deadline — the record sets it automatically.

## Confirm
1. `list_pods` — find pods mounting `model-weights` that are not the model server.
2. `describe_pod` — record the mounts, image and command (look for `curl`/`nc`/upload loops).
3. `get_pod_logs` — find the destination and bytes sent.
4. `update_scope` — mark `model-weights` as `exfiltrated` with the byte count in the note.

## Contain
1. **RB-02 isolate:** `quarantine_pod` the exfil pod first — stops any transfer still in flight.
2. **RB-01 contain:** `delete_pod` it.
3. **RB-04 identity:** request `revoke_service_account`.

## Record
Categories `data-exfiltration`, `unauthorized-access`; impact must state *what* left (file, size) and whether it is client data; next steps must include legal/client notification.

## Done when
No pod other than the model server mounts the weights; scope shows the asset as exfiltrated (it stays that way — exfiltration cannot be undone); notification deadline is on the record.
