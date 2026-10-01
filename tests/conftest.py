"""Shared fixtures. Generation is seeded, so these are reproducible and cheap."""

from __future__ import annotations

import numpy as np
import pytest

from src.telemetry_lab.config import LabConfig
from src.telemetry_lab.domain.lifecycle import simulate_lifecycles

#: A window long enough for churn trajectories to play out, small enough to stay fast.
TEST_CONFIG = LabConfig(
    seed=4242,
    n_accounts=200,
    n_users=2_000,
    n_events=20_000,
    history_months=24,
)


@pytest.fixture(scope="session")
def cfg() -> LabConfig:
    return TEST_CONFIG


@pytest.fixture(scope="session")
def lifecycles(cfg: LabConfig):
    return simulate_lifecycles(cfg, np.random.default_rng(cfg.seed))


@pytest.fixture(scope="session")
def rng(cfg: LabConfig):
    return np.random.default_rng(cfg.seed)
