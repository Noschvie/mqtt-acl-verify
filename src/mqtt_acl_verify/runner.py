# SPDX-License-Identifier: AGPL-3.0-or-later
"""Execute test cases against a broker.

A case passes only if the observed behaviour matches the expectation.
A successful CONNECT or SUBSCRIBE alone is never taken as proof: the
runner checks which messages actually arrive.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from enum import Enum

from .model import Action, Case, Config, ConfigError, Expect
from .probe import Session, describe_codes, suback_granted


class Status(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"


@dataclass
class Result:
    case: Case
    status: Status
    actual: Expect | None
    detail: str


def _payload() -> bytes:
    return f"aclprobe-{secrets.token_hex(8)}".encode()


def _verdict(case: Case, allowed: bool, detail: str) -> Result:
    actual = Expect.ALLOW if allowed else Expect.DENY
    status = Status.PASS if actual is case.expect else Status.FAIL
    return Result(case, status, actual, detail)


class Runner:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._observer: Session | None = None

    def __enter__(self) -> "Runner":
        ident = self.config.identities[self.config.observer]
        observer = Session(ident, self.config.endpoint_for(None, ident), self.config.timeout)
        ok, detail = observer.connect()
        if not ok:
            raise ConfigError(f"observer '{ident.name}' cannot connect: {detail}")
        self._observer = observer
        return self

    def __exit__(self, *exc) -> None:
        if self._observer:
            self._observer.close()

    @property
    def observer(self) -> Session:
        assert self._observer is not None, "use Runner as a context manager"
        return self._observer

    def run(self, case: Case) -> Result:
        ident = self.config.identities[case.client]
        try:
            session = Session(ident, self.config.endpoint_for(case, ident), self.config.timeout)
        except ConfigError as exc:
            return Result(case, Status.ERROR, None, str(exc))
        try:
            if case.action is Action.CONNECT:
                ok, detail = session.connect()
                return _verdict(case, ok, detail)
            ok, detail = session.connect()
            if not ok:
                return Result(case, Status.ERROR, None, f"client cannot connect ({detail})")
            if case.action is Action.PUBLISH:
                return self._publish(case, session)
            return self._receive(case, session)
        finally:
            session.close()

    def _publish(self, case: Case, session: Session) -> Result:
        _, topic = case.resolve_topics()
        codes = self.observer.subscribe(topic)
        if not suback_granted(codes):
            return Result(case, Status.ERROR, None,
                          f"observer cannot subscribe to {topic} ({describe_codes(codes)})")
        try:
            payload = _payload()
            puback = session.publish(topic, payload)
            arrived = self.observer.wait_for_message(topic, payload)
            detail = f"PUBACK: {puback if puback is not None else 'none'}; "
            detail += "message delivered" if arrived else "message not delivered"
            return _verdict(case, arrived, detail)
        finally:
            self.observer.unsubscribe(topic)

    def _receive(self, case: Case, session: Session) -> Result:
        topic_filter, topic = case.resolve_topics()
        codes = session.subscribe(topic_filter)
        # Control subscription: proves the injected message really exists on the broker.
        control = self.observer.subscribe(topic)
        if not suback_granted(control):
            return Result(case, Status.ERROR, None,
                          f"observer cannot subscribe to {topic} ({describe_codes(control)})")
        try:
            payload = _payload()
            self.observer.publish(topic, payload)
            if not self.observer.wait_for_message(topic, payload):
                return Result(case, Status.ERROR, None,
                              f"observer message on {topic} not seen by observer itself")
            received = session.wait_for_message(topic, payload)
            detail = f"SUBACK: {describe_codes(codes)}; "
            detail += "message received" if received else "message not received"
            return _verdict(case, received, detail)
        finally:
            self.observer.unsubscribe(topic)


def run_all(config: Config) -> list[Result]:
    with Runner(config) as runner:
        return [runner.run(case) for case in config.cases]
