"""Attacker-side loot + victim telemetry: GET /attack/loot.

The attacker app (the "laptop", port 5180) polls this while an attack runs so the
operator can WATCH the theft and the flood, not just read about them:

  exfil.bytes/total  how much of the weights file has arrived at the drop site
  exfil.done         the drop site's final "received ... N bytes" line
  exfil.entries      the zip entries inside the stolen .pt (names + sizes only)
  ddos.connections   the sink's accepted-connection count for the current flood
  ddos.running       the ddos step is in flight

Where the numbers come from: the drop and sink pods' own logs, read with the
backend's existing admin client (the same client defender._check_exfil_evidence
uses). We deliberately do NOT import from defender — the attacker app must not
depend on the defender lane, and this is read-only log parsing.

Attacker endpoints have no sign-in by design (judges drive them), so this returns
COUNTS and entry NAMES only. It never returns file contents, and nothing here
opens the stolen file: the drop pod's zipfile listing is the only reader.

Reset: the drop pod is deleted by reset, so its log (and this exfil view) starts
empty. The sink pod survives, so the victim counter is rebased when the ddos
step leaves "done" — that makes Reset clear both panels.
"""
from __future__ import annotations

import re

from fastapi import APIRouter

from . import config
from .hub import store
from .k8s import ApiException, admin, admin_core, first_pod_name

router = APIRouter(tags=["attack"])

# drop.py log lines (see deploy/10-lawfirm.yaml):
#   progress /contracts-ft-v3.pt 48234496/302335262 bytes
#   entry archive/data/0 4194304 bytes
#   received /contracts-ft-v3.pt 302335262 bytes
_PROGRESS = re.compile(r"^progress\s+(\S+)\s+(\d+)/(\d+)\s+bytes$")
_RECEIVED = re.compile(r"^received\s+(\S+)\s+(\d+)\s+bytes$")
_ENTRY = re.compile(r"^entry\s+(\S+)\s+(\d+)\s+bytes$")

# sink.py log line (see deploy/20-ddos-sink.yaml): sink accepted 25 connections
_SINK = re.compile(r"^sink accepted\s+(\d+)\s+connections$")

# The sink pod (and its log) outlives a reset, so keep a per-run baseline here.
_prev_ddos_status: str | None = None
_ddos_baseline = 0


def _pod_logs(selector: str, tail: int) -> str:
    """Recent log lines for the drop-site pod matching `selector`; "" if unavailable."""
    try:
        pod = first_pod_name(admin(), config.DROP_NS, selector)
        if not pod:
            return ""
        return admin_core().read_namespaced_pod_log(pod, config.DROP_NS, tail_lines=tail) or ""
    except ApiException:
        return ""
    except Exception:  # noqa: BLE001 — a missing kubeconfig must not 500 the attacker app
        return ""


def _exfil_view() -> dict:
    got = total = 0
    done = False
    entries: list[dict] = []
    for raw in _pod_logs("app=drop", 200).splitlines():
        line = raw.strip()
        m = _PROGRESS.match(line)
        if m:
            got, total = int(m.group(2)), int(m.group(3))
            continue
        m = _RECEIVED.match(line)
        if m:
            got = total = int(m.group(2))
            done = True
            continue
        m = _ENTRY.match(line)
        if m:
            entries.append({"name": m.group(1), "bytes": int(m.group(2))})
    return {"bytes": got, "total": total, "done": done, "entries": entries}


def _sink_total() -> int:
    last = 0
    for raw in _pod_logs("app=sink", 200).splitlines():
        m = _SINK.match(raw.strip())
        if m:
            last = int(m.group(1))
    return last


def _flood_pod_running() -> bool:
    """True while the attack's net-probe pod is still Running (the flood is in flight).

    steps.ddos marks the step "done" as soon as the pod is created, so the step status
    alone can't tell the UI whether connections are still climbing — the pod's phase can.
    """
    try:
        core = admin_core()
        pods = core.list_namespaced_pod(
            config.LAWFIRM_NS, label_selector=f"{config.ATTACK_LABEL_KEY}=true"
        )
        return any(
            (p.metadata.name or "").startswith("net-probe-")
            and p.status and p.status.phase == "Running"
            for p in pods.items
        )
    except Exception:  # noqa: BLE001 — telemetry must never break the panel
        return False


def _ddos_view() -> dict:
    global _prev_ddos_status, _ddos_baseline
    total = _sink_total()
    status = store.attack["ddos"].status
    if _prev_ddos_status is None:
        # Fresh process: don't show a stale flood from a previous backend run.
        _ddos_baseline = 0 if status == "done" else total
    elif status == "running" and _prev_ddos_status != "running":
        _ddos_baseline = total          # a new flood starts here
    elif status in ("ready", "locked") and _prev_ddos_status in ("done", "running"):
        _ddos_baseline = total          # reset/abort: clear the victim counter
    _prev_ddos_status = status
    return {
        "connections": max(0, total - _ddos_baseline),
        "running": status == "running" or _flood_pod_running(),
    }


@router.get("/attack/loot")
def attack_loot() -> dict:
    """Live loot arrival + victim flood counters for the attacker app. No auth, by design."""
    return {"exfil": _exfil_view(), "ddos": _ddos_view()}
