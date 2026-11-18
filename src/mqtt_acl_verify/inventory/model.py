# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum


class Direction(str, Enum):
    PUBLISH = "publish"
    PUBLISH_DENIED = "publish-denied"
    SUBSCRIBE = "subscribe"


@dataclass(frozen=True, order=True)
class InventoryEntry:
    username: str
    client_id: str
    direction: Direction
    topic: str


@dataclass
class Inventory:
    counts: Counter = field(default_factory=Counter)
    usernames: dict[str, str] = field(default_factory=dict)  # client_id -> username

    def add(self, client_id: str, direction: Direction, topic: str) -> None:
        username = self.usernames.get(client_id, "?")
        self.counts[InventoryEntry(username, client_id, direction, topic)] += 1

    def with_placeholders(self) -> "Inventory":
        """Replace the client's own username/client ID in topic levels by %u / %c.

        This makes per-device rules visible as one generic profile rule.
        """
        result = Inventory(usernames=dict(self.usernames))
        for entry, n in self.counts.items():
            levels = []
            for level in entry.topic.split("/"):
                if entry.username not in ("?", "") and level == entry.username:
                    levels.append("%u")
                elif level == entry.client_id:
                    levels.append("%c")
                else:
                    levels.append(level)
            generic = InventoryEntry(entry.username, entry.client_id, entry.direction, "/".join(levels))
            result.counts[generic] += n
        return result

    def by_username(self) -> "Inventory":
        """Merge all client IDs of a username into one row (client ID shown as '*')."""
        result = Inventory(usernames=dict(self.usernames))
        for entry, n in self.counts.items():
            merged = InventoryEntry(entry.username, "*", entry.direction, entry.topic)
            result.counts[merged] += n
        return result

    def entries(self) -> list[tuple[InventoryEntry, int]]:
        return sorted(self.counts.items())

    def to_csv(self) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["username", "client_id", "direction", "topic", "count"])
        for e, n in self.entries():
            writer.writerow([e.username, e.client_id, e.direction.value, e.topic, n])
        return buf.getvalue()

    def to_markdown(self) -> str:
        lines = [
            "| Username | Client ID | Direction | Topic | Count |",
            "|---|---|---|---|---|",
        ]
        for e, n in self.entries():
            lines.append(f"| {e.username} | {e.client_id} | {e.direction.value} | `{e.topic}` | {n} |")
        return "\n".join(lines) + "\n"
