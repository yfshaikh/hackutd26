"""Cluster inspection endpoints: one pod's spec and its logs.

These are additive, read-only routes used by the console's floor drawer. They sit
outside the 2-second telemetry snapshot because a pod's full spec and logs are
expensive to fetch and only needed when a responder opens one pod.

  GET /cluster/pods/{namespace}/{name}                       -> PodDetail
  GET /cluster/pods/{namespace}/{name}/logs?container=&...   -> PodLogs

Both require a signed-in console session, same as /snapshot, and are limited to
the namespaces the floor already shows (lawfirm + platform).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import current_user
from .cluster import VISIBLE_NS, build_pod_detail
from .k8s import ApiException, admin_core
from .models import PodDetail, PodLogs, User

router = APIRouter(prefix="/cluster", tags=["cluster"])

_MAX_LOG_BYTES = 512_000


def _check_namespace(namespace: str) -> None:
    if namespace not in VISIBLE_NS:
        raise HTTPException(status_code=404, detail=f"Namespace {namespace!r} is not on the floor")


def _k8s_detail(e: ApiException) -> str:
    """Pull the human sentence out of a Kubernetes error body when there is one."""
    body = e.body
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict) and parsed.get("message"):
                return str(parsed["message"])
        except json.JSONDecodeError:
            pass
        if body.strip():
            return body.strip()
    return e.reason or "Kubernetes request failed"


@router.get("/pods/{namespace}/{name}", response_model=PodDetail)
def pod_detail(namespace: str, name: str, user: User = Depends(current_user)) -> PodDetail:
    """Full live spec for one pod: what it runs, what it asks for, and its state."""
    _check_namespace(namespace)
    try:
        return build_pod_detail(namespace, name)
    except ApiException as e:
        raise HTTPException(
            status_code=404 if e.status == 404 else 502,
            detail=_k8s_detail(e),
        ) from e


@router.get("/pods/{namespace}/{name}/logs", response_model=PodLogs)
def pod_logs(
    namespace: str,
    name: str,
    container: str | None = None,
    tailLines: int = Query(200, ge=1, le=1000),
    previous: bool = False,
    timestamps: bool = False,
    user: User = Depends(current_user),
) -> PodLogs:
    """Last `tailLines` log lines for one container (first container by default).

    `previous=true` reads the previous run's logs after a restart, which is the
    interesting case when a container is crash-looping. A container that has not
    started yet returns 409 with Kubernetes' own explanation rather than an empty
    log, so the drawer can say why.
    """
    _check_namespace(namespace)
    core = admin_core()
    try:
        pod = core.read_namespaced_pod(name, namespace)
    except ApiException as e:
        status = 404 if e.status == 404 else 502
        raise HTTPException(status_code=status, detail=_k8s_detail(e)) from e

    names = [c.name for c in (pod.spec.containers or [])]
    if not names:
        raise HTTPException(status_code=409, detail="This pod has no containers")
    if container is None:
        container = names[0]
    elif container not in names:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown container {container!r}; expected one of {', '.join(names)}",
        )

    try:
        text = core.read_namespaced_pod_log(
            name=name,
            namespace=namespace,
            container=container,
            tail_lines=tailLines,
            previous=previous,
            timestamps=timestamps,
            limit_bytes=_MAX_LOG_BYTES,
        )
    except ApiException as e:
        # 400 is what the API server returns for "container is waiting to start".
        status = 409 if e.status == 400 else (404 if e.status == 404 else 502)
        raise HTTPException(status_code=status, detail=_k8s_detail(e)) from e

    return PodLogs(
        namespace=namespace,
        pod=name,
        container=container,
        tailLines=tailLines,
        previous=previous,
        text=text or "",
    )
