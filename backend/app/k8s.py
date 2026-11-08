"""Kubernetes access for the command center — four distinct identities.

  * admin()          - the backend's own kubeconfig (full access). Used for the
                       snapshot, GPU telemetry and detection (the SIEM-style read path).
  * attacker()       - built ONLY from the service-account token the attack chain
                       steals from the notebook pod. Everything the attacker does
                       goes through this, to prove the RBAC over-grant is the vector.
  * agent_readonly() - what the defender AGENT investigates with. RBAC denies every
                       write (deploy/30-agent-rbac.yaml), so a hijacked agent can only look.
  * executor()       - runs ONLY actions a human/policy approved. Least-privilege:
                       exactly the five containment verbs, scoped to lawfirm.

agent_readonly/executor tokens are minted in-memory via the TokenRequest API — never
read from a file, never printed. We never print tokens or kubeconfig contents.

Concepts (new here?):
  * A kubeconfig is the file (~/.kube/hackutd.yaml) holding the cluster's address plus a
    credential — a saved login for talking to the Kubernetes API server. admin() uses it.
  * A ServiceAccount is an identity for software, not a person. Kubernetes auto-mounts its
    token (a bearer credential) into every pod at /var/run/secrets/.../token; whoever holds
    that token can call the API as that identity. The attacker stealing the notebook pod's
    token IS the breach — that's why identities and their RBAC (what each is allowed to do)
    are the whole story here.
  * An ApiClient is just a configured HTTP client for the Kubernetes API; each identity above
    is one ApiClient built with a different credential.
"""
from __future__ import annotations

import os
from pathlib import Path

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.stream import stream

from .config import BACKEND_DIR

_admin_api: client.ApiClient | None = None
_attacker_token: str | None = None
_attacker_api: client.ApiClient | None = None


def _load_admin_config() -> None:
    kubeconfig = os.environ.get("KUBECONFIG") or str(Path.home() / ".kube" / "hackutd.yaml")
    config.load_kube_config(config_file=kubeconfig)


def admin() -> client.ApiClient:
    """Lazily build the admin ApiClient from the local kubeconfig."""
    global _admin_api
    if _admin_api is None:
        _load_admin_config()
        _admin_api = client.ApiClient(client.Configuration.get_default_copy())
    return _admin_api


def admin_core() -> client.CoreV1Api:
    return client.CoreV1Api(admin())


def admin_batch() -> client.BatchV1Api:
    return client.BatchV1Api(admin())


def admin_net() -> client.NetworkingV1Api:
    return client.NetworkingV1Api(admin())


def admin_rbac() -> client.RbacAuthorizationV1Api:
    return client.RbacAuthorizationV1Api(admin())


# ---------------------------------------------------------------------------
# WS-A: the defender agent's two scoped identities.
#   agent_readonly() - what the agent investigates with. RBAC denies every write.
#   executor()       - runs ONLY actions a human (or policy) approved. Privileged.
# Tokens are minted in-memory via the TokenRequest API (never read from a file,
# never printed). If the ServiceAccounts aren't applied yet, we fall back to the
# admin client and say so once, so the demo degrades loudly instead of crashing.
# ---------------------------------------------------------------------------
_sa_clients: dict[str, client.ApiClient] = {}
_sa_fallback_warned: set[str] = set()


def _mint_sa_client(sa_name: str) -> client.ApiClient:
    from .config import AGENT_SA_NS
    if sa_name in _sa_clients:
        return _sa_clients[sa_name]
    admin()  # ensure host + CA are loaded into the default config
    try:
        req = client.AuthenticationV1TokenRequest(
            spec=client.V1TokenRequestSpec(expiration_seconds=3600, audiences=[])
        )
        token = admin_core().create_namespaced_service_account_token(
            name=sa_name, namespace=AGENT_SA_NS, body=req
        ).status.token
        base = client.Configuration.get_default_copy()
        cfg = client.Configuration()
        cfg.host = base.host
        cfg.ssl_ca_cert = base.ssl_ca_cert
        cfg.verify_ssl = base.verify_ssl
        cfg.api_key = {"authorization": token}
        cfg.api_key_prefix = {"authorization": "Bearer"}
        api = client.ApiClient(cfg)
    except ApiException as e:  # SA not applied yet, or TokenRequest unavailable
        if sa_name not in _sa_fallback_warned:
            _sa_fallback_warned.add(sa_name)
            print(f"[k8s] ServiceAccount '{sa_name}' unavailable ({e.reason}); using admin "
                  f"fallback. Apply deploy/30-agent-rbac.yaml to enable the real split.")
        api = admin()
    _sa_clients[sa_name] = api
    return api


