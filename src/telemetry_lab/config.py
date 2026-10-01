"""Generation settings for the telemetry lab.

Everything that shapes the size and the shape of the generated dataset lives here, so the
CLI, the generators and the tests all agree on one source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

#: Fixed so two runs with the same config produce byte-identical CSVs.
DEFAULT_SEED = 20240101


def days_in_month(year: int, month: int) -> int:
    """Number of days in ``month`` of ``year``."""
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def months_back(anchor: date, months: int) -> date:
    """Date ``months`` before ``anchor``, clamping the day to the target month length."""
    total = anchor.year * 12 + (anchor.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(anchor.day, days_in_month(year, month)))


@dataclass(frozen=True)
class LabConfig:
    """Volume and window settings for a generation run."""

    seed: int = DEFAULT_SEED
    n_accounts: int = 2_000
    n_users: int = 20_000
    n_events: int = 1_000_000
    history_months: int = 24
    end_date: date = field(default_factory=date.today)
    output_dir: Path = Path("data/raw")
    #: Rows of the event table committed to git. The full set is generated on demand.
    sample_event_rows: int = 50_000

    @property
    def start_date(self) -> date:
        return months_back(self.end_date, self.history_months)

    @property
    def history_days(self) -> int:
        return (self.end_date - self.start_date).days

    @property
    def history_weeks(self) -> int:
        return self.history_days // 7

    def ddl_dir(self) -> Path:
        return self.output_dir

    def describe(self) -> str:
        return (
            f"accounts={self.n_accounts:,} users={self.n_users:,} "
            f"events={self.n_events:,} window={self.start_date}..{self.end_date} "
            f"({self.history_months} months, seed={self.seed})"
        )


#: Physical table names. These are what the dbt project declares as sources.
RAW_TABLES: tuple[str, ...] = (
    "raw_plans",
    "raw_accounts",
    "raw_users",
    "raw_subscriptions",
    "raw_product_events",
)
