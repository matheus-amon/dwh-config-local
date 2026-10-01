"""Users inside accounts.

Every account gets exactly one admin; the rest of the budget is spread across accounts in
proportion to how many seats they hold. ``last_seen_at`` is what the health mart uses as a
recency signal, so for a churned account it clusters near the churn date.
"""

from __future__ import annotations

import re
from datetime import timedelta

import numpy as np
import pandas as pd
from faker import Faker

from ..config import LabConfig
from ..domain.lifecycle import AccountLifecycle

MEMBER_ROLES: tuple[str, ...] = ("member", "analyst", "viewer")
ROLE_WEIGHTS: tuple[float, ...] = (0.58, 0.24, 0.18)


def _local_part(full_name: str, user_id: int) -> str:
    """Derive an e-mail local part from a display name."""
    ascii_name = full_name.encode("ascii", "ignore").decode()
    parts = [p for p in re.split(r"[^a-zA-Z]+", ascii_name) if p]
    if not parts:
        return f"user{user_id}"
    return ".".join(parts[:2]).lower()


ROLE_ADMIN = "admin"


def _millis(ts: pd.Timestamp):
    """Trim to millisecond precision so exported timestamps look like real logs."""
    return ts.round("ms").to_pydatetime()


def generate_users(
    lifecycles: list[AccountLifecycle],
    domains: dict[int, str],
    cfg: LabConfig,
    rng: np.random.Generator,
) -> pd.DataFrame:
    fake = Faker("en_US")
    Faker.seed(cfg.seed + 1)

    seats = np.array([max(1, int(lc.weekly_seats.max())) for lc in lifecycles], dtype=float)
    seats /= seats.sum()

    member_budget = max(0, cfg.n_users - len(lifecycles))
    member_alloc = rng.multinomial(member_budget, seats) if member_budget else np.zeros(len(seats), int)

    rows = []
    user_id = 1
    end_ts = pd.Timestamp(cfg.end_date)
    for lc, extra in zip(lifecycles, member_alloc, strict=True):
        window_start = pd.Timestamp(lc.signed_up_at)
        window_end = pd.Timestamp(lc.churned_at) if lc.churned_at else end_ts
        if window_end <= window_start:
            window_end = window_start + timedelta(days=7)

        for slot in range(1 + int(extra)):
            full_name = fake.name()
            role = ROLE_ADMIN if slot == 0 else str(rng.choice(MEMBER_ROLES, p=ROLE_WEIGHTS))
            # Skewed towards the later part of the window, so most users are still active.
            offset = float(rng.beta(1.6, 2.2))
            created = window_start + (window_end - window_start) * offset
            last_seen = created + (window_end - created) * float(rng.beta(2.0, 1.8))

            local = _local_part(full_name, user_id)
            rows.append(
                {
                    "user_id": user_id,
                    "account_id": lc.account_id,
                    "email": f"{local}{user_id}@{domains[lc.account_id]}",
                    "full_name": full_name,
                    "role": role,
                    "is_admin": role == ROLE_ADMIN,
                    "created_at": _millis(created),
                    "last_seen_at": _millis(last_seen),
                }
            )
            user_id += 1

    return pd.DataFrame(rows)
