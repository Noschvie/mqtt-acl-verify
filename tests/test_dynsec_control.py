# SPDX-License-Identifier: AGPL-3.0-or-later
"""DynSec control API of Mosquitto 2.1.4: properties PMSS relies on.

- correlationData: is it returned in the response, per command, in every case?
- getClient: does it ever return a password hash? (basis for decision S-5:
  a password change does not change the client ETag)

Runs against testbroker-dynsec/ (plain listener, user dynsec-admin):
  MQTT_TEST_BROKER_DYNSEC=127.0.0.1:1884 pytest tests/test_dynsec_control.py -v
"""

import json
import os
import queue
import uuid

import paho.mqtt.client as mqtt
import pytest
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

DYNSEC = os.environ.get("MQTT_TEST_BROKER_DYNSEC")
ADMIN = os.environ.get("MQTT_DYNSEC_ADMIN_USER", "dynsec-admin")
ADMIN_PW = os.environ.get("MQTT_DYNSEC_ADMIN_PASSWORD", "test")
REQUEST = "$CONTROL/dynamic-security/v1"
RESPONSE = "$CONTROL/dynamic-security/v1/response"
TIMEOUT = 5

pytestmark = pytest.mark.skipif(
    not DYNSEC, reason="MQTT_TEST_BROKER_DYNSEC not set (needs testbroker-dynsec/)")

# Every field name under which a password or its hash could appear
PASSWORD_FIELDS = {"password", "encoded_password", "salt", "hash", "iterations", "pw"}


class Control:
    """MQTT 5 client on the DynSec control topics, one queue of responses."""

    def __init__(self, name: str):
        host, _, port = DYNSEC.rpartition(":")
        self.responses: queue.Queue = queue.Queue()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id=f"probe-{name}-{uuid.uuid4().hex[:8]}",
                                  protocol=mqtt.MQTTv5)
        self.client.username_pw_set(ADMIN, ADMIN_PW)
        self.client.on_message = lambda c, u, msg: self.responses.put(msg)
        subscribed = queue.Queue()
        self.client.on_subscribe = lambda c, u, mid, rc, p: subscribed.put(rc)
        self.client.connect(host, int(port))
        self.client.loop_start()
        self.client.subscribe(RESPONSE, qos=1)
        rc = subscribed.get(timeout=TIMEOUT)
        assert not rc[0].is_failure, f"subscribe to {RESPONSE} refused: {rc[0]}"

    def send(self, payload, properties: Properties | None = None) -> None:
        body = payload if isinstance(payload, (str, bytes)) else json.dumps(payload)
        self.client.publish(REQUEST, body, qos=1, properties=properties).wait_for_publish(TIMEOUT)

    def receive(self, timeout: float = TIMEOUT) -> mqtt.MQTTMessage:
        return self.responses.get(timeout=timeout)

    def request(self, *commands: dict) -> list[dict]:
        self.send({"commands": list(commands)})
        return json.loads(self.receive().payload)["responses"]

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


@pytest.fixture
def ctl():
    c = Control("ctl")
    yield c
    c.close()


@pytest.fixture
def probe_client(ctl):
    """Temporary password client; deleted afterwards."""
    name = f"probe-{uuid.uuid4().hex[:8]}"
    (r,) = ctl.request({"command": "createClient", "username": name, "password": "a" * 24,
                        "textname": "probe"})
    assert "error" not in r, r
    yield name
    ctl.request({"command": "deleteClient", "username": name})


def _keys(obj) -> set[str]:
    """All keys of a JSON tree, recursively."""
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in _keys(v)}
    if isinstance(obj, list):
        return {k for v in obj for k in _keys(v)}
    return set()


# --- correlationData --------------------------------------------------------

def test_correlation_data_returned_per_command(ctl, probe_client):
    responses = ctl.request(
        {"command": "getClient", "username": probe_client, "correlationData": "c-1"},
        {"command": "getClient", "username": "does-not-exist", "correlationData": "c-2"},
        {"command": "listRoles", "correlationData": "c-3"},
    )
    assert [r.get("correlationData") for r in responses] == ["c-1", "c-2", "c-3"]
    # also on errors, and the order of the batch is kept
    assert "error" not in responses[0]
    assert responses[1]["error"] == "Client not found"


def test_correlation_data_on_modifying_commands(ctl):
    name = f"probe-{uuid.uuid4().hex[:8]}"
    responses = ctl.request(
        {"command": "createClient", "username": name, "correlationData": "create"},
        {"command": "createClient", "username": name, "correlationData": "create-again"},
        {"command": "deleteClient", "username": name, "correlationData": "delete"},
    )
    assert [(r.get("correlationData"), r.get("error")) for r in responses] == [
        ("create", None), ("create-again", "Client already exists"), ("delete", None)]


