"""The plan catalogue, as a raw frame."""

from __future__ import annotations

import pandas as pd

from ..domain.plans import PLAN_CATALOG


def generate_plans() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "plan_code": p.plan_code,
                "plan_name": p.plan_name,
                "monthly_price_usd": p.monthly_price_usd,
                "included_seats": p.included_seats,
                "billing_interval": p.billing_interval,
                "tier_rank": p.tier_rank,
            }
            for p in PLAN_CATALOG
        ]
    )
