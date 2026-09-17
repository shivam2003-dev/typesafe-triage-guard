"""Command-line entry point for all three pipelines.

    triage-guard ticket run "My card was charged twice, please help ASAP"
    triage-guard ticket run --file examples/sample_tickets.json

    triage-guard alert run "p99 latency on checkout-api jumped to 8s after the 14:02 deploy"
    triage-guard alert run --file examples/sample_alerts.json

    triage-guard deploy-gate run "Adds a migration dropping the legacy_users column, no rollback noted."
    triage-guard deploy-gate run --file examples/sample_prs.json

Any subcommand accepts --mock (force the offline heuristic client),
--policy strict|permissive, and --json (machine-readable output).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from triage.client import get_client
from triage.ops.alerts import alert_triage
from triage.ops.deploy_gate import risk_gate
from triage.triage import triage


def _load(text: str | None, file: Path | None) -> list[str]:
    if file:
        return json.loads(file.read_text())
    if text:
        return [text]
    raise SystemExit("provide text or --file")


def _cmd_ticket(args: argparse.Namespace, client: Any) -> list[dict]:
    out = []
    for t in _load(args.text, args.file):
        r = triage(t, client=client, policy=args.policy)
        d = asdict(r)
        d["guard"] = asdict(r.guard)
        out.append(d)
        if not args.json:
            print(f"\n--- {t[:70]!r}{'...' if len(t) > 70 else ''}")
            print(f"  route: {r.route}   ({r.reason})")
            print(f"  guard: {r.guard.action}  severity={r.guard.severity_label!r}")
            if r.route != "blocked":
                print(f"  department={r.department} (conf {r.department_confidence:.2f})  "
                      f"frustration={r.frustration:.2f}  urgency={r.urgency:.2f}  "
                      f"priority={r.priority:.2f}")
    return out


def _cmd_alert(args: argparse.Namespace, client: Any) -> list[dict]:
    out = []
    for a in _load(args.text, args.file):
        r = alert_triage(a, client=client)
        out.append(asdict(r))
        if not args.json:
            print(f"\n--- {a[:70]!r}{'...' if len(a) > 70 else ''}")
            print(f"  route: {r.route}   ({r.reason})")
            print(f"  service={r.service} (conf {r.service_confidence:.2f})  "
                  f"root_cause={r.root_cause}  severity={r.severity_label!r} "
                  f"({r.severity:.2f})  is_duplicate={r.is_duplicate:.2f}  "
                  f"priority={r.priority:.2f}")
    return out


def _cmd_deploy_gate(args: argparse.Namespace, client: Any) -> list[dict]:
    action_map = {"pass": "auto_merge", "review": "require_review", "block": "block_deploy"}
    out = []
    for p in _load(args.text, args.file):
        r = risk_gate(p, client=client, policy=args.policy)
        d = asdict(r)
        d["decision"] = action_map[r.action]
        out.append(d)
        if not args.json:
            print(f"\n--- {p[:70]!r}{'...' if len(p) > 70 else ''}")
            print(f"  decision: {action_map[r.action]}   (triggered_by={r.triggered_by})")
            print(f"  blast_radius={r.severity_label!r} ({r.severity:.2f})  signals={r.signals}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="triage-guard")
    sub = parser.add_subparsers(dest="domain", required=True)

    for name, help_ in [
        ("ticket", "Support-ticket triage + safety guardrail."),
        ("alert", "Observability alert triage."),
        ("deploy-gate", "Deploy / PR risk gate."),
    ]:
        p = sub.add_parser(name, help=help_)
        p.set_defaults(domain=name)
        run = p.add_subparsers(dest="command", required=True).add_parser("run")
        run.add_argument("text", nargs="?")
        run.add_argument("--file", type=Path)
        run.add_argument("--policy", default="strict", choices=["strict", "permissive"])
        run.add_argument("--mock", action="store_true")
        run.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    client = get_client(mock=True if args.mock else None)

    with client:
        if args.domain == "ticket":
            results = _cmd_ticket(args, client)
        elif args.domain == "alert":
            results = _cmd_alert(args, client)
        elif args.domain == "deploy-gate":
            results = _cmd_deploy_gate(args, client)
        else:  # pragma: no cover
            parser.error(f"unknown domain {args.domain!r}")
            return 1

    if args.json:
        print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
