"""Simulates the commercial lifecycle of every account across the history window.

The point of this module is that churn is not sprinkled on independently of behaviour. An
account that cancels has a visible decline in weekly engagement over the weeks before it
cancels, which is the signal ``mart_account_health`` later keys on. If the two were generated
independently the warehouse would be modelling noise.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from ..config import LabConfig
from .plans import PLAN_CODES, features_for_tier, mrr_usd, plan, tier_rank

#: Weeks of onboarding ramp before an account reaches steady-state engagement.
RAMP_WEEKS = 4
#: Nobody churns inside the first two months; contracts have a floor.
MIN_TENURE_WEEKS = 8
#: Share of accounts that enter a terminal usage decline at some point.
DECLINE_PROBABILITY = 0.32
#: Weekly multiplicative decay applied once an account is declining.
WEEKLY_DECAY = 0.90
#: Engagement level under which an account is considered to be failing.
CHURN_ENGAGEMENT_THRESHOLD = 0.18
#: Baseline weekly hazard, independent of the decline trajectory.
BASE_WEEKLY_CHURN_HAZARD = 0.0015
#: Weekly probability of a tier change, once past warm-up.
UPGRADE_PROBABILITY = 0.020
DOWNGRADE_PROBABILITY = 0.008
#: Log-normal-ish spread on weekly engagement, so weeks are not identical.
WEEKLY_NOISE_SIGMA = 0.12

ENDED_UPGRADED = "upgraded"
ENDED_DOWNGRADED = "downgraded"
ENDED_CHURNED = "churned"


@dataclass(frozen=True)
class EmployeeBand:
    """Company size bucket. Larger companies start on larger plans and hold more seats."""

    name: str
    share: float
    seats_range: tuple[int, int]
    plan_weights: dict[str, float]


EMPLOYEE_BANDS: tuple[EmployeeBand, ...] = (
    EmployeeBand(
        "1-10", 0.30, (2, 10),
        {"starter": 0.62, "growth": 0.30, "scale": 0.07, "enterprise": 0.01},
    ),
    EmployeeBand(
        "11-50", 0.28, (8, 50),
        {"starter": 0.26, "growth": 0.48, "scale": 0.21, "enterprise": 0.05},
    ),
    EmployeeBand(
        "51-200", 0.20, (40, 200),
        {"starter": 0.10, "growth": 0.34, "scale": 0.41, "enterprise": 0.15},
    ),
    EmployeeBand(
        "201-1000", 0.14, (150, 1000),
        {"starter": 0.03, "growth": 0.17, "scale": 0.48, "enterprise": 0.32},
    ),
    EmployeeBand(
        "1000+", 0.08, (800, 5000),
        {"starter": 0.01, "growth": 0.08, "scale": 0.36, "enterprise": 0.55},
    ),
)

@dataclass(frozen=True)
class SubscriptionTerm:
    """One uninterrupted period an account spends on a single plan."""

    plan_code: str
    started_at: datetime
    ended_at: datetime | None
    ended_reason: str | None
    seats: int
    discount_pct: float

    @property
    def mrr_usd(self) -> float:
        return mrr_usd(self.plan_code, self.seats, self.discount_pct)


@dataclass
class AccountLifecycle:
    """Everything known about one account: when it arrived, how it behaved, how it left."""

    account_id: int
    employee_band: str
    signed_up_at: datetime
    initial_plan_code: str
    terms: list[SubscriptionTerm]
    churned_at: datetime | None
    #: Weekly engagement in [0, inf), indexed by week offset from the window start. Zero
    #: before signup and from the churn week onwards.
    engagement: np.ndarray
    #: Weekly seat count, aligned with ``engagement``.
    weekly_seats: np.ndarray
    #: Weekly plan tier rank, aligned with ``engagement``. Gates which product features the
    #: account's users can reach, so the telemetry generator has to consult it.
    weekly_tier: np.ndarray

    @property
    def churned(self) -> bool:
        return self.churned_at is not None

    @property
    def final_seats(self) -> int:
        return self.terms[-1].seats if self.terms else 0

    @property
    def current_plan_code(self) -> str:
        return self.terms[-1].plan_code if self.terms else self.initial_plan_code

    def features_available(self) -> tuple[str, ...]:
        return features_for_tier(tier_rank(self.current_plan_code))


def simulate_lifecycles(
    cfg: LabConfig, rng: np.random.Generator | None = None
) -> list[AccountLifecycle]:
    """Simulate every account in the dataset."""
    rng = np.random.default_rng(cfg.seed) if rng is None else rng
    band_idx = rng.choice(
        len(EMPLOYEE_BANDS), size=cfg.n_accounts, p=[b.share for b in EMPLOYEE_BANDS]
    )
    return [
        _simulate_account(account_id, EMPLOYEE_BANDS[int(idx)], cfg, rng)
        for account_id, idx in enumerate(band_idx, start=1)
    ]


def _weighted_plan(weights: dict[str, float], rng: np.random.Generator) -> str:
    codes = [c for c in PLAN_CODES if weights.get(c)]
    probabilities = np.array([weights[c] for c in codes], dtype=float)
    probabilities /= probabilities.sum()
    return codes[int(rng.choice(len(codes), p=probabilities))]


def _step_tier(current: str, direction: int, rng: np.random.Generator) -> str | None:
    """Move one tier, occasionally skipping a rung on the way up.

    Returns ``None`` when the account is already at the end of the ladder, so the caller can
    skip the change rather than record one that moves nothing.
    """
    order = list(PLAN_CODES)
    i = order.index(current)
    if direction > 0:
        if i == len(order) - 1:
            return None
        jump = 2 if (rng.random() < 0.25 and i + 2 < len(order)) else 1
        return order[i + jump]
    if i == 0:
        return None
    return order[i - 1]


def _discount_for(plan_code: str, rng: np.random.Generator) -> float:
    """Only the top tiers get negotiated discounts, and only some of them."""
    if tier_rank(plan_code) < 3 or rng.random() >= 0.25:
        return 0.0
    return float(rng.choice([5.0, 10.0, 15.0, 20.0]))


def _clamp_seats(seats: int, band: EmployeeBand) -> int:
    low, high = band.seats_range
    return int(min(high, max(low, seats)))


def _timestamp(cfg: LabConfig, week: int, rng: np.random.Generator) -> datetime:
    base = datetime(cfg.start_date.year, cfg.start_date.month, cfg.start_date.day)
    return base + timedelta(days=7 * week, hours=int(rng.integers(0, 24)))


def _week_start(cfg: LabConfig, week: int) -> datetime:
    """Midnight on the first day of ``week``.

    Plan changes are snapped to this, deliberately. Engagement and feature entitlement are
    modelled per week, so a term boundary landing partway through a week would let the
    generator emit events for a tier the account did not actually hold yet, and anything
    attributing usage by term would then disagree with the entitlement. Snapping removes the
    seam entirely.
    """
    base = datetime(cfg.start_date.year, cfg.start_date.month, cfg.start_date.day)
    return base + timedelta(days=7 * week)


def _simulate_account(
    account_id: int, band: EmployeeBand, cfg: LabConfig, rng: np.random.Generator
) -> AccountLifecycle:
    n_weeks = cfg.history_weeks

    # Signups span the whole window, including the final weeks.
    #
    # Reserving MIN_TENURE_WEEKS at the end so that every account could theoretically reach the
    # churn threshold left the last ~10 weeks with no signups at all, which shows up downstream
    # as three months of zero new MRR in the movement mart and reads as a broken model rather
    # than as a truncated one. An account that signs up in the last week simply has no
    # opportunity to churn inside the observation window, which is the honest outcome.
    signup_week = int(rng.integers(0, n_weeks))
    signed_up_at = _timestamp(cfg, signup_week, rng)

    current_plan = _weighted_plan(band.plan_weights, rng)
    seats = int(rng.integers(band.seats_range[0], band.seats_range[1] + 1))

    # --- weekly engagement trajectory -------------------------------------------------
    engagement = np.zeros(n_weeks, dtype=float)
    noise = rng.normal(1.0, WEEKLY_NOISE_SIGMA, size=n_weeks)
    decline_start: int | None = None

    # A decline needs room to play out: enough weeks after the ramp to decay past the churn
    # threshold. An account that signs up in the last few weeks cannot have one, which is why
    # this is a range check rather than an unconditional draw. Without it, a signup week near
    # the end of the window produces lo > hi and numpy raises.
    decline_lo = signup_week + RAMP_WEEKS + 4
    decline_hi = n_weeks - 2

    if decline_lo < decline_hi and rng.random() < DECLINE_PROBABILITY:
        decline_start = int(rng.integers(decline_lo, decline_hi))

    base_engagement = plan(current_plan).engagement_base
    for w in range(signup_week, n_weeks):
        ramp = min(1.0, (w - signup_week + 1) / RAMP_WEEKS)
        value = base_engagement * ramp * float(noise[w])
        if decline_start is not None and w >= decline_start:
            value *= WEEKLY_DECAY ** (w - decline_start)
        engagement[w] = max(0.0, value)

    churn_week: int | None = None
    for w in range(signup_week + MIN_TENURE_WEEKS, n_weeks):
        if engagement[w] < CHURN_ENGAGEMENT_THRESHOLD:
            churn_week = w
            break
        if rng.random() < BASE_WEEKLY_CHURN_HAZARD:
            churn_week = w
            break

    churned_at = _timestamp(cfg, churn_week, rng) if churn_week is not None else None
    if churn_week is not None:
        engagement[churn_week:] = 0.0

    # --- subscription terms ----------------------------------------------------------
    end_week = churn_week if churn_week is not None else n_weeks - 1
    terms: list[SubscriptionTerm] = []
    weekly_seats = np.zeros(n_weeks, dtype=int)

    term_plan = current_plan
    term_seats = seats
    term_start = signup_week
    term_started_at = signed_up_at
    term_discount = _discount_for(term_plan, rng)

    term_spans: list[tuple[int, int]] = []
    for w in range(signup_week, end_week + 1):
        if w > term_start + RAMP_WEEKS and rng.random() < UPGRADE_PROBABILITY:
            nxt = _step_tier(term_plan, +1, rng)
            reason = ENDED_UPGRADED
        elif w > term_start + MIN_TENURE_WEEKS and rng.random() < DOWNGRADE_PROBABILITY:
            nxt = _step_tier(term_plan, -1, rng)
            reason = ENDED_DOWNGRADED
        else:
            continue

        # Already at the top or the bottom of the ladder: nothing actually changed.
        if nxt is None:
            continue

        # One boundary timestamp shared by both sides, so terms never overlap or gap, and
        # snapped to the start of the week so weekly entitlement stays consistent with terms.
        boundary = _week_start(cfg, w)
        terms.append(
            SubscriptionTerm(
                plan_code=term_plan,
                started_at=term_started_at,
                ended_at=boundary,
                ended_reason=reason,
                seats=term_seats,
                discount_pct=term_discount,
            )
        )
        term_spans.append((term_start, w - 1))

        growth = rng.uniform(1.05, 1.7) if reason == ENDED_UPGRADED else rng.uniform(0.7, 1.0)
        term_plan = nxt
        term_seats = _clamp_seats(int(term_seats * growth), band)
        term_discount = _discount_for(term_plan, rng)
        term_start = w
        term_started_at = boundary

    terms.append(
        SubscriptionTerm(
            plan_code=term_plan,
            started_at=term_started_at,
            ended_at=churned_at,
            ended_reason=ENDED_CHURNED if churned_at is not None else None,
            seats=term_seats,
            discount_pct=term_discount,
        )
    )
    term_spans.append((term_start, end_week))

    # Seats are constant within a term; weekly resolution is enough to scale event volume.
    weekly_tier = np.zeros(n_weeks, dtype=int)
    for term, (lo, hi) in zip(terms, term_spans, strict=True):
        weekly_seats[lo : hi + 1] = term.seats
        weekly_tier[lo : hi + 1] = tier_rank(term.plan_code)

    return AccountLifecycle(
        account_id=account_id,
        employee_band=band.name,
        signed_up_at=signed_up_at,
        initial_plan_code=terms[0].plan_code,
        terms=terms,
        churned_at=churned_at,
        engagement=engagement,
        weekly_seats=weekly_seats,
        weekly_tier=weekly_tier,
    )


def dataset_summary(lifecycles: list[AccountLifecycle]) -> dict[str, int]:
    """Counts used by the CLI and by tests to sanity-check a run."""
    churned = sum(1 for lc in lifecycles if lc.churned)
    multi_term = sum(1 for lc in lifecycles if len(lc.terms) > 1)
    total_mrr = sum(lc.terms[-1].mrr_usd for lc in lifecycles if not lc.churned)
    return {
        "accounts": len(lifecycles),
        "churned_accounts": churned,
        "accounts_with_plan_changes": multi_term,
        "subscription_terms": sum(len(lc.terms) for lc in lifecycles),
        "active_mrr_usd": round(total_mrr, 2),
    }
