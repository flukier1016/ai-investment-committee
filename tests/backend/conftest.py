import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

from app.domain.pipeline import run_decision  # noqa: E402
from app.schemas.config import AllocationConfig  # noqa: E402


@pytest.fixture(scope="session")
def config() -> AllocationConfig:
    return AllocationConfig()


@pytest.fixture(scope="session")
def record(config):
    return run_decision("recovery_2026", "2026-07-09", config)


@pytest.fixture(scope="session")
def record_stagflation(config):
    return run_decision("stagflation_2022", "2022-10-14", config)
