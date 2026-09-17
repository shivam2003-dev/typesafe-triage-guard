"""Deploy / PR risk gate.

Reuses the same generic hazard-battery engine as guardrail.py
(triage.battery.run_battery) with a deploy-risk battery instead of a
content-safety one -- same composition pattern, different domain, proving
the engine isn't guardrail-specific.

Typical wiring: a CI job calls `risk_gate(pr_diff_and_description,
client=client)` and fails the "merge" or "auto-deploy" check on
action == "block", or routes to a required human reviewer on "review".
"""

from __future__ import annotations

from typing import Any

from typesafe_sdk import Noul, Score

from triage.battery import Battery, BatteryResult, Policy, run_battery
from triage.client import SystemOneClient

DeployGateResult = BatteryResult

DEPLOY_HAZARDS: Battery = {
    "touches_prod_credentials": (
        Noul(
            instructions=(
                "This change adds, modifies, or reads production credentials, "
                "API keys, or secrets (in code, config, or CI files)."
            ),
        ),
        "review",
    ),
    "touches_migration": (
        Noul(
            instructions=(
                "This change includes a database schema migration or a "
                "data-backfill script."
            ),
        ),
        "review",
    ),
    "no_rollback_plan": (
        Noul(
            instructions=(
                "This change is described as risky or irreversible (e.g. a "
                "migration, a breaking API change, a delete/drop) but the "
                "description does not mention a rollback plan, feature flag, "
                "or staged rollout."
            ),
        ),
        "block",
    ),
    "touches_shared_infra": (
        Noul(
            instructions=(
                "This change modifies shared infrastructure that many "
                "services depend on -- e.g. the load balancer, the service "
                "mesh, a shared library, or the CI pipeline itself."
            ),
        ),
        "review",
    ),
}

BLAST_RADIUS_QUESTION = Score(
    instructions="How many users or downstream services could this change affect if it goes wrong?",
    criteria=[
        "None -- isolated to a single, non-critical component with tests.",
        "Small -- one service or a small subset of users.",
        "Large -- a whole product surface or most users.",
        "Everyone -- affects all users or all services (e.g. shared infra, auth, billing).",
    ],
)

POLICIES: dict[str, Policy] = {
    "strict": {"review": 0.40, "block": 0.70, "severity_block": 2.0},
    "permissive": {"review": 0.50, "block": 0.85, "severity_block": 2.5},
}


def risk_gate(
    pr_text: Any,
    *,
    client: SystemOneClient,
    policy: str = "strict",
) -> BatteryResult:
    """Screen a PR diff + description for deploy risk before merge/auto-deploy."""
    return run_battery(
        pr_text,
        client=client,
        battery=DEPLOY_HAZARDS,
        severity_question=BLAST_RADIUS_QUESTION,
        policies=POLICIES,
        policy=policy,
    )
