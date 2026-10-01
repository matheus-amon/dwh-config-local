"""Product telemetry.

Turns the weekly engagement trajectory into individual product events. Volume is allocated
across (account, week) cells in proportion to ``engagement * seats``, so the event stream
inherits the seasonality and the decline-before-churn behaviour for free.

Every step is vectorised: a million events built cell by cell in Python would take minutes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import LabConfig
from ..domain.lifecycle import AccountLifecycle
from ..domain.plans import CORE_ACTIONS, FEATURES, FEATURE_ACTIONS, FEATURE_MIN_TIER

#: Weekday multipliers, Monday first. Weekends are quieter.
WEEKDAY_WEIGHTS = np.array([1.00, 1.08, 1.10, 1.09, 1.00, 0.55, 0.38])
#: Hour-of-day multipliers, business hours heavy.
HOUR_WEIGHTS = np.array(
    [0.4, 0.3, 0.2, 0.2, 0.3, 0.5, 1.0, 1.6, 2.4, 2.8, 2.9, 2.7,
     2.5, 2.6, 2.7, 2.6, 2.2, 1.6, 1.1, 0.8, 0.7, 0.6, 0.5, 0.4]
)
#: Per-month multipliers, applied by the calendar month of the week.
MONTH_UPLIFT = {11: 1.25, 0: 1.10, 6: 0.95}

PLATFORMS = ("web", "ios", "android", "api")
#: Relative weight of the 'api' platform among all events. Used only as documentation of the
#: intended mix; the emitted platform is decided by the feature, see below.
PLATFORM_WEIGHTS = (0.62, 0.18, 0.12, 0.08)

#: Relative propensity of each feature, before the plan gate is applied.
FEATURE_BASE_WEIGHTS = {
    "core_dashboard": 1.00,
    "data_export": 0.28,
    "api_access": 0.22,
    "sso": 0.14,
    "audit_log": 0.12,
    "advanced_analytics": 0.10,
}

#: Probability that a given event is one of the un-gated core actions.
CORE_ACTION_SHARE = 0.22
#: Mean events per session. The session slot is geometric with p = 1 / (mean + 1).
EVENTS_PER_SESSION = 6.0

MAX_TIER = max(FEATURE_MIN_TIER.values())
_FEATURE_WEIGHTS = np.array(
    [
        [FEATURE_BASE_WEIGHTS[f] if tier >= FEATURE_MIN_TIER[f] else 0.0 for tier in range(1, MAX_TIER + 1)]
        for f in FEATURES
    ]
)


def _normalise(weights: np.ndarray) -> np.ndarray:
    total = weights.sum()
    if total <= 0:
        raise ValueError("cannot normalise an all-zero weight vector")
    return weights / total


def _sample_from_rows(matrix: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Draw one option index per column of row-cumulative ``matrix``.

    ``matrix`` is (options, rows) of non-negative weights.
    """
    cumulative = np.cumsum(matrix, axis=0)
    thresholds = rng.random(matrix.shape[1]) * cumulative[-1]
    return (cumulative < thresholds).sum(axis=0)


def _action_blocks() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(labels, block offsets, block lengths) describing the actions available per feature."""
    lengths = np.array([len(FEATURE_ACTIONS[f]) for f in FEATURES], dtype=int)
    labels: list[str] = []
    for feature in FEATURES:
        labels.extend(FEATURE_ACTIONS[feature])
    offsets = np.concatenate([[0], np.cumsum(lengths)])[:-1]
    return np.array(labels, dtype=object), offsets, lengths


_ACTION_LABELS, _ACTION_OFFSETS, _ACTION_LENGTHS = _action_blocks()


def _weekly_month_boost(cfg: LabConfig, n_weeks: int) -> np.ndarray:
    """Average December/January/July multiplier across each week's seven days."""
    boosts = np.ones(n_weeks)
    for week in range(n_weeks):
        first = np.datetime64(cfg.start_date) + np.timedelta64(7 * week, "D")
        total = 0.0
        for offset in range(7):
            day = first + np.timedelta64(offset, "D")
            month = int(day.astype("datetime64[M]").astype(int)) % 12
            total += MONTH_UPLIFT.get(month, 1.0)
        boosts[week] = total / 7
    return boosts


