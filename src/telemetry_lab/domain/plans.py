"""Product catalogue: plans, pricing and the features each tier unlocks."""

from __future__ import annotations

from dataclasses import dataclass

#: Monthly list price in USD for a plan at its included seat count.
EXTRA_SEAT_PRICE = {"starter": 8.0, "growth": 7.0, "scale": 6.0, "enterprise": 5.0}


@dataclass(frozen=True)
class Plan:
    plan_code: str
    plan_name: str
    monthly_price_usd: float
    included_seats: int
    billing_interval: str
    tier_rank: int
    #: Relative weight that a new account signs up on this tier.
    signup_weight: float
    #: Baseline weekly engagement per seat before any ramp or decay.
    engagement_base: float


PLAN_CATALOG: tuple[Plan, ...] = (
    Plan("starter", "Starter", 49.0, 5, "monthly", 1, 0.34, 0.55),
    Plan("growth", "Growth", 199.0, 20, "monthly", 2, 0.33, 0.70),
    Plan("scale", "Scale", 599.0, 75, "monthly", 3, 0.22, 0.85),
    Plan("enterprise", "Enterprise", 2400.0, 250, "annual", 4, 0.11, 0.95),
)

PLANS_BY_CODE: dict[str, Plan] = {p.plan_code: p for p in PLAN_CATALOG}
PLAN_CODES: tuple[str, ...] = tuple(p.plan_code for p in PLAN_CATALOG)

#: Product areas that generate telemetry. ``min_tier_rank`` gates who can reach them, which is
#: what makes adoption genuinely interesting to analyse: SSO simply does not exist on Starter.
FEATURE_MIN_TIER: dict[str, int] = {
    "core_dashboard": 1,
    "data_export": 2,
    "api_access": 2,
    "sso": 3,
    "audit_log": 3,
    "advanced_analytics": 4,
}

FEATURES: tuple[str, ...] = tuple(FEATURE_MIN_TIER)

#: Which named actions belong to which feature.
FEATURE_ACTIONS: dict[str, tuple[str, ...]] = {
    "core_dashboard": ("dashboard_viewed", "report_created", "report_scheduled", "alert_created"),
    "data_export": ("export_run",),
    "api_access": ("api_call",),
    "sso": ("member_invited", "sso_configured"),
    "audit_log": ("settings_changed", "audit_viewed"),
    "advanced_analytics": ("forecast_built", "cohort_analysed"),
}

#: Telemetry actions that are not tied to a paid feature.
CORE_ACTIONS: tuple[str, ...] = ("app_opened", "integration_connected")


def features_for_tier(tier_rank: int) -> tuple[str, ...]:
    """Features reachable by a plan of ``tier_rank``."""
    return tuple(f for f, min_tier in FEATURE_MIN_TIER.items() if tier_rank >= min_tier)


def plan(code: str) -> Plan:
    return PLANS_BY_CODE[code]


def mrr_usd(plan_code: str, seats: int, discount_pct: float = 0.0) -> float:
    """Monthly recurring revenue for ``seats`` on ``plan_code``, net of a percent discount.

    Seats beyond the plan's included allowance are billed at the plan's per-extra-seat rate,
    so an account that grows seats within its tier still moves MRR.
    """
    p = plan(plan_code)
    seats = max(1, int(seats))
    extra = max(0, seats - p.included_seats)
    gross = p.monthly_price_usd + extra * EXTRA_SEAT_PRICE[plan_code]
    return round(gross * (1.0 - discount_pct / 100.0), 2)


def tier_rank(plan_code: str) -> int:
    return plan(plan_code).tier_rank
