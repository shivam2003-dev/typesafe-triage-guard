"""Deterministic, offline stand-in for the real TypeSafe client.

This is NOT Jev. It is a small keyword-overlap heuristic that answers Noul /
Choice / Score questions well enough to exercise the pipeline's *composition
logic* (routing, thresholds, weighting) without a network call or an API key.

Use it for local development and for unit tests that assert on triage.py's
and guardrail.py's own code, not on model quality. Swap in the real
`typesafe_sdk.TypeSafeClient` (see client.py) for anything that needs to
measure actual model accuracy or calibration.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

_WORD_RE = re.compile(r"[a-z0-9']+")

# Common words that show up in nearly every instructions/criteria template
# ("This message...", "...with strong language...") and would otherwise
# cause spurious overlap against almost any state text.
_STOPWORDS = {
    "this", "that", "with", "from", "have", "does", "your", "about", "into",
    "when", "then", "than", "they", "them", "were", "been", "also", "such",
    "only", "more", "most", "some", "none", "each", "both", "over", "under",
    "will", "shall", "would", "could", "should", "asks", "seeks", "tries",
    "other", "rather", "message", "text", "content", "here", "there", "what",
    "which", "being", "these", "those", "where", "while", "isn't", "doesn't",
}


def _words(text: Any) -> set[str]:
    if text is None:
        return set()
    if not isinstance(text, str):
        text = str(text)
    return {
        w for w in _WORD_RE.findall(text.lower())
        if len(w) > 3 and w not in _STOPWORDS
    }


def _stable_jitter(*parts: str) -> float:
    """A small deterministic +/- offset so identical inputs always answer the
    same way (needed for reproducible tests) while different questions don't
    all collapse to exactly 0.5."""
    h = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return (int(h[:8], 16) / 0xFFFFFFFF - 0.5) * 0.08


@dataclass
class _NoulAnswer:
    noul: float


@dataclass
class _ChoiceAnswer:
    choice: str
    confidence: float
    probabilities: dict[str, float]


@dataclass
class _ScoreAnswer:
    score: float
    confidence: float
    legend: dict[int, str]
    probabilities: dict[int, float]


@dataclass
class _Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass
class MockResponse:
    model: str
    answers: dict[str, Any]
    usage: _Usage = field(default_factory=_Usage)

    @property
    def nouls(self) -> dict[str, _NoulAnswer]:
        return {k: v for k, v in self.answers.items() if isinstance(v, _NoulAnswer)}

    @property
    def choices(self) -> dict[str, _ChoiceAnswer]:
        return {k: v for k, v in self.answers.items() if isinstance(v, _ChoiceAnswer)}

    @property
    def scores(self) -> dict[str, _ScoreAnswer]:
        return {k: v for k, v in self.answers.items() if isinstance(v, _ScoreAnswer)}


class MockTypeSafeClient:
    """Offline heuristic double for typesafe_sdk.TypeSafeClient / AsyncTypeSafeClient.

    Implements the same `system_one(state, questions) -> response` surface
    (plus a sync-compatible `__enter__`/`__exit__` and async variants) so
    triage.py and guardrail.py never need to know which one they're holding.
    """

    def __enter__(self) -> "MockTypeSafeClient":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    async def __aenter__(self) -> "MockTypeSafeClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def system_one(self, state: Any, questions: Mapping[str, Any]) -> MockResponse:
        state_words = _words(state)
        answers: dict[str, Any] = {}

        for name, q in questions.items():
            qtype = type(q).__name__

            if qtype == "Noul":
                instr_words = _words(getattr(q, "instructions", None))
                overlap = len(state_words & instr_words)
                base = min(0.08 + 0.20 * overlap, 0.92)
                p = max(0.02, min(0.98, base + _stable_jitter(name, str(state)[:64])))
                answers[name] = _NoulAnswer(noul=round(p, 4))

            elif qtype == "Choice":
                criteria: Mapping[str, Any] = getattr(q, "criteria", {}) or {}
                scores: dict[str, float] = {}
                for label, desc in criteria.items():
                    label_words = _words(label) | _words(desc)
                    scores[label] = len(state_words & label_words) + 0.05
                total = sum(scores.values()) or 1.0
                probs = {k: v / total for k, v in scores.items()}
                best = max(probs, key=probs.get)
                answers[name] = _ChoiceAnswer(
                    choice=best,
                    confidence=round(min(0.97, 0.35 + probs[best]), 4),
                    probabilities={k: round(v, 4) for k, v in probs.items()},
                )

            elif qtype == "Score":
                criteria = list(getattr(q, "criteria", []) or [])
                n = max(1, len(criteria))
                scores = {}
                for level, desc in enumerate(criteria):
                    level_words = _words(desc)
                    scores[level] = len(state_words & level_words) + 0.05
                total = sum(scores.values()) or 1.0
                probs = {k: v / total for k, v in scores.items()}
                expected = sum(level * p for level, p in probs.items())
                best = max(probs, key=probs.get)
                answers[name] = _ScoreAnswer(
                    score=round(expected, 4),
                    confidence=round(min(0.97, 0.35 + probs[best]), 4),
                    legend={i: str(d) for i, d in enumerate(criteria)},
                    probabilities={k: round(v, 4) for k, v in probs.items()},
                )
            else:
                raise TypeError(f"MockTypeSafeClient: unsupported question type {qtype!r}")

        return MockResponse(model="mock-heuristic-v0", answers=answers, usage=_Usage())

    async def system_one_async(self, state: Any, questions: Mapping[str, Any]) -> MockResponse:
        return self.system_one(state, questions)
