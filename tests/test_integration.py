# SPDX-License-Identifier: AGPL-3.0-or-later
"""End-to-end run against a real Mosquitto using testbroker/acl.

Broker selection:
- MQTT_TEST_BROKER=host:port  use an already running test broker
                               (e.g. testbroker/ via docker compose, as in CI)
- otherwise                   start the local mosquitto binary; skipped if missing
"""

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

from mqtt_acl_verify.model import load_config
from mqtt_acl_verify.runner import Status, run_all

ROOT = Path(__file__).parents[1]
USERS = ["admin", "kitchen", "livingroom", "tasmofleet", "homeassistant", "viewer"]
ENV = {
    "MQTT_ADMIN_PASSWORD": "test", "MQTT_PW_KITCHEN": "test", "MQTT_PW_LIVINGROOM": "test",
    "MQTT_PW_TASMOFLEET": "test", "MQTT_PW_HOMEASSISTANT": "test", "MQTT_PW_VIEWER": "test",
    "MQTT_PW_UNKNOWN": "wrong",
}

EXTERNAL = os.environ.get("MQTT_TEST_BROKER")

pytestmark = pytest.mark.skipif(
    not EXTERNAL and shutil.which("mosquitto") is None,
    reason="mosquitto not installed and MQTT_TEST_BROKER not set",
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(host: str, port: int, proc: subprocess.Popen | None = None) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            output = proc.stdout.read() if proc.stdout else ""
            pytest.fail(f"mosquitto exited with code {proc.returncode}:\n{output}")
        try:
            socket.create_connection((host, port), timeout=0.5).close()
            return
        except OSError:
            time.sleep(0.1)
    pytest.fail(f"broker not reachable on {host}:{port}")


@pytest.fixture
def broker(tmp_path):
    if EXTERNAL:
        host, _, port = EXTERNAL.rpartition(":")
        _wait_for_port(host, int(port))
        yield host, int(port)
        return

    port = _free_port()
    passwd = tmp_path / "passwd"
    passwd.touch(mode=0o600)
    for user in USERS:
        subprocess.run(["mosquitto_passwd", "-b", str(passwd), user, "test"],
                       check=True, capture_output=True)
    acl = tmp_path / "acl"
    shutil.copy(ROOT / "testbroker/acl", acl)
    acl.chmod(0o600)
    conf = tmp_path / "mosquitto.conf"
    lines = [
        f"listener {port} 127.0.0.1",
        "allow_anonymous false",
        f"password_file {passwd}",
        f"acl_file {acl}",
        "log_dest stdout",
    ]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        lines.append("user root")
    conf.write_text("\n".join(lines) + "\n")
    proc = subprocess.Popen(["mosquitto", "-c", str(conf)], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        _wait_for_port("127.0.0.1", port, proc)
        yield "127.0.0.1", port
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_testbroker_cases(broker, tmp_path, monkeypatch):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    cfg = tmp_path / "config.yaml"
    host, port = broker
    text = (ROOT / "testbroker/config.yaml").read_text()
    cfg.write_text(text.replace("host: 127.0.0.1", f"host: {host}").replace("port: 1883", f"port: {port}"))

    results = {r.case.id: r for r in run_all(load_config(cfg, ROOT / "testbroker/cases.yaml"))}

    failed = {cid: r.detail for cid, r in results.items() if r.status is not Status.PASS}
    assert failed == {}
