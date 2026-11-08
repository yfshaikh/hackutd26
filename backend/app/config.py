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


def nvidia_api_key() -> str | None:
    """Return the Nemotron key if set, else None. Never logs the value."""
    key = os.environ.get("OPENROUTER_API_KEY", "").strip() or os.environ.get("NVIDIA_API_KEY", "").strip()
    return key or None
