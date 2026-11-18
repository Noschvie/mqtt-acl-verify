# SPDX-License-Identifier: AGPL-3.0-or-later
"""Command line interface: `mqtt-acl-verify run` and `mqtt-acl-verify inventory`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, report
from .inventory import mosquitto as mosquitto_log
from .model import ConfigError, load_config
from .runner import Status, run_all


def _cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args.config, args.cases)
    if args.only:
        wanted = set(args.only)
        config.cases = [c for c in config.cases if c.id in wanted]
    results = run_all(config)
    sys.stdout.write(report.text(results))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report.markdown(results), encoding="utf-8")
    if any(r.status is not Status.PASS for r in results):
        return 1
    return 0


def _cmd_inventory(args: argparse.Namespace) -> int:
    inv = None
    for path in args.logfile:
        with path.open(encoding="utf-8", errors="replace") as fh:
            inv = mosquitto_log.parse(fh, inv)
    if inv is None:
        return 0
    if args.placeholders:
        inv = inv.with_placeholders()
    if args.by_user:
        inv = inv.by_username()
    out = inv.to_csv() if args.format == "csv" else inv.to_markdown()
    sys.stdout.write(out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mqtt-acl-verify", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run ACL test cases against a broker")
    run.add_argument("-c", "--config", type=Path, required=True, help="endpoints and identities (YAML)")
    run.add_argument("-t", "--cases", type=Path, required=True, help="test cases (YAML)")
    run.add_argument("-r", "--report", type=Path, help="write a Markdown report to this file")
    run.add_argument("--only", nargs="+", metavar="ID", help="run only these case IDs")
    run.set_defaults(func=_cmd_run)

    inv = sub.add_parser("inventory", help="build a topic inventory from Mosquitto debug logs")
    inv.add_argument("logfile", type=Path, nargs="+")
    inv.add_argument("-f", "--format", choices=["md", "csv"], default="md")
    inv.add_argument("-p", "--placeholders", action="store_true",
                     help="replace the client's own username / client ID in topics by %%u / %%c")
    inv.add_argument("-u", "--by-user", action="store_true",
                     help="merge all client IDs of a username into one row")
    inv.set_defaults(func=_cmd_inventory)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
