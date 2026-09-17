"""Client selection: real Jev via typesafe-sdk, or the offline mock.

Real calls require TYPESAFE_API_KEY (https://console.typesafe.ai/settings/keys)
and the `typesafe-sdk` package (declared as a dependency in pyproject.toml).
Mock mode needs neither and is meant for development, tests, and demos where
no network access or API key is available -- see mock.py for exactly what it
does and does not simulate.
"""

from __future__ import annotations

import os
from typing import Any, Protocol


class SystemOneClient(Protocol):
    def system_one(self, state: Any, questions: Any) -> Any: ...
    def __enter__(self) -> "SystemOneClient": ...
    def __exit__(self, *exc: object) -> None: ...


def get_client(*, mock: bool | None = None) -> SystemOneClient:
    """Return a client implementing `.system_one(state, questions)`.

    mock=True            -> always use MockTypeSafeClient.
    mock=False            -> always use the real typesafe_sdk.TypeSafeClient
                              (raises if the SDK isn't installed or no API
                              key is configured).
    mock=None (default)   -> use the real client if TYPESAFE_API_KEY is set
                              and TRIAGE_GUARD_MOCK isn't truthy, otherwise
                              fall back to the mock and print a one-line
                              notice so nobody mistakes mock output for real
                              Jev output.
    """
    force_mock_env = os.environ.get("TRIAGE_GUARD_MOCK", "").strip().lower() in {"1", "true", "yes"}
    if mock is True or (mock is None and force_mock_env):
        from triage.mock import MockTypeSafeClient

        return MockTypeSafeClient()

    have_key = bool(os.environ.get("TYPESAFE_API_KEY"))

    if mock is False or have_key:
        try:
            from typesafe_sdk import TypeSafeClient
        except ImportError as exc:  # pragma: no cover - exercised only without the dep
            raise RuntimeError(
                "typesafe-sdk is not installed. Run `pip install typesafe-sdk` "
                "or pass mock=True / set TRIAGE_GUARD_MOCK=1 to use the offline mock."
            ) from exc
        if not have_key and mock is False:
            raise RuntimeError(
                "TYPESAFE_API_KEY is not set. Get a key at "
                "https://console.typesafe.ai/settings/keys and `export TYPESAFE_API_KEY=...`."
            )
        return TypeSafeClient()

    print(
        "[triage-guard] TYPESAFE_API_KEY not set -- using the offline mock client. "
        "Answers are heuristic, not Jev. See src/triage/mock.py.",
    )
    from triage.mock import MockTypeSafeClient

    return MockTypeSafeClient()
