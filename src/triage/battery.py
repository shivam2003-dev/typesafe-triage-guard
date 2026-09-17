"""Generic reusable "hazard battery" engine.

The pattern from TypeSafe's guardrails cookbook
(docs.typesafe.ai/cookbooks/llm_guardrails.md) generalizes past content
safety: N independent Noul "does this fire?" questions, batched with one
severity Score, resolved into a routing action by a named, code-owned
policy. guardrail.py (message safety) and ops/deploy_gate.py (deploy risk)
both just plug a different battery + policy table into run_battery().
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from typesafe_sdk import Noul, Score

from triage.client import SystemOneClient

RouteAction = Literal["pass", "review", "block", "support"]

# name -> (question, action to take if this hazard fires above its threshold)
Battery = dict[str, tuple[Noul, RouteAction]]
Policy = dict[str, float]  # {"review": ..., "block": ..., "severity_block": ...}


@dataclass
class BatteryResult:
    action: RouteAction
    signals: dict[str, float]
    severity: float
    severity_label: str
    triggered_by: str | None
    raw_model: str


def run_battery(
    state: Any,
    *,
    client: SystemOneClient,
    battery: Battery,
    severity_question: Score,
    policies: dict[str, Policy],
    policy: str,
) -> BatteryResult:
    if policy not in policies:
        raise ValueError(f"Unknown policy {policy!r}; choose one of {list(policies)}")
    thresholds = policies[policy]

    questions: dict[str, Any] = {name: q for name, (q, _action) in battery.items()}
    questions["severity"] = severity_question

    # One batched call for the whole battery -- see cookbooks/parallel_questions.md
    # for why this beats one round trip per question (same accuracy, ~10x cheaper/faster
    # once the shared `state` is non-trivial in size).
    response = client.system_one(state, questions)

    signals = {name: response.answers[name].noul for name in battery}
    severity_answer = response.answers["severity"]
    severity = severity_answer.score
    severity_label = severity_answer.legend[round(severity)]

    action: RouteAction = "pass"
    triggered_by: str | None = None
    priority = {"block": 3, "support": 2, "review": 1, "pass": 0}

    for name, (_q, fire_action) in battery.items():
        p = signals[name]
        if fire_action == "block" and p >= thresholds["block"]:
            candidate: RouteAction = "block"
        elif fire_action == "support" and p >= thresholds["review"]:
            candidate = "support"
        elif fire_action == "review" and p >= thresholds["review"]:
            candidate = "review"
        elif p >= thresholds["review"]:
            candidate = "review"
        else:
            continue

        if priority[candidate] > priority[action]:
            action, triggered_by = candidate, name

    if severity >= thresholds["severity_block"] and priority["block"] > priority[action]:
        action, triggered_by = "block", "severity"

    return BatteryResult(
        action=action,
        signals=signals,
        severity=severity,
        severity_label=severity_label,
        triggered_by=triggered_by,
        raw_model=response.model,
    )
