# triage-guard

Three composable judgment pipelines built on [TypeSafe](https://typesafe.ai)'s
System One model, **Jev** — a model that returns typed, calibrated
probabilities instead of generated text. This repo is R&D / a worked example,
not a product: it exists to test what the TypeSafe primitives (Noul, Choice,
Score) are actually good for outside the docs' own demos, across three
different domains, with one shared architecture.

| Pipeline | What it does | CLI |
|---|---|---|
| **Support-ticket triage** | routes + prioritizes a support ticket, gated by a safety guardrail | `triage-guard ticket run` |
| **Observability alert triage** | attributes an alert to a service/root-cause, dedupes, decides auto-page vs. ticket | `triage-guard alert run` |
| **Deploy / PR risk gate** | screens a PR diff+description for deploy risk before merge/auto-deploy | `triage-guard deploy-gate run` |

All three are ~120 lines of composition logic each, built from the **same
four reusable patterns**, taken directly from TypeSafe's own docs and
cookbooks rather than invented here:

1. **Batched, parallel questions over one state** — every pipeline asks its
   whole question set in a single `system_one()` call rather than one
   round trip per question. TypeSafe's own
   [parallel-questions cookbook](https://docs.typesafe.ai/cookbooks/parallel_questions.md)
   reports ~10–12x cost/latency improvement from batching a 13-question
   battery over one document, with identical answers to calling one
   question at a time — the state dominates the request either way, so
   sending it once instead of N times is where the saving comes from.
2. **A generic hazard-battery engine** (`src/triage/battery.py`) — N
   independent Noul "does this fire?" questions plus one severity Score,
   resolved into a routing action by a named, code-owned policy table. This
   is TypeSafe's [LLM-guardrails cookbook](https://docs.typesafe.ai/cookbooks/llm_guardrails.md)
   pattern, generalized: `guardrail.py` (message safety) and
   `ops/deploy_gate.py` (deploy risk) are both ~15-line instantiations of
   the same `run_battery()` function with a different battery + policy —
   proof the pattern isn't guardrail-specific.
3. **Composite scoring, weighted in code** — `triage.py` and
   `ops/alerts.py` each score independent dimensions separately (urgency,
   frustration, severity, duplicate-ness) and combine them with weights
   that live in Python, not in the model, per
   [the composite-scoring pattern](https://docs.typesafe.ai/patterns/composite-scoring.md).
   Changing a weight is a code diff with a visible blast radius, not a
   prompt edit.
4. **Confidence-gated routing** — every pipeline checks `.confidence` (not
   just the answer) before acting automatically, per
   [the confidence-routing pattern](https://docs.typesafe.ai/patterns/confidence-routing.md):
   low routing confidence forces a human-review path regardless of what the
   answer itself says, because ("the answer tells you what; confidence
   tells you whether to act").

A fifth pattern shows up structurally rather than as a named function:
**hazard-gated short-circuiting**. `triage()` runs the safety guardrail
*first*, and if it blocks, returns immediately without spending a second
call on classification — the building guide's own criterion for when a
second request is warranted ("an earlier answer is needed to ... determine
the next options") applied literally.

## Why these three domains

The [skill's use-case guidance](https://docs.typesafe.ai/concepts/use-case-map.md)
frames System One as good for classification, routing, scoring, extraction,
and branching — support triage is the docs' own running example. Alert
triage and deploy-risk gating are the same shape of problem (typed judgment
→ code branches on it) in a domain the docs don't cover: DevOps/observability,
where the volume argument for a fast, cheap, calibrated model is arguably
stronger than for support tickets — an org pages on hundreds of alerts and
merges dozens of PRs a day, each a candidate for the exact "is this worth a
human's attention" judgment Jev is built for.

## Architecture

```
src/triage/
  battery.py       generic hazard-battery engine (Noul battery + Score + policy -> action)
  client.py        real TypeSafeClient, or the offline mock -- see below
  mock.py          offline heuristic double for local dev / tests / CI without a key
  guardrail.py      guard(): message-safety battery on top of battery.py
  triage.py         triage(): ticket classification + composite priority + confidence gate
  ops/
    alerts.py       alert_triage(): service/root-cause/severity/dedup + composite priority
    deploy_gate.py   risk_gate(): deploy-risk battery on top of battery.py
  cli.py            `triage-guard {ticket,alert,deploy-gate} run ...`
tests/               pytest suite against the mock client (tests composition logic, not model quality)
examples/             sample tickets / alerts / PR descriptions for each pipeline
```

### The offline mock, and why it exists

`src/triage/mock.py` is a small, explicitly-labeled keyword-overlap
heuristic that implements the same `client.system_one(state, questions)`
surface as the real SDK. It exists so this repo's tests, CI, and demo runs
work with **no API key and no network call** — and so the pipeline's
*composition logic* (routing thresholds, weighting, short-circuiting) can be
unit-tested independently of model quality, which is good practice
regardless of which model is behind the interface.

**It is not Jev, and it is not trying to be.** It has no semantic
understanding — it counts shared non-stopword tokens between the state text
and each question's instructions/criteria, with a small deterministic jitter
so identical inputs always answer the same way (needed for reproducible
tests). Run it side by side with a real key and the gap is visible and
instructive: the mock catches `pick a lock` phrased near hazard-adjacent
words, but misses `pick a lock on someone else's front door` entirely
because there's no shared vocabulary with the jailbreak/harmful-request
instructions — exactly the semantic gap a real model closes and a bag-of-words
heuristic structurally cannot. See `--mock` in every command below; omit it
once you have a key and the same code paths hit the real model.

```bash
export TYPESAFE_API_KEY=...   # https://console.typesafe.ai/settings/keys
pip install -e ".[dev]"
triage-guard ticket run "My card was charged twice, please help ASAP."
# same command, no key needed, for CI/local dev:
triage-guard ticket run "My card was charged twice, please help ASAP." --mock
```

## Setup

```bash
git clone https://github.com/shivam2003-dev/typesafe-triage-guard
cd typesafe-triage-guard
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env    # fill in TYPESAFE_API_KEY, or leave blank to use --mock
pytest -q                # runs entirely against the mock client, no key needed
```

## Usage

```bash
# Support-ticket triage
triage-guard ticket run "Hi, I've been trying to connect my Stripe account for 3 days and it keeps failing. I'm losing sales every hour. Please help ASAP." --mock
triage-guard ticket run --file examples/sample_tickets.json --mock

# Observability alert triage
triage-guard alert run "p99 latency on checkout-api jumped to 8s after the 14:02 deploy" --mock
triage-guard alert run --file examples/sample_alerts.json --mock

# Deploy / PR risk gate
triage-guard deploy-gate run "Adds a migration dropping the legacy_users column, no rollback plan noted." --mock
triage-guard deploy-gate run --file examples/sample_prs.json --mock --policy permissive
```

Every command accepts `--mock` (offline heuristic client), `--policy
strict|permissive` (guardrail / deploy-gate only), and `--json`
(machine-readable output for wiring into a real pipeline).

### Sample output (mock mode)

```
--- 'Total outage: the load balancer is returning 502s for all traffic acro'...
  route: auto_page   (priority 0.68 >= 0.66)
  service=network (conf 0.97)  root_cause=deploy  severity='Major -- a feature or a subset of users is broken.' (1.95)  is_duplicate=0.25  priority=0.68

--- 'Adds a database migration that drops the legacy_users column and backf'...
  decision: block_deploy   (triggered_by=no_rollback_plan)
  blast_radius='Large -- a whole product surface or most users.' (1.97)  signals={'touches_prod_credentials': 0.27, 'touches_migration': 0.47, 'no_rollback_plan': 0.89, 'touches_shared_infra': 0.04}
```

Note the mock's Score/Choice outputs get noisy on near-zero-overlap inputs
(ties get broken by a small deterministic jitter rather than genuine
judgment) — the *routing decisions* stay sensible because they're driven by
whichever signal has real overlap, but don't read the mock's raw severity
numbers as meaningful. That noise-vs-decision gap is itself a reasonably
honest illustration of why RLCD's calibration objective (see the write-up
below) matters: a model whose probabilities are actually calibrated doesn't
have this failure mode.

### Verified against the real model (CI, `jev-1.13.0`)

The repo's `live-smoke` CI job runs all three CLIs against real Jev (via a
`TYPESAFE_API_KEY` repo secret) on every push —
[latest run](https://github.com/shivam2003-dev/typesafe-triage-guard/actions/workflows/ci.yml).
Unedited output from one such run:

```json
// triage-guard ticket run "My card was charged twice, please help ASAP." --json
{
  "route": "auto",
  "guard": { "action": "pass", "severity": 0.06,
             "severity_label": "No harm -- ordinary, benign content." },
  "department": "billing", "department_confidence": 1.0,
  "frustration": 1.46, "urgency": 2.27, "is_urgent": 0.98,
  "priority": 0.5618, "reason": "within normal thresholds"
}

// triage-guard alert run "Total outage across every service, nothing is reachable." --json
{
  "route": "auto_page", "service": "network", "service_confidence": 0.7,
  "root_cause": "unknown", "severity": 3.0,
  "severity_label": "Critical -- widespread outage or data-loss risk.",
  "is_duplicate": 0.54, "priority": 0.865,
  "reason": "priority 0.86 >= 0.66"
}

// triage-guard deploy-gate run "Adds a migration dropping a column, no rollback plan mentioned." --json
{
  "action": "block",
  "signals": { "touches_prod_credentials": 0.03, "touches_migration": 0.96,
               "no_rollback_plan": 0.96, "touches_shared_infra": 0.16 },
  "severity": 1.74, "severity_label": "Large -- a whole product surface or most users.",
  "triggered_by": "no_rollback_plan", "decision": "block_deploy"
}
```

Three things worth reading closely here:

- **`department_confidence: 1.0` on an unambiguous billing complaint** — the
  routing confidence gate would let this through automatically, correctly,
  with no human review needed.
- **The alert call was given no `open_incidents` list**, so
  `is_duplicate: 0.54` — right at maximum uncertainty (0.5), not a
  confident wrong answer in either direction. That's the calibration
  property RLCD is built for, visible on a single real call: with no
  evidence either way, the model reported "I don't know" instead of
  guessing — which is exactly the behavior a threshold-based router needs
  to be trustworthy.
- **The deploy gate correctly fired on `no_rollback_plan` (0.96) and
  `touches_migration` (0.96)** while leaving `touches_prod_credentials` low
  (0.03) — a plausible migration-without-rollback correctly distinguished
  from a credentials change, from one sentence, in one batched call.

No accuracy claims beyond this small, unlabeled smoke test are made here —
see the [Honest limitations](#honest-limitations) section.

## What each pipeline decides, and why

### `ticket.triage()`

1. Run the message-safety `guard()` battery on the raw ticket text first.
   If it blocks (jailbreak / harmful request over threshold), return
   immediately — no classification call spent on a ticket that's getting
   blocked anyway.
2. Otherwise, one batched call answers `department` (Choice), `frustration`
   (Score), `urgency` (Score), `is_urgent` (Noul).
3. Composite priority = weighted blend of urgency, frustration, is_urgent,
   and the guardrail's own severity score (weights in `PRIORITY_WEIGHTS`,
   `triage.py`).
4. Route: `department.confidence < 0.6` → `review` (don't trust the routing
   enough to auto-assign); guardrail flagged `review`/`support` → `review`;
   `priority >= 0.66` → `escalate`; else `auto`.

### `ops.alert_triage()`

One batched call answers `service` (Choice), `root_cause` (Choice),
`severity` (Score), `is_duplicate` (Noul — compared against an
`open_incidents` list passed in as extra state). `is_duplicate >= 0.7` short-circuits
straight to `suppress_duplicate` before priority is even computed — a
duplicate of an open incident doesn't need a priority, it needs silence.
Otherwise: low service-attribution confidence → `review`; composite priority
(75% severity, 25% "not a duplicate") `>= 0.66` → `auto_page`; else
`ticket`.

### `ops.risk_gate()`

Reuses `battery.run_battery()` with a deploy-risk battery instead of a
safety one: `touches_prod_credentials` / `touches_migration` /
`touches_shared_infra` (→ `review`), `no_rollback_plan` (→ `block`), plus a
`blast_radius` Score that can force a block on its own past a severity
threshold even if no single hazard fires — a change with no named individual
hazard but a huge blast radius (e.g. "reconfigure the load balancer for
everyone") should still get stopped.

## Honest limitations

- **The mock is a bag-of-words heuristic, not a model.** Every number in
  this README's demo output that came from `--mock` reflects keyword
  overlap, not judgment. It is useful for testing composition logic and
  useless for evaluating Jev's actual accuracy or calibration — for that,
  read [TypeSafe's own workflow evals](https://evals.typesafe.ai/) or run
  this repo with a real key against your own labeled data.
- **The thresholds in every module (0.6 confidence floor, 0.35/0.70 hazard
  thresholds, 0.66 escalation cutoff) are starting points, not validated
  numbers.** The docs say this explicitly and it's worth repeating: *"start
  with conservative thresholds, test with your own data, and adjust as you
  observe results."* None of these have been tuned against real production
  data — they're defensible defaults, not measured optima.
- **`triage-guard alert run` in this repo has no real alerting backend
  behind it.** `open_incidents` is passed in by hand for the demo; a real
  deployment would pull it from PagerDuty/Alertmanager's own open-incidents
  API before calling `alert_triage()`.
- **No live evaluation was run against real Jev for this write-up.** The
  CI workflow includes an optional `live-smoke` job gated on a
  `TYPESAFE_API_KEY` repo secret that exercises all three CLIs against the
  real model if the secret is present, but no accuracy claims are made here
  beyond "the pipeline runs end-to-end" — see `evals.typesafe.ai` for
  TypeSafe's own accuracy/cost/latency numbers.

## Related

This repo grew out of a longer technical write-up on TypeSafe's launch —
what System One models are, how RLCD (the calibration-focused training
objective behind Jev) differs from RLHF/RLVR, and a critical read of the
workflow-evals numbers — at
[cvam.sight/posts/typesafe-jev-system-one-models](https://cvam.sight/posts/typesafe-jev-system-one-models).

## License

MIT — see [LICENSE](LICENSE).