def generate_events(
    lifecycles: list[AccountLifecycle],
    users: pd.DataFrame,
    account_countries: dict[int, str],
    cfg: LabConfig,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Build the product event table."""
    n_weeks = cfg.history_weeks

    engagement = np.stack([lc.engagement for lc in lifecycles])
    seats = np.stack([lc.weekly_seats for lc in lifecycles]).astype(float)
    tiers = np.stack([lc.weekly_tier for lc in lifecycles])

    month_boost = _weekly_month_boost(cfg, n_weeks)
    weights = engagement * seats * month_boost[None, :]
    weights[weights <= 0] = 0.0
    if weights.sum() <= 0:
        raise ValueError("no active account-weeks to allocate events to")

    # multinomial normalises pvals along its last axis, so the probabilities have to be
    # flattened; a 2-D array here would make it draw `n_events` once per account.
    cell_counts = rng.multinomial(cfg.n_events, _normalise(weights.ravel())).reshape(weights.shape)
    account_rows, week_cols = np.nonzero(cell_counts > 0)
    counts = cell_counts[account_rows, week_cols]

    total_events = int(counts.sum())
    account_index = np.repeat(account_rows, counts)
    week_index = np.repeat(week_cols, counts)

    # --- when ---------------------------------------------------------------------------
    week_starts = np.array(
        [np.datetime64(cfg.start_date) + np.timedelta64(7 * w, "D") for w in range(n_weeks)]
    )
    day_offsets = rng.choice(7, size=total_events, p=_normalise(WEEKDAY_WEIGHTS))
    event_days = week_starts[week_index] + day_offsets.astype("timedelta64[D]")

    hours = rng.choice(24, size=total_events, p=_normalise(HOUR_WEIGHTS))

    # An account does not exist before its signup timestamp, but the first week is a whole
    # week wide. Push any event that would land earlier than signup up to the signup hour.
    window_start = pd.Timestamp(cfg.start_date)
    hours_into_week = np.array(
        [(pd.Timestamp(lc.signed_up_at) - window_start).total_seconds() / 3600 for lc in lifecycles]
    )
    signup_week = np.array(
        [(lc.signed_up_at.date() - cfg.start_date).days // 7 for lc in lifecycles]
    )
    on_signup_day = (day_offsets == 0) & (week_index == signup_week[account_index])
    hours = np.where(
        on_signup_day,
        np.maximum(hours, (hours_into_week[account_index] % 168).astype(int)),
        hours,
    )
    event_ts = (
        event_days.astype("datetime64[s]")
        + hours.astype("timedelta64[h]")
        + rng.integers(0, 3600, size=total_events).astype("timedelta64[s]")
    )

    # --- who ----------------------------------------------------------------------------
    account_ids = np.array([lc.account_id for lc in lifecycles])[account_index]

    ordered = users.sort_values("account_id", kind="stable")
    user_accounts = ordered["account_id"].to_numpy()
    positions = np.searchsorted(user_accounts, account_ids, side="right") - 1
    if positions.min() < 0:
        raise ValueError("an account in the event stream has no users")
    actor_ids = ordered["user_id"].to_numpy()[positions]

    # --- what ---------------------------------------------------------------------------
    event_tiers = np.clip(tiers[account_index, week_index], 1, MAX_TIER)
    feature_positions = _sample_from_rows(_FEATURE_WEIGHTS[:, event_tiers - 1], rng)
    chosen_features = np.array(FEATURES, dtype=object)[feature_positions]

    # Actions are uniform within a feature's block, so the index is a uniform draw over
    # that feature's action count.
    block_lengths = _ACTION_LENGTHS[feature_positions]
    local_actions = np.minimum(
        (rng.random(total_events) * block_lengths).astype(int), block_lengths - 1
    )
    feature_actions = _ACTION_LABELS[_ACTION_OFFSETS[feature_positions] + local_actions]

    is_core = rng.random(total_events) < CORE_ACTION_SHARE
    core_names = np.array(CORE_ACTIONS, dtype=object)[
        rng.integers(0, len(CORE_ACTIONS), size=total_events)
    ]
    event_names = np.where(is_core, core_names, feature_actions)
    features = np.where(is_core, "core", chosen_features)

    # Everything outside the API integration happens in a client. API activity only ever
    # happens over the API, so the platform is derived from the feature rather than sampled.
    browser_platforms = np.array(("web", "ios", "android"), dtype=object)
    platforms = np.where(
        features == "api_access",
        "api",
        browser_platforms[
            rng.choice(len(browser_platforms), size=total_events, p=_normalise(np.array([0.66, 0.20, 0.14])))
        ],
    )

    # --- sessions -----------------------------------------------------------------------
    slot = np.minimum(rng.geometric(1.0 / (EVENTS_PER_SESSION + 1), size=total_events) - 1, 40)
    day_strings = event_days.astype("datetime64[D]").astype(str)
    session_ids = np.char.add(
        np.char.add(np.char.add(account_ids.astype(str), "-"), day_strings),
        np.char.add("-", slot.astype(str)),
    )

    frame = pd.DataFrame(
        {
            "event_id": np.arange(1, total_events + 1, dtype="int64"),
            "account_id": account_ids.astype("int32"),
            "user_id": actor_ids.astype("int32"),
            "event_name": event_names,
            "feature": features,
            "platform": platforms,
            "session_id": session_ids,
            "country_code": np.array([account_countries[a] for a in account_ids]),
            "event_ts": event_ts,
            "event_date": event_days,
        }
    )
    frame = frame.sort_values("event_ts", kind="stable", ignore_index=True)
    # Re-number after sorting so event_id increases with time, which is what makes the
    # warehouse's incremental merge on event_id behave.
    frame["event_id"] = np.arange(1, total_events + 1, dtype="int64")
    return frame
