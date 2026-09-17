from triage.ops.alerts import alert_triage
from triage.ops.deploy_gate import risk_gate


def test_outage_alert_is_higher_priority_than_minor_one(client):
    minor = alert_triage(
        "Background job queue depth is slightly above baseline, no user impact expected.",
        client=client,
    )
    critical = alert_triage(
        "Total outage: the load balancer is returning errors for all "
        "traffic across every service. Nothing is reachable. Critical "
        "widespread impact.",
        client=client,
    )
    assert critical.priority > minor.priority


def test_duplicate_alert_is_suppressed(client):
    r = alert_triage(
        "DNS resolution failing intermittently, same as the open incident.",
        client=client,
        open_incidents=[
            "DNS resolution failing intermittently, same as the open incident.",
        ],
    )
    assert r.is_duplicate >= 0.5


def test_risky_migration_pr_is_flagged(client):
    r = risk_gate(
        "Adds a database migration dropping a column and backfilling data, "
        "no rollback plan or feature flag mentioned, irreversible change.",
        client=client,
        policy="strict",
    )
    assert r.action in {"review", "block"}


def test_trivial_readme_pr_passes(client):
    r = risk_gate(
        "Fixes a typo in the README documentation file. No code changes.",
        client=client,
        policy="strict",
    )
    assert r.action == "pass"
