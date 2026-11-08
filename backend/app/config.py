"""Runtime configuration — the one place every tunable name, URL and secret-reference lives.

New here? Read this file first. Everything else imports these constants instead of
hard-coding strings, so this is the map of "what talks to what": which ports the apps use,
which Nemotron model the agent calls, and the Kubernetes names (namespaces, labels, the
weights file) that the rest of the backend refers to.

A ".env" file is a plain text file of KEY=value secrets/settings that is NOT committed to
git (so keys don't leak). python-dotenv's load_dotenv() copies those keys into the process
environment (os.environ); we only ever read individual keys from there — we never open or
print the .env file itself.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Load backend/.env into os.environ if present. override=False so a real
# shell env wins. We never open the file directly.
load_dotenv(BACKEND_DIR / ".env", override=False)

# --- Service wiring: origins + the seeded admin login ----------------------
CONSOLE_ORIGIN = os.environ.get("CONSOLE_ORIGIN", "http://localhost:5173")
# The separate attacker app (Task 2). CORS-allowed so it can stream the transcript.
ATTACKER_ORIGIN = os.environ.get("ATTACKER_ORIGIN", "http://localhost:5180")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@halloran-vance.example")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme-hackutd")

# --- Model: Nemotron via OpenRouter or NVIDIA's own API --------------------
# Nemotron through OpenRouter if OPENROUTER_API_KEY is set, otherwise NVIDIA's own API (build.nvidia.com).
# Both speak the OpenAI API; only the URL, key and model id differ.
USE_OPENROUTER = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
NVIDIA_BASE_URL = "https://openrouter.ai/api/v1" if USE_OPENROUTER else "https://integrate.api.nvidia.com/v1"
NEMOTRON_MODEL = os.environ.get(
    "NEMOTRON_MODEL",
    "nvidia/nemotron-3-ultra-550b-a55b" if USE_OPENROUTER else "nvidia/llama-3.3-nemotron-super-49b-v1.5",
)
# Per-task model for the cheap, fast agents (Triage, Investigator); the heavy Advisor
# keeps NEMOTRON_MODEL (Ultra-550B). On OpenRouter this is the Nano-30B (fast + cheap,
# same Nemotron-3 generation as the Ultra); off OpenRouter it falls back to NEMOTRON_MODEL
# (no split). The old Super-49B id was retired from OpenRouter, which silently broke the
# two fast agents — hence pinning a live id here.
# ponytail: two tiers is the whole "per-task model" story; add a third when one pays off.
NEMOTRON_FAST_MODEL = os.environ.get(
    "NEMOTRON_FAST_MODEL",
    "nvidia/nemotron-3-nano-30b-a3b" if USE_OPENROUTER else NEMOTRON_MODEL,
)

FIRM_NAME = "Halloran & Vance LLP"

# The exposed JupyterLab, reachable ONLY on the tailnet via the notebook-edge proxy
# (deploy/15-notebook-edge.yaml). The attack drives the notebook through this.
JUPYTER_URL = os.environ.get("JUPYTER_URL", "http://100.106.83.89:8888")
TAILSCALE_IP = os.environ.get("TAILSCALE_IP", "100.106.83.89")

# Namespaces / names from deploy/10-lawfirm.yaml.
# A Kubernetes "namespace" is just a named folder inside the cluster that groups related
# objects (pods, services, etc.) and gives them a boundary. We use three: the law firm's
# real workloads, our platform helpers, and the attacker's "drop site".
LAWFIRM_NS = "lawfirm"
PLATFORM_NS = "platform"
DROP_NS = "drop-site"

# WS-A: the defender agent holds a read-only identity; approved actions run through a
# separate privileged executor identity. Both ServiceAccounts live here (deploy/30-agent-rbac.yaml).
AGENT_SA_NS = "platform"
AGENT_READONLY_SA = "agent-readonly"
AGENT_EXECUTOR_SA = "agent-executor"
# A "label" is a key=value tag you attach to Kubernetes objects; you then select objects by
# their labels (e.g. "give me every pod with app=gpu-telemetry"). These are the labels/names
# the backend searches for.
TELEMETRY_LABEL = "app=gpu-telemetry"
# A PVC (PersistentVolumeClaim) is a request for disk that outlives any single pod — here it
# holds the firm's trained model file, which is exactly what the attacker exfiltrates.
MODEL_WEIGHTS_PVC = "model-weights"
NOTEBOOK_LABEL = "app=notebook"
# A Kubernetes Service name of the form <service>.<namespace>.svc is an in-cluster DNS address.
DROP_SERVICE = "http://drop.drop-site.svc/contracts-ft-v3.pt"
WEIGHTS_FILE = "contracts-ft-v3.pt"
# Every object the attack creates gets this label, so cleanup can find and delete them all.
ATTACK_LABEL_KEY = "hackutd/attack"

# CronJobs allowed to exist in lawfirm (anything else is suspicious). Empty = none are
# expected, so any CronJob the detector sees is treated as attacker persistence.
CRONJOB_ALLOWLIST: set[str] = set()

# Pods allowed to mount model-weights. Only the real model server should; anything else
# mounting it is the exfil pod stealing the weights.
WEIGHTS_MOUNT_ALLOWLIST = ("model-server",)

# Where the agent's decision log is written: one JSON line per tool call. This file is the
# evidence trail the evals + /defender/metrics read back.
LOG_DIR = BACKEND_DIR / "logs"
DECISIONS_LOG = LOG_DIR / "decisions.jsonl"

# --- On-call paging: phone the on-call engineer when a human decision is needed --------
# Cartesia's agents/calls API places ONE outbound call that reads a short summary of the
# pending approval. The pager agent is talk-only: it has no path back into this backend, so
# nothing said on the call can approve or change anything. The four keys it needs
# (CARTESIA_API_KEY, CARTESIA_PAGER_AGENT_ID, CARTESIA_FROM_NUMBER_ID, ONCALL_PHONE) are
# read fresh from os.environ by paging_settings() — never cached, logged, or committed.
CARTESIA_CALLS = "https://api.cartesia.ai/agents/calls"
CARTESIA_VERSION = "2026-08-14"
PAGE_EVERY_SECONDS = 120  # at most one call per window, however many approvals fire


def paging_on() -> bool:
    """Whether a pending approval should phone the on-call engineer (off unless PAGING_ON=true)."""
    return os.environ.get("PAGING_ON", "false").strip().lower() in {"1", "true", "yes", "on"}


def paging_settings() -> dict[str, str]:
    """The four keys a page needs, read at call time. The phone number is never logged."""
    return {
        key: os.environ.get(key, "").strip()
        for key in ("CARTESIA_API_KEY", "CARTESIA_PAGER_AGENT_ID", "CARTESIA_FROM_NUMBER_ID", "ONCALL_PHONE")
    }


def nvidia_api_key() -> str | None:
    """Return the Nemotron key if set, else None. Never logs the value."""
    key = os.environ.get("OPENROUTER_API_KEY", "").strip() or os.environ.get("NVIDIA_API_KEY", "").strip()
    return key or None
