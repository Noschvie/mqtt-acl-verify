# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parse a Mosquitto 2.x log written with 'log_type all' (or at least debug).

Relevant lines (after an optional timestamp prefix ending in ': '):

    New client connected from 10.0.0.5:51234 as DVES_1A2B3C (p2, c1, k30, u'kitchen').
    Received PUBLISH from DVES_1A2B3C (d0, q0, r1, m0, 'tele/kitchen/LWT', ... (6 bytes))
    Denied PUBLISH from DVES_1A2B3C (d0, q1, r0, m1, 'stat/other/POWER', ... (2 bytes))
    Received SUBSCRIBE from DVES_1A2B3C
        cmnd/kitchen/# (QoS 0)
"""

from __future__ import annotations

import re
from typing import Iterable

from .model import Direction, Inventory

# Patterns are searched, not anchored, so any timestamp format before them works.
_CONNECT = re.compile(r"New client connected from \S+ as (?P<cid>\S+) \((?P<flags>[^)]*)\)")
_USER = re.compile(r"u'(?P<user>[^']*)'")
_PUBLISH = re.compile(r"(?P<kind>Received|Denied) PUBLISH from (?P<cid>\S+) \(d\d, q\d, r\d, m\d+, '(?P<topic>[^']*)'")
_SUBSCRIBE = re.compile(r"Received SUBSCRIBE from (?P<cid>\S+)\s*$")
_SUB_TOPIC = re.compile(r"\t(?P<topic>\S+) \(QoS \d\)\s*$")


def parse(lines: Iterable[str], inventory: Inventory | None = None) -> Inventory:
    inv = inventory or Inventory()
    pending_sub: str | None = None

    for raw in lines:
        line = raw.rstrip("\r\n")

        if pending_sub is not None:
            m = _SUB_TOPIC.search(line)
            if m:
                inv.add(pending_sub, Direction.SUBSCRIBE, m["topic"])
                continue
            pending_sub = None

        if m := _PUBLISH.search(line):
            direction = Direction.PUBLISH if m["kind"] == "Received" else Direction.PUBLISH_DENIED
            inv.add(m["cid"], direction, m["topic"])
        elif m := _SUBSCRIBE.search(line):
            pending_sub = m["cid"]
        elif m := _CONNECT.search(line):
            user = _USER.search(m["flags"])
            inv.usernames[m["cid"]] = user["user"] if user else ""
    return inv
