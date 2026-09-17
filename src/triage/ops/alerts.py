"""Observability alert triage.

Same shape as triage.triage(): batched Choice/Score/Noul questions over one
alert (log line, page payload, metric-breach description), composite
severity, confidence-gated routing. Point of this module: the *pattern*
transfers across domains unchanged -- only the questions and thresholds are
domain-specific.

Typical wiring: an alert webhook (Prometheus Alertmanager, Datadog monitor,
PagerDuty event) calls `alert_triage(alert_text, client=client)` before
paging, to decide auto-page vs. ticket vs. suppress-as-duplicate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from typesafe_sdk import Choice, Noul, Score

from triage.client import SystemOneClient

Route = Literal["auto_page", "ticket", "suppress_duplicate", "review"]

SERVICES = {
    "api": "The public API / request-serving layer.",
    "database": "Primary database, replicas, or connection pooling.",
    "queue": "Message queue, background workers, or job processing.",
    "cache": "Caching layer (Redis/memcached-style).",
    "network": "Load balancer, DNS, CDN, or inter-service networking.",
    "unknown": "Cannot be attributed to a specific owning service from this text alone.",
}

ROOT_CAUSES = {
    "deploy": "Correlates with a recent deploy or config rollout.",
    "capacity": "Resource exhaustion -- CPU, memory, disk, connection pool, or rate limit.",
    "dependency": "An upstream or downstream dependency is failing or slow.",
    "config_drift": "A configuration value or feature flag looks wrong or stale.",
    "unknown": "No clear root-cause signal in the text.",
}

ALERT_QUESTIONS = {
    "service": Choice(
        instructions="Which service or subsystem does this alert most likely belong to?",
        criteria=SERVICES,
    ),
    "root_cause": Choice(
        instructions="What does the text suggest is the most likely root-cause category?",
        criteria=ROOT_CAUSES,
    ),
    "severity": Score(
        instructions="How severe is the customer/business impact described or implied?",
        criteria=[
            "Informational -- no user-facing impact.",
            "Warning -- degraded performance, no outage.",
            "Major -- a feature or a subset of users is broken.",
            "Critical -- widespread outage or data-loss risk.",
        ],
    ),
    "is_duplicate": Noul(
        instructions=(
            "This alert describes the same underlying problem as the open "
            "incidents listed under `open_incidents` in the state, not merely "
            "the same service."
        ),
    ),
}

# Weights sum to 1.0; is_duplicate pulls priority *down* via (1 - p).
PRIORITY_WEIGHTS = {"severity": 0.75, "not_duplicate": 0.25}

SERVICE_CONFIDENCE_FLOOR = 0.6
AUTO_PAGE_AT = 0.66


@dataclass
class AlertTriageResult:
    route: Route
    service: str
    service_confidence: float
    root_cause: str
    severity: float
    severity_label: str
    is_duplicate: float
    priority: float
    reason: str


def alert_triage(
    alert_text: str,
    *,
    client: SystemOneClient,
    open_incidents: list[str] | None = None,
) -> AlertTriageResult:
    state: Any = (
        {"alert": alert_text, "open_incidents": open_incidents}
        if open_incidents
        else alert_text
    )

    response = client.system_one(state, ALERT_QUESTIONS)

    service = response.answers["service"]
    root_cause = response.answers["root_cause"]
    severity_answer = response.answers["severity"]
    is_duplicate = response.answers["is_duplicate"].noul

    priority = round(
        PRIORITY_WEIGHTS["severity"] * (severity_answer.score / 3)
        + PRIORITY_WEIGHTS["not_duplicate"] * (1 - is_duplicate),
        4,
    )

    if is_duplicate >= 0.7:
        route: Route = "suppress_duplicate"
        reason = f"is_duplicate={is_duplicate:.2f} >= 0.70"
    elif service.confidence < SERVICE_CONFIDENCE_FLOOR:
        route = "review"
        reason = f"low service-attribution confidence ({service.confidence:.2f})"
    elif priority >= AUTO_PAGE_AT:
        route = "auto_page"
        reason = f"priority {priority:.2f} >= {AUTO_PAGE_AT}"
    else:
        route = "ticket"
        reason = "below page threshold"

    return AlertTriageResult(
        route=route,
        service=service.choice,
        service_confidence=round(service.confidence, 4),
        root_cause=root_cause.choice,
        severity=round(severity_answer.score, 4),
        severity_label=severity_answer.legend[round(severity_answer.score)],
        is_duplicate=round(is_duplicate, 4),
        priority=priority,
        reason=reason,
    )
