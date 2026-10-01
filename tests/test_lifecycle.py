"""Behavioural tests for the lifecycle simulator.

The important one is ``test_churn_is_preceded_by_a_usage_decline``: if churn were generated
independently of behaviour, the health mart downstream would be fitting noise.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from src.telemetry_lab.config import LabConfig
from src.telemetry_lab.domain.lifecycle import (
    ENDED_CHURNED,
    ENDED_DOWNGRADED,
    ENDED_UPGRADED,
    MIN_TENURE_WEEKS,
    simulate_lifecycles,
)
from src.telemetry_lab.domain.plans import mrr_usd, tier_rank

DECLINE_WINDOW = 8
BASELINE_WINDOW = 8


def _week_of(cfg: LabConfig, ts) -> int:
    return (ts.date() - cfg.start_date).days // 7


def test_every_account_has_at_least_one_term(lifecycles):
    assert all(len(lc.terms) >= 1 for lc in lifecycles)
    assert len({lc.account_id for lc in lifecycles}) == len(lifecycles)


def test_engagement_is_zero_before_signup_and_after_churn(cfg: LabConfig, lifecycles):
    for lc in lifecycles:
        signup_week = _week_of(cfg, lc.signed_up_at)
        assert lc.engagement[:signup_week].sum() == 0.0
        if lc.churned_at is not None:
            churn_week = _week_of(cfg, lc.churned_at)
            assert lc.engagement[churn_week:].sum() == 0.0


def test_nobody_churns_inside_the_minimum_tenure(cfg: LabConfig, lifecycles):
    for lc in lifecycles:
        if lc.churned_at is None:
            continue
        elapsed = (lc.churned_at.date() - lc.signed_up_at.date()).days // 7
        assert elapsed >= MIN_TENURE_WEEKS


def test_terms_chain_without_gaps(lifecycles):
    for lc in lifecycles:
        for current, following in zip(lc.terms, lc.terms[1:], strict=False):
            gap = following.started_at - current.ended_at
            assert timedelta(0) <= gap <= timedelta(days=7)
        assert lc.terms[-1].ended_at == lc.churned_at


def test_plan_changes_move_in_the_expected_direction(lifecycles):
    for lc in lifecycles:
        for current, following in zip(lc.terms, lc.terms[1:], strict=False):
            delta = tier_rank(following.plan_code) - tier_rank(current.plan_code)
            reason = current.ended_reason
            if reason == ENDED_UPGRADED:
                assert delta > 0
            elif reason == ENDED_DOWNGRADED:
                assert delta < 0
            else:
                # The only other way a term can end is churn, which cannot be followed
                # by another term — that case is covered by
                # test_only_the_final_term_of_a_churned_account_ends_in_churn.
                assert False, f"term ended for {reason!r} but a later term exists"


def test_only_the_final_term_of_a_churned_account_ends_in_churn(lifecycles):
    for lc in lifecycles:
        for term in lc.terms[:-1]:
            assert term.ended_reason in (ENDED_UPGRADED, ENDED_DOWNGRADED)
        if lc.churned:
            assert lc.terms[-1].ended_reason == ENDED_CHURNED
        else:
            assert lc.terms[-1].ended_reason is None


def test_churn_is_preceded_by_a_usage_decline(cfg: LabConfig, lifecycles):
    """The whole point of the module: churn is visible in usage before it happens."""
    declined = 0
    churned = 0
    for lc in lifecycles:
        if not lc.churned:
            continue
        churned += 1
        signup_week = _week_of(cfg, lc.signed_up_at)
        churn_week = _week_of(cfg, lc.churned_at)
        if churn_week - signup_week < DECLINE_WINDOW + BASELINE_WINDOW:
            continue
        before = lc.engagement[churn_week - DECLINE_WINDOW : churn_week]
        baseline = lc.engagement[
            signup_week + MIN_TENURE_WEEKS : signup_week + MIN_TENURE_WEEKS + BASELINE_WINDOW
        ]
        if before.mean() < baseline.mean():
            declined += 1

    assert churned > 0, "no churned accounts in the fixture; the test would be vacuous"
    # Not every churn needs a visible decline — some are the baseline hazard. Most should.
    assert declined / churned >= 0.7


def test_active_accounts_keep_engagement_through_the_window(cfg: LabConfig, lifecycles):
    active = [lc for lc in lifecycles if not lc.churned]
    assert active
    for lc in active[:20]:
        signup_week = _week_of(cfg, lc.signed_up_at)
        assert lc.engagement[-1] > 0.0
        assert lc.weekly_seats[-1] == lc.terms[-1].seats
        assert lc.weekly_seats[:signup_week].sum() == 0


def test_generation_is_reproducible(cfg: LabConfig):
    first = simulate_lifecycles(cfg, np.random.default_rng(cfg.seed))
    second = simulate_lifecycles(cfg, np.random.default_rng(cfg.seed))
    assert len(first) == len(second)
    for a, b in zip(first, second, strict=True):
        assert a.signed_up_at == b.signed_up_at
        assert np.array_equal(a.engagement, b.engagement)
        assert [(t.plan_code, t.started_at, t.mrr_usd) for t in a.terms] == [
            (t.plan_code, t.started_at, t.mrr_usd) for t in b.terms
        ]


def test_mrr_grows_with_seats_beyond_the_included_allowance():
    assert mrr_usd("starter", 5) == 49.0
    assert mrr_usd("starter", 15) == 49.0 + 10 * 8.0
    assert mrr_usd("enterprise", 250, 10.0) == 2400.0 * 0.9


def test_plan_changes_land_on_a_week_start(cfg: LabConfig, lifecycles):
    """Term boundaries must align with the weekly entitlement model.

    Engagement, seats and feature gating are all modelled at week resolution. A boundary partway
    through a week would let the generator emit events for a tier the account had not reached
    yet, and the warehouse's per-event term attribution would then contradict the entitlement.
    """
    window_start = datetime(cfg.start_date.year, cfg.start_date.month, cfg.start_date.day)
    for lc in lifecycles:
        for current, following in zip(lc.terms, lc.terms[1:], strict=False):
            offset_days = (following.started_at - window_start).days
            assert offset_days % 7 == 0, (
                f"account {lc.account_id} changed plan at {following.started_at}, "
                f"which is not a week start"
            )
