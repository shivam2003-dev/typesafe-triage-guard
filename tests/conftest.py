import pytest

from triage.mock import MockTypeSafeClient


@pytest.fixture
def client() -> MockTypeSafeClient:
    return MockTypeSafeClient()
