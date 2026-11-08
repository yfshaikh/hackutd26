"""The real attack chain, driven through the exposed Jupyter kernel API.

Instead of the backend using a Kubernetes client, the attack runs the way a real
intruder with a leaked notebook URL would (ShadowRay): find the unauthenticated
JupyterLab, open a kernel inside the notebook pod, read the pod's mounted
service-account token, and call the Kubernetes API with it to create the miner
pod, the exfil pod, the CronJob and the flood.

This package is the old single attacks.py, split so it's easier to read:

  runtime.py  — plumbing shared by every step: constants, the kernel helpers,
                the transcript helpers, and _K8S_PREAMBLE (the in-pod snippet
                that calls the API server with the stolen token).
  bodies.py   — the Kubernetes objects (and the Python scripts inside them) each
                step creates: the miner/exfil/cronjob/ddos/injection pod bodies.
  steps.py    — the attack chain itself (gain_access -> start_miner ->
                steal_weights -> persistence -> ddos), plus the eval fixture,
                recon, and reset. Read this one to follow the whole intrusion.

Other modules still do `from . import attacks` and call attacks.run_step /
attacks.reset / attacks.recon exactly as before — the names are re-exported here.
"""
from .bodies import (  # noqa: F401  (re-exported for tests / callers)
    _ddos_pod_body,
    _FLOOD_PY,
    _injection_pod_body,
)
from .runtime import (  # noqa: F401
    DDOS_CONNECT_INTERVAL,
    DDOS_DURATION,
    DDOS_MAX_CONNS,
    DDOS_TARGET_HOST,
    DDOS_TARGET_PORT,
    PROMPT_INJECTION_LINE,
)
from .steps import (  # noqa: F401
    ddos,
    gain_access,
    persistence,
    plant_prompt_injection,
    recon,
    reset,
    run_step,
    start_miner,
    steal_weights,
)

__all__ = [
    "run_step", "reset", "recon",
    "gain_access", "start_miner", "steal_weights", "persistence", "ddos",
    "plant_prompt_injection",
    "PROMPT_INJECTION_LINE",
    "DDOS_TARGET_HOST", "DDOS_TARGET_PORT", "DDOS_MAX_CONNS",
    "DDOS_DURATION", "DDOS_CONNECT_INTERVAL",
]