def test_correlation_data_uuid_and_empty_string_returned_verbatim(ctl):
    cid = str(uuid.uuid4())
    (r1, r2) = ctl.request({"command": "listClients", "correlationData": cid},
                           {"command": "listClients", "correlationData": ""})
    assert r1["correlationData"] == cid
    assert r2["correlationData"] == ""


def test_correlation_data_missing_is_omitted(ctl):
    (r,) = ctl.request({"command": "listClients"})
    assert "correlationData" not in r


def test_correlation_data_non_string_aborts_batch_without_id(ctl):
    """A non-string correlationData yields an error WITHOUT correlationData and
    the remaining commands of the batch are not executed."""
    name = f"probe-{uuid.uuid4().hex[:8]}"
    responses = ctl.request(
        {"command": "listClients", "correlationData": 42},
        {"command": "createClient", "username": name, "correlationData": "next"},
    )
    assert responses == [{"command": "listClients", "error": "Invalid correlationData data type."}]
    (r,) = ctl.request({"command": "getClient", "username": name, "correlationData": "check"})
    assert r["error"] == "Client not found"


@pytest.mark.parametrize("payload, error", [
    ("not json", "Payload not valid JSON"),
    ('{"commands": {}}', "Invalid/missing commands"),
])
def test_invalid_request_has_no_correlation_data(ctl, payload, error):
    ctl.send(payload)
    (r,) = json.loads(ctl.receive().payload)["responses"]
    assert r.get("error") == error
    assert "correlationData" not in r


def test_mqtt5_correlation_property_and_response_topic_ignored(ctl):
    """MQTT 5 request/response properties are not used: the answer always goes to
    the fixed response topic and carries no Correlation Data property."""
    props = Properties(PacketTypes.PUBLISH)
    props.ResponseTopic = f"{RESPONSE}/probe-{uuid.uuid4().hex[:8]}"
    props.CorrelationData = b"mqtt5-cid"
    ctl.send({"commands": [{"command": "listRoles", "correlationData": "json-cid"}]}, props)
    msg = ctl.receive()
    assert msg.topic == RESPONSE
    assert getattr(msg.properties, "CorrelationData", None) is None
    assert json.loads(msg.payload)["responses"][0]["correlationData"] == "json-cid"


def test_responses_go_to_every_subscriber():
    """The plugin publishes the answer to all subscribers of the response topic,
    not only to the requester. A second admin (e.g. mosquitto_ctrl or a second
    PMSS instance) sees foreign responses with unknown correlationData."""
    a, b = Control("a"), Control("b")
    try:
        cid = f"from-a-{uuid.uuid4().hex[:8]}"
        a.request({"command": "listRoles", "correlationData": cid})
        seen_by_b = json.loads(b.receive().payload)["responses"][0]
        assert seen_by_b["correlationData"] == cid
    finally:
        a.close()
        b.close()


# --- getClient and password hash (S-5) --------------------------------------

def test_get_client_has_no_password_hash(ctl, probe_client):
    (r,) = ctl.request({"command": "getClient", "username": probe_client, "correlationData": "g"})
    client = r["data"]["client"]
    assert client["username"] == probe_client
    assert _keys(client) & PASSWORD_FIELDS == set()
    assert "a" * 24 not in json.dumps(r)


def test_list_clients_verbose_has_no_password_hash(ctl, probe_client):
    (r,) = ctl.request({"command": "listClients", "verbose": True})
    clients = r["data"]["clients"]
    assert probe_client in {c["username"] for c in clients}
    assert _keys(clients) & PASSWORD_FIELDS == set()


def test_get_client_unchanged_by_password_change(ctl, probe_client):
    """S-5: the client ETag is computed from getClient; a password change must not change it."""
    get = {"command": "getClient", "username": probe_client}
    (before,) = ctl.request(get)
    (r,) = ctl.request({"command": "setClientPassword", "username": probe_client,
                        "password": "b" * 24})
    assert "error" not in r, r
    (after,) = ctl.request(get)
    assert after == before


def test_get_client_disabled_flag_only_when_set(ctl, probe_client):
    """'disabled' is omitted for enabled clients and only appears as true.
    The ETag must treat 'missing' and 'false' alike."""
    get = {"command": "getClient", "username": probe_client}
    (r,) = ctl.request(get)
    assert "disabled" not in r["data"]["client"]
    ctl.request({"command": "disableClient", "username": probe_client})
    (r,) = ctl.request(get)
    assert r["data"]["client"]["disabled"] is True
    ctl.request({"command": "enableClient", "username": probe_client})
    (r,) = ctl.request(get)
    assert "disabled" not in r["data"]["client"]
