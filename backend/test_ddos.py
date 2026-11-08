"""Self-check for the WS-D DDoS step and prompt-injection fixture.

Run from the backend directory:

    uv run python test_ddos.py

No test framework. It proves the two safety properties that matter:

  (a) the flood target is the in-cluster sink and cannot be overridden, and
  (b) the embedded flood loop honors both hard caps (connections + duration).

It also checks the step is registered and the WS-C fixture is importable.
"""
from __future__ import annotations

import builtins
import inspect
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import attacks  # noqa: E402
from app.hub import Store  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SINK_MANIFEST = REPO_ROOT / "deploy" / "20-ddos-sink.yaml"


class _FakeConn:
    def close(self) -> None:
        pass


class _FakeSocket:
    def __init__(self) -> None:
        self.connections = 0

    def create_connection(self, target, timeout=None):
        # The fake ignores the address on purpose: we are testing the loop, not
        # making real connections. The target is asserted separately.
        self.connections += 1
        return _FakeConn()


class _FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _run_flood(script: str) -> tuple[int, float]:
    """Execute the embedded pod script with fake socket/time modules."""
    fake_socket, fake_time = _FakeSocket(), _FakeTime()
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "socket":
            return fake_socket
        if name == "time":
            return fake_time
        return real_import(name, *args, **kwargs)

    safe_builtins = dict(vars(builtins))
    safe_builtins["__import__"] = fake_import
    exec(script, {"__builtins__": safe_builtins, "__name__": "__main__"})
    return fake_socket.connections, fake_time.now


def check_target_is_in_cluster_sink() -> None:
    assert attacks.DDOS_TARGET_HOST == "sink.drop-site.svc", attacks.DDOS_TARGET_HOST
    assert attacks.DDOS_TARGET_HOST.endswith(".svc"), "target must be in-cluster DNS"
    assert "://" not in attacks.DDOS_TARGET_HOST
    assert attacks.DDOS_TARGET_PORT == 80

    # The attack step takes no arguments, so no caller can point it elsewhere.
    assert inspect.signature(attacks.ddos).parameters == {}
    assert list(inspect.signature(attacks._ddos_pod_body).parameters) == ["name"]

    body = attacks._ddos_pod_body("probe")
    spec = body["spec"]
    assert "hostNetwork" not in spec, "the flood pod must not use host networking"
    command = " ".join(spec["containers"][0]["command"])
    assert attacks.DDOS_TARGET_HOST in command
    assert f"MAX_CONNS = {attacks.DDOS_MAX_CONNS}" in command
    assert f"DURATION = {attacks.DDOS_DURATION}" in command

    manifest = SINK_MANIFEST.read_text()
    assert "kind: Service" in manifest
    assert "type: ClusterIP" in manifest
    assert not re.search(r"type:\s*(NodePort|LoadBalancer)", manifest), "sink must stay ClusterIP"
    assert "name: sink" in manifest


def check_connection_cap() -> None:
    count, elapsed = _run_flood(attacks._FLOOD_PY)
    assert count == attacks.DDOS_MAX_CONNS, (count, attacks.DDOS_MAX_CONNS)
    assert elapsed <= attacks.DDOS_DURATION + attacks.DDOS_CONNECT_INTERVAL


def check_duration_cap() -> None:
    # Raise only the connection cap in the test copy; the duration cap must still stop it.
    script = attacks._FLOOD_PY.replace(
        f"MAX_CONNS = {attacks.DDOS_MAX_CONNS}", "MAX_CONNS = 1000000000"
    )
    count, elapsed = _run_flood(script)
    expected_max = int(attacks.DDOS_DURATION / attacks.DDOS_CONNECT_INTERVAL) + 2
    assert count <= expected_max, (count, expected_max)
    assert elapsed >= attacks.DDOS_DURATION


def check_registration() -> None:
    steps = Store().attack_list()
    ids = [s.id for s in steps]
    assert ids[-2:] == ["persistence", "ddos"], ids
    assert steps[-1].status == "locked"
    consts = attacks.run_step.__code__.co_consts
    assert any(isinstance(c, tuple) and "ddos" in c for c in consts), consts
    main_src = (Path(__file__).resolve().parent / "app" / "main.py").read_text()
    assert '"ddos"' in main_src, "run_attack allowlist must include ddos"


def check_prompt_injection_fixture() -> None:
    line = attacks.PROMPT_INJECTION_LINE
    assert isinstance(line, str) and line.startswith("SYSTEM:")
    assert callable(attacks.plant_prompt_injection)
    assert list(inspect.signature(attacks.plant_prompt_injection).parameters) == []
    body = attacks._injection_pod_body("syslog-test")
    command = " ".join(body["spec"]["containers"][0]["command"])
    assert line in command
    # The separate evals process has no attack kernel, so the helper must have an
    # operator-client fallback.
    assert "create_from_dict" in inspect.getsource(attacks.plant_prompt_injection)


def main() -> None:
    check_target_is_in_cluster_sink()
    check_connection_cap()
    check_duration_cap()
    check_registration()
    check_prompt_injection_fixture()
    print("OK: DDoS target is in-cluster, caps hold, step registered, fixture importable.")


if __name__ == "__main__":
    main()
