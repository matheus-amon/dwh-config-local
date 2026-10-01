"""Account master records.

Country is decided here and reused downstream by the telemetry generator, so an account's
events all report the same geography.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
from faker import Faker

from ..config import LabConfig
from ..domain.lifecycle import AccountLifecycle

INDUSTRIES: tuple[str, ...] = (
    "Software", "Financial Services", "Healthcare", "Retail", "Manufacturing",
    "Logistics", "Education", "Real Estate", "Media", "Energy", "Public Sector",
    "Professional Services", "Hospitality", "Telecommunications",
)

#: (country_code, region, relative weight)
COUNTRY_CATALOG: tuple[tuple[str, str, float], ...] = (
    ("US", "North America", 0.36),
    ("CA", "North America", 0.08),
    ("GB", "EMEA", 0.13),
    ("DE", "EMEA", 0.09),
    ("NL", "EMEA", 0.05),
    ("SE", "EMEA", 0.04),
    ("IE", "EMEA", 0.03),
    ("BR", "LATAM", 0.08),
    ("MX", "LATAM", 0.04),
    ("SG", "APAC", 0.04),
    ("AU", "APAC", 0.04),
    ("JP", "APAC", 0.02),
)

_NAME_SUFFIXES = (
    "Labs", "Systems", "Group", "Works", "Digital", "Analytics", "Technologies",
    "Partners", "Software", "Collective", "Industries", "Networks",
)


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "", text.lower())
    return cleaned or "account"


def _domain_for(company: str, rng: np.random.Generator) -> str:
    tld = str(rng.choice(("com", "io", "co", "ai", "dev"), p=(0.45, 0.25, 0.15, 0.08, 0.07)))
    return f"{_slug(company)}.{tld}"


def generate_accounts(
    lifecycles: list[AccountLifecycle], cfg: LabConfig, rng: np.random.Generator
) -> pd.DataFrame:
    fake = Faker("en_US")
    Faker.seed(cfg.seed)

    codes = [c for c, _, _ in COUNTRY_CATALOG]
    regions = [r for _, r, _ in COUNTRY_CATALOG]
    weights = np.array([w for _, _, w in COUNTRY_CATALOG], dtype=float)
    weights /= weights.sum()

    rows = []
    for lc in lifecycles:
        suffix = str(rng.choice(_NAME_SUFFIXES))
        company = f"{fake.last_name().replace(chr(39), '')} {suffix}"
        country_idx = int(rng.choice(len(codes), p=weights))
        rows.append(
            {
                "account_id": lc.account_id,
                "account_name": company,
                "domain": _domain_for(company, rng),
                "industry": str(rng.choice(INDUSTRIES)),
                "employee_band": lc.employee_band,
                "country_code": codes[country_idx],
                "region": regions[country_idx],
                "signed_up_at": lc.signed_up_at,
                "plan_code_at_signup": lc.initial_plan_code,
                "seats": lc.final_seats,
                "status": "churned" if lc.churned else "active",
                "churned_at": lc.churned_at,
            }
        )
    return pd.DataFrame(rows)
