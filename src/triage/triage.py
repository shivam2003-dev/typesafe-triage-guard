"""Support-ticket triage: classification + composite priority + confidence-gated routing.

Composition follows three documented TypeSafe patterns directly:

- Batched, parallel questions over one state
  (docs.typesafe.ai/cookbooks/parallel_questions.md)
- Composite scoring: independent dimensions scored separately, combined with
  code-owned weights (docs.typesafe.ai/patterns/composite-scoring.md)
- Confidence-gated routing: the answer says *what*, confidence says *whether
  to act* (docs.typesafe.ai/patterns/confidence-routing.md)

The guard() hazard battery runs first and can short-circuit the whole
pipeline -- if a ticket is blocked outright, there is no reason to spend a
second call classifying it. This mirrors the building guide's own criterion
for when a second request is warranted: "an earlier answer is needed to ...
determine the next options."
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from typesafe_sdk import Choice, Noul, Score

from triage.client import SystemOneClient
from triage.guardrail import GuardResult, guard

Route = Literal["auto", "review", "escalate", "blocked"]

DEPARTMENTS = {
    "billing": "Payment, invoices, refunds, or subscription issues.",
    "technical": "Bugs, integration failures, or the product not working as expected.",
    "sales": "Pricing questions, upgrades, or new-account interest.",
    "account": "Login, access, or account-settings issues.",
}

CLASSIFICATION_QUESTIONS = {
    "department": Choice(
        instructions="Which team should handle this support ticket?",
        criteria=DEPARTMENTS,
    ),
    "frustration": Score(
        instructions="How frustrated does the customer sound?",
        criteria=[
            "Calm, just stating facts.",
            "Mildly annoyed but civil.",
            "Frustrated, pointed language.",
            "Very angry, strong language or threats to leave.",
        ],
    ),
    "urgency": Score(
        instructions="How time-sensitive is this ticket for the customer?",
        criteria=[
            "No particular urgency.",
            "Would like a response soon.",
            "Actively blocked; needs a response today.",
            "Losing money or users right now.",
        ],
    ),
    "is_urgent": Noul(
        instructions="The message itself explicitly conveys urgency or time pressure.",
    ),
}

# Composite priority weights -- code-owned, not learned by the model.
# Must sum to 1.0; see docs.typesafe.ai/patterns/composite-scoring.md.
PRIORITY_WEIGHTS = {
    "urgency": 0.35,
    "frustration": 0.30,
    "is_urgent": 0.15,
    "guard_severity": 0.20,
}

DEPARTMENT_CONFIDENCE_FLOOR = 0.6
ESCALATE_AT = 0.66


@dataclass
class TriageResult:
    route: Route
    guard: GuardResult
    department: str | None = None
    department_confidence: float | None = None
    frustration: float | None = None
    urgency: float | None = None
    is_urgent: float | None = None
    priority: float | None = None
    reason: str = ""


def _composite_priority(urgency: float, frustration: float, is_urgent: float, severity: float) -> float:
    """Weighted blend of independently-scored dimensions, each normalized to [0, 1]
    before weighting (urgency/frustration are 0-3 scores, severity is 0-3)."""
    return round(
        PRIORITY_WEIGHTS["urgency"] * (urgency / 3)
        + PRIORITY_WEIGHTS["frustration"] * (frustration / 3)
        + PRIORITY_WEIGHTS["is_urgent"] * is_urgent
        + PRIORITY_WEIGHTS["guard_severity"] * (severity / 3),
        4,
    )


def triage(
    ticket_text: str,
    *,
    client: SystemOneClient,
    policy: str = "strict",
) -> TriageResult:
    guard_result = guard(ticket_text, client=client, policy=policy)

    if guard_result.action == "block":
        return TriageResult(
            route="blocked",
            guard=guard_result,
            reason=f"blocked by guardrail: {guard_result.triggered_by}",
        )

    response = client.system_one(ticket_text, CLASSIFICATION_QUESTIONS)

    department = response.answers["department"]
    frustration = response.answers["frustration"].score
    urgency = response.answers["urgency"].score
    is_urgent = response.answers["is_urgent"].noul

    priority = _composite_priority(urgency, frustration, is_urgent, guard_result.severity)

    if department.confidence < DEPARTMENT_CONFIDENCE_FLOOR:
        route: Route = "review"
        reason = f"low routing confidence ({department.confidence:.2f} < {DEPARTMENT_CONFIDENCE_FLOOR})"
    elif guard_result.action == "review" or guard_result.action == "support":
        route = "review"
        reason = f"guardrail flagged for review: {guard_result.triggered_by}"
    elif priority >= ESCALATE_AT:
        route = "escalate"
        reason = f"composite priority {priority:.2f} >= {ESCALATE_AT}"
    else:
        route = "auto"
        reason = "within normal thresholds"

    return TriageResult(
        route=route,
        guard=guard_result,
        department=department.choice,
        department_confidence=round(department.confidence, 4),
        frustration=round(frustration, 4),
        urgency=round(urgency, 4),
        is_urgent=round(is_urgent, 4),
        priority=priority,
        reason=reason,
    )
