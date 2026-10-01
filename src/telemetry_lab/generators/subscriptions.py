"""Subscription terms, flattened across every account.

One row per uninterrupted period on a plan. This is the shape the warehouse needs to derive
new / expansion / contraction / churned MRR without guessing.
"""

from __future__ import annotations

import pandas as pd

from ..domain.lifecycle import AccountLifecycle
from ..domain.plans import plan


def generate_subscriptions(lifecycles: list[AccountLifecycle]) -> pd.DataFrame:
    rows = []
    subscription_id = 1
    for lc in lifecycles:
        for term in lc.terms:
            rows.append(
                {
                    "subscription_id": subscription_id,
                    "account_id": lc.account_id,
                    "plan_code": term.plan_code,
                    "billing_interval": plan(term.plan_code).billing_interval,
                    "seats": term.seats,
                    "discount_pct": term.discount_pct,
                    "mrr_usd": term.mrr_usd,
                    "started_at": term.started_at,
                    "ended_at": term.ended_at,
                    "ended_reason": term.ended_reason,
                }
            )
            subscription_id += 1
    return pd.DataFrame(rows)
