# SPDX-License-Identifier: AGPL-3.0-or-later
"""Thin synchronous wrapper around paho-mqtt for probing a broker."""

from __future__ import annotations

import ssl
import threading
from dataclasses import dataclass

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from .model import Endpoint, Identity


@dataclass
class Received:
    topic: str
    payload: bytes


class Session:
    """One MQTT connection for one identity on one endpoint."""

    def __init__(self, identity: Identity, endpoint: Endpoint, timeout: float) -> None:
        self.identity = identity
        self.endpoint = endpoint
        self.timeout = timeout
        protocol = mqtt.MQTTv5 if endpoint.protocol == 5 else mqtt.MQTTv311
        self._client = mqtt.Client(
            CallbackAPIVersion.VERSION2,
            client_id=identity.make_client_id(),
            protocol=protocol,
        )
        if identity.username is not None:
            self._client.username_pw_set(identity.username, identity.password())
        if endpoint.tls:
            self._client.tls_set(ca_certs=endpoint.ca_file, cert_reqs=ssl.CERT_REQUIRED)

        self._cond = threading.Condition()
        self._connect_rc: mqtt.ReasonCode | None = None
        self._suback: dict[int, list] = {}
        self._puback: dict[int, mqtt.ReasonCode] = {}
        self._messages: list[Received] = []
        self._running = False

        self._client.on_connect = self._on_connect
        self._client.on_subscribe = self._on_subscribe
        self._client.on_publish = self._on_publish
        self._client.on_message = self._on_message

    # -- callbacks (network thread) --------------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        with self._cond:
            self._connect_rc = reason_code
            self._cond.notify_all()

    def _on_subscribe(self, client, userdata, mid, reason_code_list, properties):
        with self._cond:
            self._suback[mid] = list(reason_code_list)
            self._cond.notify_all()

    def _on_publish(self, client, userdata, mid, reason_code, properties):
        with self._cond:
            self._puback[mid] = reason_code
            self._cond.notify_all()

    def _on_message(self, client, userdata, msg):
        with self._cond:
            self._messages.append(Received(msg.topic, msg.payload))
            self._cond.notify_all()

    # -- API ---------------------------------------------------------------

    def connect(self) -> tuple[bool, str]:
        """Connect and wait for CONNACK. Returns (accepted, detail)."""
        try:
            self._client.connect(self.endpoint.host, self.endpoint.port, keepalive=30)
        except (OSError, ssl.SSLError) as exc:
            return False, f"connection error: {exc}"
        self._client.loop_start()
        self._running = True
        with self._cond:
            self._cond.wait_for(lambda: self._connect_rc is not None, self.timeout)
            rc = self._connect_rc
        if rc is None:
            self.close()
            return False, "no CONNACK (timeout)"
        if rc.is_failure:
            self.close()
            return False, f"CONNACK: {rc}"
        return True, "CONNACK: Success"

    def subscribe(self, topic_filter: str, qos: int = 1) -> list | None:
        """Subscribe and return the SUBACK reason codes, or None on timeout."""
        _, mid = self._client.subscribe(topic_filter, qos=qos)
        with self._cond:
            self._cond.wait_for(lambda: mid in self._suback, self.timeout)
            return self._suback.get(mid)

    def unsubscribe(self, topic_filter: str) -> None:
        self._client.unsubscribe(topic_filter)

    def publish(self, topic: str, payload: bytes, qos: int = 1) -> mqtt.ReasonCode | None:
        """Publish (never retained) and return the PUBACK reason code, or None."""
        info = self._client.publish(topic, payload, qos=qos, retain=False)
        with self._cond:
            self._cond.wait_for(lambda: info.mid in self._puback, self.timeout)
            return self._puback.get(info.mid)

    def wait_for_message(self, topic: str, payload: bytes, timeout: float | None = None) -> bool:
        def found() -> bool:
            return any(m.topic == topic and m.payload == payload for m in self._messages)

        with self._cond:
            return self._cond.wait_for(found, self.timeout if timeout is None else timeout)

    def close(self) -> None:
        if self._running:
            self._client.disconnect()
            self._client.loop_stop()
            self._running = False


def suback_granted(codes: list | None) -> bool:
    return bool(codes) and not any(c.is_failure for c in codes)


def describe_codes(codes: list | None) -> str:
    if codes is None:
        return "no SUBACK"
    return ", ".join(str(c) for c in codes)
