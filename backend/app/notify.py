"""Phone the on-call engineer through Cartesia when an action needs a human.

This is the pager. `hub.Store.upsert_approval` starts a background thread that runs
`page_oncall` the first time a *pending* approval appears: one outbound Cartesia call that
reads a short summary of the decision. Cartesia does the voice + telephony through its
agents/calls API. The pager agent is **talk-only** — it has no path back into this backend,
so nothing said on a call can approve, execute, or change anything.

Two guards keep the phone quiet:
  * one call per approval id, and
  * one call per `config.PAGE_EVERY_SECONDS` window across every approval (a burst of
    approvals still produces a single call). Both live in this module because `store` is one
    process-wide object, so there is no cross-process race to coordinate.

Fail-safe by design: every outcome is recorded on the approval and in the timeline
("call placed: <id>", "call failed: <type>", "not called: <reason>"), and no failure here
can reach the detection loop or the approval flow.

SECURITY: the summary is built from the Advisor's output, which can quote attacker-controlled
pod logs, so every spoken field goes through `spoken()` — markdown/links stripped, units said
aloud, phone-number-like digit runs removed, length capped. The phone number is never logged
or shown, and Cartesia's raw error text is never stored (it could echo the number back).
"""
from __future__ import annotations

import json
import logging
import re
import ssl
import threading
import time
import urllib.error
import urllib.request
from functools import lru_cache

from . import config
from .models import Approval, IncidentRecord

log = logging.getLogger(__name__)

# Guards for the one call per approval + one call per window rule.
_LOCK = threading.Lock()
_paged: set[str] = set()
_last_page_at = 0.0
_ALREADY = "already paged"  # internal: this approval was handled, so record nothing new

# Abbreviations the voice guesses wrong ("gpu" as "g-poo") and units a person says aloud.
SPOKEN_WORDS = [
    (r"(\d)\s*GiB\b|(\d)\s*GB\b", r"\1\2 gigabytes"),
    (r"(\d)\s*MiB\b|(\d)\s*MB\b", r"\1\2 megabytes"),
    (r"\bGiB\b|\bGB\b", "gigabytes"),
    (r"\bMiB\b|\bMB\b", "megabytes"),
    (r"(\d)\s*°?\s*C\b", r"\1 degrees"),
    (r"(\d)\s*W\b", r"\1 watts"),
    (r"(\d)\s*%", r"\1 percent"),
    (r"\bGPUs\b", "G P Us"),
    (r"\bGPU\b", "G P U"),
    (r"\bCVE\b", "C V E"),
    (r"\bTLS\b", "T L S"),
    (r"\bIAM\b", "I A M"),
    (r"\bRBAC\b", "R B A C"),
    (r"\bOOM\b", "out of memory"),
    (r"\bSA\b", "service account"),
    (r"\bAPI\b", "A P I"),
]
# Say a CVE id before the phone-number-like digit-run scrubber sees it ("CVE-2024-3094").
_CVE = re.compile(r"\bCVE[- ]?(\d{4})[- ]?(\d{4,7})\b", re.IGNORECASE)


def page_oncall_soon(approval: Approval, record: IncidentRecord | None) -> None:
    """Start the page on its own thread, so filing the approval never waits on a phone call."""
    try:
        threading.Thread(
            target=page_oncall,
            args=(approval, record),
            daemon=True,
            name="oncall-page",
        ).start()
    except Exception:  # noqa: BLE001 — a pager must never break filing the approval
        log.exception("Could not start the on-call page for %s", approval.id)


def page_oncall(approval: Approval, record: IncidentRecord | None) -> None:
    """One page for one pending approval. Records the outcome; never raises."""
    try:
        result = _page(approval, record)
    except Exception as error:  # noqa: BLE001 — network, config or shape: record it and move on
        result = f"call failed: {type(error).__name__}"
    if result:  # "" means this approval was already handled; never overwrite a real outcome
        _record(approval, result)


def _page(approval: Approval, record: IncidentRecord | None) -> str:
    """Run the checks, claim the call slot, and place the call. Returns the recorded outcome."""
    if not config.paging_on():
        return "not called: paging off"
    settings = config.paging_settings()
    if not all(settings.values()):
        return "not called: paging isn't set up"
    blocked = _claim(approval.id)
    if blocked == _ALREADY:
        return ""
    if blocked:
        return blocked
    return _call(settings, variables(approval, record))


def _claim(approval_id: str) -> str | None:
    """Take the one call allowed per window, once per approval id.

    Returns None when this approval gets the call, _ALREADY if it was already handled, else
    the "not called" reason. The lock makes simultaneous approvals settle on a single caller.
    """
    global _last_page_at
    with _LOCK:
        if approval_id in _paged:
            return _ALREADY
        now = time.monotonic()
        if now - _last_page_at < config.PAGE_EVERY_SECONDS:
            return "not called: someone was paged in the last 2 minutes"
        _paged.add(approval_id)
        _last_page_at = now
        return None


