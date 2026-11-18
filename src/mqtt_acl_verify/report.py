# SPDX-License-Identifier: AGPL-3.0-or-later
"""Render test results as Markdown or plain text."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from .runner import Result, Status

ICON = {Status.PASS: "✅", Status.FAIL: "❌", Status.ERROR: "⚠️"}


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def summary(results: list[Result]) -> str:
    counts = Counter(r.status for r in results)
    return (f"{len(results)} cases: {counts[Status.PASS]} passed, "
            f"{counts[Status.FAIL]} failed, {counts[Status.ERROR]} errors")


def markdown(results: list[Result]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# MQTT ACL verification report",
        "",
        f"**Run:** {now}  ",
        f"**Result:** {summary(results)}",
        "",
        "| Status | ID | Client | Action | Topic | Expected | Actual | Detail |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        c = r.case
        topic = c.topic or ""
        if c.publish_topic:
            topic += f" → {c.publish_topic}"
        lines.append(
            f"| {ICON[r.status]} | {_cell(c.id)} | {_cell(c.client)} | {c.action.value} "
            f"| `{_cell(topic)}` | {c.expect.value} "
            f"| {r.actual.value if r.actual else '–'} | {_cell(r.detail)} |"
        )
    return "\n".join(lines) + "\n"


def text(results: list[Result]) -> str:
    lines = []
    for r in results:
        c = r.case
        actual = r.actual.value if r.actual else "-"
        lines.append(f"{r.status.value.upper():5} {c.id:30} expect={c.expect.value:5} "
                     f"actual={actual:5} {r.detail}")
    lines.append(summary(results))
    return "\n".join(lines) + "\n"
