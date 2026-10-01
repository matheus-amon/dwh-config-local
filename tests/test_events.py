"""Tests for the telemetry generator.

The gating test matters most: if ``sso`` showed up on a Starter account, every downstream
adoption metric would be measuring nothing but plan mix.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.telemetry_lab.config import LabConfig
from src.telemetry_lab.domain.lifecycle import simulate_lifecycles
from src.telemetry_lab.domain.plans import FEATURE_MIN_TIER
from src.telemetry_lab.generators.accounts import generate_accounts
from src.telemetry_lab.generators.events import generate_events
from src.telemetry_lab.generators.users import generate_users
from src.telemetry_lab.schema import RAW_COLUMNS


@pytest.fixture(scope="module")
def telemetry(cfg: LabConfig, lifecycles, rng):
    accounts = generate_accounts(lifecycles, cfg, rng)
    domains = dict(zip(accounts["account_id"], accounts["domain"], strict=True))
    users = generate_users(lifecycles, domains, cfg, rng)
    countries = dict(zip(accounts["account_id"], accounts["country_code"], strict=True))
    events = generate_events(lifecycles, users, countries, cfg, rng)
    return events, accounts, users, lifecycles


def test_event_count_matches_the_request(cfg: LabConfig, telemetry):
    events, *_ = telemetry
    assert len(events) == cfg.n_events


def test_event_ids_are_unique_and_increase_with_time(telemetry):
    events, *_ = telemetry
    assert events["event_id"].is_unique
    assert events["event_id"].tolist() == list(range(1, len(events) + 1))
    assert events["event_ts"].is_monotonic_increasing


def test_event_columns_match_the_declared_schema(telemetry):
    events, *_ = telemetry
    assert list(events.columns) == list(RAW_COLUMNS["raw_product_events"])


def test_event_date_agrees_with_the_timestamp(telemetry):
    events, *_ = telemetry
    derived = events["event_ts"].dt.tz_localize(None).dt.normalize()
    assert (derived == events["event_date"]).all()


def test_events_reference_known_accounts_and_users(telemetry):
    events, accounts, users, _ = telemetry
    assert set(events["account_id"]) <= set(accounts["account_id"])
    known_users = set(users["user_id"])
    assert set(events["user_id"]) <= known_users


def test_events_never_outlive_the_account(telemetry):
    events, accounts, *_ = telemetry
    churned_at = dict(zip(accounts["account_id"], accounts["churned_at"], strict=True))
    signed_up_at = dict(zip(accounts["account_id"], accounts["signed_up_at"], strict=True))

    for account_id, ts in zip(events["account_id"], events["event_ts"], strict=True):
        assert ts >= signed_up_at[account_id]
        ended = churned_at[account_id]
        if isinstance(ended, str) and ended:
            assert ts <= pd.Timestamp(ended)


def _weekly_tier_per_event(cfg: LabConfig, events, lifecycles) -> np.ndarray:
    """The plan tier in force for the account during the week each event happened.

    This is deliberately not the account's final plan: an account that upgraded mid-window
    was legitimately entitled to features it can no longer reach at the end.
    """
    tiers_by_account = {lc.account_id: lc.weekly_tier for lc in lifecycles}
    weeks = (events["event_date"] - pd.Timestamp(cfg.start_date)).dt.days // 7
    return np.array(
        [
            int(tiers_by_account[account_id][week])
            for account_id, week in zip(events["account_id"], weeks, strict=True)
        ]
    )


def test_paid_features_never_appear_below_their_tier(cfg: LabConfig, telemetry):
    events, _, _, lifecycles = telemetry
    gated = {f: t for f, t in FEATURE_MIN_TIER.items() if f != "core_dashboard"}
    observed = events[events["feature"].isin(gated)]
    assert len(observed) > 0

    tiers = _weekly_tier_per_event(cfg, observed, lifecycles)
    required = np.array([gated[f] for f in observed["feature"]])
    assert (tiers >= required).all(), "a gated feature fired below the plan that unlocks it"


def test_every_gated_feature_is_actually_exercised(cfg: LabConfig, telemetry):
    """Otherwise the adoption mart would be reporting on an empty dimension."""
    events, _, _, lifecycles = telemetry
    for feature, min_tier in FEATURE_MIN_TIER.items():
        if feature == "core_dashboard":
            continue
        assert (events["feature"] == feature).any(), f"{feature} never generated"


def test_api_platform_only_for_the_api_feature(telemetry):
    events, *_ = telemetry
    api_platform = events[events["platform"] == "api"]
    assert len(api_platform) > 0
    assert set(api_platform["feature"]) <= {"api_access"}


def test_core_actions_are_unavailable_on_every_plan(telemetry):
    events, *_ = telemetry
    core = events[events["feature"] == "core"]
    assert len(core) > 0
    assert set(core["event_name"]) <= {"app_opened", "integration_connected"}


def test_weekends_are_quieter_than_weekdays(telemetry):
    events, *_ = telemetry
    by_day = events["event_date"].dt.dayofweek.value_counts(normalize=True)
    weekday_mean = by_day.loc[[0, 1, 2, 3, 4]].mean()
    weekend_mean = by_day.loc[[5, 6]].mean()
    assert weekend_mean < weekday_mean


def test_sessionisation_groups_events_within_an_account_day(telemetry):
    """Session ids must be reused inside an account-day, not unique per event."""
    events, *_ = telemetry
    per_day = events.groupby(["account_id", "event_date"])["session_id"]
    dense_days = per_day.size()
    dense_days = dense_days[dense_days >= 4]
    assert len(dense_days) > 0, "no account-day dense enough to test sessionisation"

    distinct = per_day.nunique().loc[dense_days.index]
    # On a dense day, reusing sessions must collapse at least some of the events.
    assert (distinct < dense_days).mean() >= 0.5


def test_session_slot_distribution_is_heavy_tailed(telemetry):
    """Session slots follow a geometric distribution, concentrated in the first sessions.

    numpy's geometric puts its mass at k=1, so the first session takes 1/(mean+1) of all
    events and the tail decays. Uniform slots over the same 41 slots would put 2.4% in the
    first, so anything above 7% shows the intended decay.
    """
    events, *_ = telemetry
    slots = events["session_id"].str.rsplit("-", n=1).str[-1].astype(int)
    counts = slots.value_counts().sort_index()
    uniform_share = 1 / (counts.index.max() + 1)

    assert counts.iloc[0] / counts.sum() > 2.5 * uniform_share
    # Decaying away over the first few sessions. The tail is truncated, so only the head
    # is guaranteed to be monotone.
    head = counts.iloc[:8].to_numpy()
    assert (np.diff(head) <= 0).all()
    assert 3.0 < slots.mean() < 7.0


def test_accounts_in_decline_generate_less_than_their_baseline(telemetry):
    """The generator must preserve the behaviour the health mart depends on."""
    events, accounts, _, lifecycles = telemetry
    churned = {lc.account_id: lc.churned_at for lc in lifecycles if lc.churned}
    assert churned, "no churned accounts in the fixture"

    last_week_counts: dict[int, int] = {}
    early_week_counts: dict[int, int] = {}
    for account_id, churn_ts in churned.items():
        subset = events[events["account_id"] == account_id]
        if subset.empty:
            continue
        last_week_counts[account_id] = int(
            (subset["event_ts"] >= pd.Timestamp(churn_ts) - pd.Timedelta(days=7)).sum()
        )
        early_week_counts[account_id] = int(
            (subset["event_ts"] < pd.Timestamp(churn_ts) - pd.Timedelta(weeks=10)).sum()
        )

    paired = [
        (last_week_counts[a], early_week_counts[a])
        for a in last_week_counts
        if a in early_week_counts
    ]
    assert paired
    declining = sum(1 for last, early in paired if last < early)
    assert declining / len(paired) >= 0.7


def test_generation_is_reproducible(cfg: LabConfig):
    def build():
        r = np.random.default_rng(cfg.seed)
        lcs = simulate_lifecycles(cfg, r)
        accounts = generate_accounts(lcs, cfg, r)
        domains = dict(zip(accounts["account_id"], accounts["domain"], strict=True))
        users = generate_users(lcs, domains, cfg, r)
        countries = dict(zip(accounts["account_id"], accounts["country_code"], strict=True))
        return generate_events(lcs, users, countries, cfg, r)

    first, second = build(), build()
    pd.testing.assert_frame_equal(first, second)