def variables(approval: Approval, record: IncidentRecord | None) -> dict[str, str]:
    """The pager agent's dynamic_variables: a short, spoken-safe summary of the decision.

    The deployed pager agent's prompt (shared with the NMC reference project) interpolates
    alert / node / diagnosis / proposed_fix / status, so we send those names. The spec's
    approval-centric names (action / rationale / impact / incident / severity) are sent too,
    so either prompt version reads real values instead of literal "{{...}}" text.

    Every value is untrusted (pod logs can reach the Advisor's rationale) and goes through
    `spoken()` before it is allowed on the call.
    """
    title = record.title if record else "an unnamed incident"
    vector = record.vector if record else None
    incident = f"{title}. {vector}" if vector else title
    severity = record.severity if record else "unknown"
    target = approval.target or (record.affectedSystems[0] if record and record.affectedSystems else "the cluster")
    return {
        # The deployed agent's placeholders.
        "alert": spoken(title, 160),
        "node": spoken(target, 80),
        "diagnosis": spoken(approval.rationale or approval.policyReason, 220),
        "proposed_fix": spoken(approval.action.replace("_", " "), 160),
        "status": spoken("waiting for a human approval in the console", 90),
        # Spec 04's names, kept for forward/backward compatibility.
        "action": spoken(approval.action.replace("_", " "), 160),
        "rationale": spoken(approval.rationale or approval.policyReason, 220),
        "impact": spoken(approval.impact, 160),
        "incident": spoken(incident, 160),
        "severity": spoken(severity, 40),
    }


def spoken(text: str | None, limit: int = 300) -> str:
    """Untrusted text made safe to read out: markdown/links and phone-like digit runs removed,
    units and abbreviations said aloud, one line, capped.

    It stays untrusted even after this (it can quote a customer's pod log), which is why the
    phone agent can only talk.
    """
    text = str(text or "")
    # Say CVE ids first; otherwise the digit-run scrubber would eat them like a phone number.
    text = _CVE.sub(r"C V E \1 dash \2", text)
    for pattern, said in SPOKEN_WORDS:
        text = re.sub(pattern, said, text, flags=re.IGNORECASE)
    text = re.sub(r"https?://\S+|www\.\S+", "[link removed]", text)
    text = re.sub(r"\+?\d[\d\s().-]{6,}\d", "[number removed]", text)
    text = re.sub(r"[*`#_>|\[\]{}]+", "", text)
    return re.sub(r"\s+", " ", text).strip()[:limit]


@lru_cache(maxsize=1)
def _ssl_context() -> ssl.SSLContext:
    """The TLS trust store for the call, with verification always on (the request carries a key).

    A uv/macOS Python often has no system CA bundle, so prefer certifi when it is installed and
    fall back to the platform default everywhere else.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001 — certifi absent: let the platform find its own bundle
        return ssl.create_default_context()


def _call(settings: dict[str, str], dynamic_variables: dict[str, str]) -> str:
    """Place the single outbound call. Returns our outcome line, never Cartesia's own error text."""
    body = json.dumps(
        {
            "from_number_id": settings["CARTESIA_FROM_NUMBER_ID"],
            "agent_id": settings["CARTESIA_PAGER_AGENT_ID"],
            "ringing_timeout_seconds": 45,
            "outbound_calls": [
                {"to_number": settings["ONCALL_PHONE"], "dynamic_variables": dynamic_variables}
            ],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        config.CARTESIA_CALLS,
        data=body,
        method="POST",
        headers={
            "X-API-Key": settings["CARTESIA_API_KEY"],
            "Cartesia-Version": config.CARTESIA_VERSION,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30, context=_ssl_context()) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        # Only the status code: Cartesia's error body could echo the phone number back.
        return f"call failed (Cartesia HTTP {error.code})"
    except Exception as error:  # noqa: BLE001 — timeout/DNS/bad JSON: the type name is enough
        return f"call failed: {type(error).__name__}"

    calls = payload.get("calls") if isinstance(payload, dict) else None
    call = calls[0] if isinstance(calls, list) and calls else {}
    call_id = call.get("agent_call_id") if isinstance(call, dict) else None
    if not call_id:
        return "call failed (Cartesia returned no call)"
    return f"call placed: {call_id}"


def _record(approval: Approval, result: str) -> None:
    """Put the outcome on the approval and in the timeline. Failures here are swallowed too."""
    approval.paging = result  # always true of this object, even if a reset cleared the store
    try:
        # Local import: hub imports this module for the hook, so a top-level import would cycle.
        from .hub import store

        store.set_approval_paging(approval.id, result)
        store.add_timeline(
            kind="system",
            actor="Pager",
            text=f"On-call page for {approval.action}: {result}.",
            severity="info" if result.startswith("call placed") else "low",
            target=approval.target or None,
        )
    except Exception:  # noqa: BLE001 — recording a page must never reach the approval flow
        log.exception("Could not record the paging outcome for %s", approval.id)
