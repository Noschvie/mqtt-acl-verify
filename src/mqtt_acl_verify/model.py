# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration and test case model.

Passwords are never stored in YAML files. Each identity names an
environment variable that holds its password.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import yaml

PROBE_PLACEHOLDER = "{probe}"


class ConfigError(ValueError):
    """Raised for invalid configuration or test case files."""


class Action(str, Enum):
    CONNECT = "connect"
    PUBLISH = "publish"
    RECEIVE = "receive"


class Expect(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class Endpoint:
    name: str
    host: str
    port: int
    tls: bool = False
    ca_file: str | None = None
    protocol: int = 5  # 5 = MQTT v5, 4 = MQTT v3.1.1


@dataclass(frozen=True)
class Identity:
    name: str
    username: str | None
    password_env: str | None = None
    client_id: str | None = None
    endpoint: str | None = None

    def password(self) -> str | None:
        if not self.password_env:
            return None
        value = os.environ.get(self.password_env)
        if value is None:
            raise ConfigError(
                f"identity '{self.name}': environment variable "
                f"{self.password_env} is not set"
            )
        return value

    def make_client_id(self) -> str:
        """Use a unique client ID unless one is configured explicitly.

        Reusing the client ID of a live device would disconnect that device.
        """
        if self.client_id:
            return self.client_id
        base = self.username or self.name
        return f"{base}-aclprobe-{secrets.token_hex(3)}"


@dataclass(frozen=True)
class Case:
    id: str
    client: str
    action: Action
    expect: Expect
    topic: str | None = None
    publish_topic: str | None = None
    endpoint: str | None = None
    live: bool = False
    description: str = ""

    def resolve_topics(self) -> tuple[str | None, str | None]:
        """Return (filter_or_topic, concrete_topic) with {probe} replaced."""
        token = f"_aclprobe_{secrets.token_hex(3)}"
        topic = self.topic.replace(PROBE_PLACEHOLDER, token) if self.topic else None
        concrete = self.publish_topic or self.topic
        concrete = concrete.replace(PROBE_PLACEHOLDER, token) if concrete else None
        return topic, concrete


@dataclass
class Config:
    endpoints: dict[str, Endpoint]
    identities: dict[str, Identity]
    observer: str
    default_endpoint: str
    timeout: float = 2.0
    cases: list[Case] = field(default_factory=list)

    def endpoint_for(self, case: Case | None, identity: Identity) -> Endpoint:
        name = (case.endpoint if case else None) or identity.endpoint or self.default_endpoint
        try:
            return self.endpoints[name]
        except KeyError:
            raise ConfigError(f"unknown endpoint '{name}'") from None


def _has_wildcard(topic: str) -> bool:
    return "+" in topic.split("/") or topic.endswith("#")


def _validate_case(case: Case, identities: dict[str, Identity], endpoints: dict[str, Endpoint]) -> None:
    where = f"case '{case.id}'"
    if case.client not in identities:
        raise ConfigError(f"{where}: unknown client '{case.client}'")
    if case.endpoint and case.endpoint not in endpoints:
        raise ConfigError(f"{where}: unknown endpoint '{case.endpoint}'")
    if case.action is Action.CONNECT:
        return
    if not case.topic:
        raise ConfigError(f"{where}: 'topic' is required for {case.action.value}")
    concrete = case.publish_topic or case.topic
    if case.action is Action.PUBLISH and _has_wildcard(case.topic):
        raise ConfigError(f"{where}: publish topic must not contain wildcards")
    if case.action is Action.RECEIVE and _has_wildcard(concrete):
        raise ConfigError(
            f"{where}: subscription filter has wildcards, set 'publish_topic' "
            "to a concrete topic that matches it"
        )
    if PROBE_PLACEHOLDER not in concrete and not case.live:
        raise ConfigError(
            f"{where}: topic '{concrete}' has no {PROBE_PLACEHOLDER} placeholder. "
            "Test messages on real topics can trigger devices. "
            "Add {probe} as last level or set 'live: true' deliberately."
        )


def _load_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping at top level")
    return data


def load_config(config_path: Path, cases_path: Path | None = None) -> Config:
    data = _load_yaml(config_path)

    endpoints: dict[str, Endpoint] = {}
    for name, ep in (data.get("endpoints") or {}).items():
        endpoints[name] = Endpoint(
            name=name,
            host=ep["host"],
            port=int(ep["port"]),
            tls=bool(ep.get("tls", False)),
            ca_file=ep.get("ca_file"),
            protocol=int(ep.get("protocol", 5)),
        )
    if not endpoints:
        raise ConfigError(f"{config_path}: no endpoints defined")

    identities: dict[str, Identity] = {}
    for name, ident in (data.get("identities") or {}).items():
        ident = ident or {}
        identities[name] = Identity(
            name=name,
            username=ident.get("username"),
            password_env=ident.get("password_env"),
            client_id=ident.get("client_id"),
            endpoint=ident.get("endpoint"),
        )

    observer = data.get("observer")
    if observer not in identities:
        raise ConfigError(f"{config_path}: 'observer' must name a defined identity")

    default_endpoint = data.get("default_endpoint") or next(iter(endpoints))
    if default_endpoint not in endpoints:
        raise ConfigError(f"{config_path}: unknown default_endpoint '{default_endpoint}'")
    for ident in identities.values():
        if ident.endpoint and ident.endpoint not in endpoints:
            raise ConfigError(f"identity '{ident.name}': unknown endpoint '{ident.endpoint}'")

    config = Config(
        endpoints=endpoints,
        identities=identities,
        observer=observer,
        default_endpoint=default_endpoint,
        timeout=float(data.get("timeout", 2.0)),
    )

    if cases_path is not None:
        config.cases = load_cases(cases_path, identities, endpoints)
    return config


def load_cases(path: Path, identities: dict[str, Identity], endpoints: dict[str, Endpoint]) -> list[Case]:
    data = _load_yaml(path)
    cases: list[Case] = []
    seen: set[str] = set()
    for raw in data.get("cases") or []:
        try:
            case = Case(
                id=str(raw["id"]),
                client=raw["client"],
                action=Action(raw["action"]),
                expect=Expect(raw["expect"]),
                topic=raw.get("topic"),
                publish_topic=raw.get("publish_topic"),
                endpoint=raw.get("endpoint"),
                live=bool(raw.get("live", False)),
                description=raw.get("description", ""),
            )
        except KeyError as exc:
            raise ConfigError(f"{path}: case is missing field {exc}") from exc
        except ValueError as exc:
            raise ConfigError(f"{path}: case '{raw.get('id')}': {exc}") from exc
        if case.id in seen:
            raise ConfigError(f"{path}: duplicate case id '{case.id}'")
        seen.add(case.id)
        _validate_case(case, identities, endpoints)
        cases.append(case)
    return cases
