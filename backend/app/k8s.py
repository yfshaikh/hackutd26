"""Kubernetes access for the command center.

Two distinct clients:
  * admin()    - the backend's own kubeconfig. Used by snapshot + defender tools.
  * attacker() - built ONLY from the service-account token the attack chain
                 steals from the notebook pod. Everything the attacker does
                 goes through this, to prove the RBAC over-grant is the vector.

We never print tokens or kubeconfig contents.
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
    "attacker", "attacker_core", "attacker_batch",
    "set_attacker_token", "has_attacker_token", "attacker_token",
    "clear_attacker_token", "exec_in_pod", "first_pod_name",
    "ApiException",
]
