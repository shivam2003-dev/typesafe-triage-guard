"""triage-guard: three composable judgment pipelines on TypeSafe's Jev --
support-ticket triage, observability alert triage, and a deploy-risk gate --
all built from the same reusable battery/composite-scoring/confidence-gate
patterns."""

from triage.battery import BatteryResult, run_battery
from triage.guardrail import GuardResult, guard
from triage.ops.alerts import AlertTriageResult, alert_triage
from triage.ops.deploy_gate import DeployGateResult, risk_gate
from triage.triage import TriageResult, triage

__all__ = [
    "BatteryResult",
    "run_battery",
    "GuardResult",
    "guard",
    "TriageResult",
    "triage",
    "AlertTriageResult",
    "alert_triage",
    "DeployGateResult",
    "risk_gate",
]
__version__ = "0.2.0"