def agent_readonly() -> client.ApiClient:
    from .config import AGENT_READONLY_SA
    return _mint_sa_client(AGENT_READONLY_SA)


def agent_readonly_core() -> client.CoreV1Api:
    return client.CoreV1Api(agent_readonly())


def executor() -> client.ApiClient:
    from .config import AGENT_EXECUTOR_SA
    return _mint_sa_client(AGENT_EXECUTOR_SA)


def executor_core() -> client.CoreV1Api:
    return client.CoreV1Api(executor())


def executor_batch() -> client.BatchV1Api:
    return client.BatchV1Api(executor())


def executor_net() -> client.NetworkingV1Api:
    return client.NetworkingV1Api(executor())


def executor_rbac() -> client.RbacAuthorizationV1Api:
    return client.RbacAuthorizationV1Api(executor())


def reset_agent_clients() -> None:
    """Drop cached SA clients (after RBAC changes or token expiry)."""
    _sa_clients.clear()
    _sa_fallback_warned.clear()


def set_attacker_token(token: str) -> None:
    """Install the stolen token and rebuild the attacker ApiClient from it."""
    global _attacker_token, _attacker_api
    _attacker_token = token
    admin()  # ensure default config (host + CA) is loaded
    base = client.Configuration.get_default_copy()
    cfg = client.Configuration()
    cfg.host = base.host
    cfg.ssl_ca_cert = base.ssl_ca_cert
    cfg.verify_ssl = base.verify_ssl
    cfg.api_key = {"authorization": token}
    cfg.api_key_prefix = {"authorization": "Bearer"}
    _attacker_api = client.ApiClient(cfg)


def has_attacker_token() -> bool:
    return _attacker_token is not None


def attacker_token() -> str | None:
    return _attacker_token


def clear_attacker_token() -> None:
    global _attacker_token, _attacker_api
    _attacker_token = None
    _attacker_api = None


def attacker() -> client.ApiClient:
    if _attacker_api is None:
        raise RuntimeError("No stolen token yet: run gain-access first.")
    return _attacker_api


def attacker_core() -> client.CoreV1Api:
    return client.CoreV1Api(attacker())


def attacker_batch() -> client.BatchV1Api:
    return client.BatchV1Api(attacker())


def exec_in_pod(
    api: client.ApiClient, namespace: str, pod: str, command: list[str], container: str | None = None
) -> str:
    """Run a command in a pod and return combined stdout/stderr."""
    # stream() rewires the ApiClient it's given to speak websocket while the exec runs. On a shared
    # client, concurrent calls (snapshot, reset) would go out as websockets and fail, so exec gets its own.
    core = client.CoreV1Api(client.ApiClient(api.configuration))
    kwargs = dict(
        command=command,
        stderr=True,
        stdin=False,
        stdout=True,
        tty=False,
        _preload_content=True,
    )
    if container:
        kwargs["container"] = container
    return stream(
        core.connect_get_namespaced_pod_exec,
        pod,
        namespace,
        **kwargs,
    )


def first_pod_name(api: client.ApiClient, namespace: str, label_selector: str) -> str | None:
    core = client.CoreV1Api(api)
    pods = core.list_namespaced_pod(namespace, label_selector=label_selector)
    for p in pods.items:
        if p.status and p.status.phase == "Running":
            return p.metadata.name
    return pods.items[0].metadata.name if pods.items else None


__all__ = [
    "admin", "admin_core", "admin_batch", "admin_net", "admin_rbac",
    "agent_readonly", "agent_readonly_core",
    "executor", "executor_core", "executor_batch", "executor_net", "executor_rbac",
    "reset_agent_clients",
    "attacker", "attacker_core", "attacker_batch",
    "set_attacker_token", "has_attacker_token", "attacker_token",
    "clear_attacker_token", "exec_in_pod", "first_pod_name",
    "ApiException",
]
