"""Command line entry point for the telemetry lab."""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import numpy as np

from .config import DEFAULT_SEED, LabConfig
from .domain.lifecycle import dataset_summary, simulate_lifecycles
from .duck import StagingWarehouse
from .generators.accounts import generate_accounts
from .generators.events import generate_events
from .generators.plans import generate_plans
from .generators.subscriptions import generate_subscriptions
from .generators.users import generate_users

#: Tables that the event generator does not need to participate in.
CORE_TABLES: tuple[str, ...] = ("raw_plans", "raw_accounts", "raw_users", "raw_subscriptions")
ALL_TABLES: tuple[str, ...] = (*CORE_TABLES, "raw_product_events")


def _log(message: str) -> None:
    print(message, flush=True)


def _config_from_args(args: argparse.Namespace) -> LabConfig:
    return LabConfig(
        seed=args.seed,
        n_accounts=args.accounts,
        n_users=args.users,
        n_events=args.events,
        history_months=args.months,
        end_date=args.end_date or date.today(),
        output_dir=args.output_dir,
    )


def cmd_generate(args: argparse.Namespace) -> int:
    cfg = _config_from_args(args)
    _log(f"generating: {cfg.describe()}")
    started = time.perf_counter()

    rng = np.random.default_rng(cfg.seed)
    lifecycles = simulate_lifecycles(cfg, rng)
    lifecycles = [lc for lc in lifecycles if lc.weekly_seats.sum() > 0]

    with StagingWarehouse() as warehouse:
        warehouse.create_all()

        accounts = generate_accounts(lifecycles, cfg, rng)
        users = generate_users(
            lifecycles,
            dict(zip(accounts["account_id"], accounts["domain"], strict=True)),
            cfg,
            rng,
        )
        countries = dict(zip(accounts["account_id"], accounts["country_code"], strict=True))

        warehouse.append("raw_plans", generate_plans())
        warehouse.append("raw_accounts", accounts)
        warehouse.append("raw_users", users)
        warehouse.append("raw_subscriptions", generate_subscriptions(lifecycles))
        warehouse.append(
            "raw_product_events", generate_events(lifecycles, users, countries, cfg, rng)
        )

        counts = warehouse.counts(ALL_TABLES)
        written = warehouse.export_csv(cfg.output_dir, ALL_TABLES)

    for path in written.values():
        _log(f"  {path}  ({counts[path.stem]:,} rows)")

    summary = dataset_summary(lifecycles)
    _log(
        f"done in {time.perf_counter() - started:.1f}s — "
        f"{summary['accounts']:,} accounts, {summary['subscription_terms']:,} subscription terms, "
        f"{summary['churned_accounts']:,} churned, "
        f"{summary['accounts_with_plan_changes']:,} with plan changes, "
        f"active MRR ${summary['active_mrr_usd']:,.0f}"
    )
    return 0


def cmd_load(args: argparse.Namespace) -> int:
    from .load import load

    started = time.perf_counter()
    if args.recreate:
        _log("recreating raw tables (cascades to dependent dbt views; run dbt build after)")
    _log(f"loading {args.input_dir} into the raw schema")
    counts = load(args.input_dir, recreate=args.recreate)
    for table, rows in counts.items():
        _log(f"  raw.{table}  {rows:,} rows")
    _log(f"done in {time.perf_counter() - started:.1f}s")
    return 0


def _add_generate_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--accounts", type=int, default=2_000)
    parser.add_argument("--users", type=int, default=20_000)
    parser.add_argument("--events", type=int, default=1_000_000)
    parser.add_argument("--months", type=int, default=24)
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=None,
        help="Anchor for the history window. Defaults to today.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="telemetry-lab",
        description="Generate synthetic B2B SaaS telemetry for the saas-metrics-dwh warehouse.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate", help="Generate every raw table as CSV.")
    _add_generate_arguments(generate)
    generate.set_defaults(func=cmd_generate)

    load = sub.add_parser("load", help="Load the generated CSVs into the raw schema in Postgres.")
    load.add_argument("--input-dir", type=Path, default=Path("data/raw"))
    load.add_argument(
        "--recreate",
        action="store_true",
        help="Drop and recreate the raw tables instead of truncating. Needed only when a "
        "column changed; cascades to any dbt views reading from them.",
    )
    load.set_defaults(func=cmd_load)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
