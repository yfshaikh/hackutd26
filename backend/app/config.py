"""Runtime configuration, loaded from backend/.env via python-dotenv.

We never read or print the .env file ourselves; load_dotenv() populates
os.environ and we only ever read individual keys from there.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent

# Load backend/.env into os.environ if present. override=False so a real
# shell env wins. We never open the file directly.
load_dotenv(BACKEND_DIR / ".env", override=False)

CONSOLE_ORIGIN = os.environ.get("CONSOLE_ORIGIN", "http://localhost:5173")
# The separate attacker app (Task 2). CORS-allowed so it can stream the transcript.
ATTACKER_ORIGIN = os.environ.get("ATTACKER_ORIGIN", "http://localhost:5180")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@halloran-vance.example")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme-hackutd")

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
LAWFIRM_NS = "lawfirm"
PLATFORM_NS = "platform"
DROP_NS = "drop-site"
TELEMETRY_LABEL = "app=gpu-telemetry"
MODEL_WEIGHTS_PVC = "model-weights"
NOTEBOOK_LABEL = "app=notebook"
DROP_SERVICE = "http://drop.drop-site.svc/contracts-ft-v3.pt"
WEIGHTS_FILE = "contracts-ft-v3.pt"
ATTACK_LABEL_KEY = "hackutd/attack"

# CronJobs allowed to exist in lawfirm (anything else is suspicious).
CRONJOB_ALLOWLIST: set[str] = set()

# Pods allowed to mount model-weights.
WEIGHTS_MOUNT_ALLOWLIST = ("model-server",)

LOG_DIR = BACKEND_DIR / "logs"
DECISIONS_LOG = LOG_DIR / "decisions.jsonl"


def nvidia_api_key() -> str | None:
    """Return the Nemotron key if set, else None. Never logs the value."""
    key = os.environ.get("OPENROUTER_API_KEY", "").strip() or os.environ.get("NVIDIA_API_KEY", "").strip()
    return key or None
