"""Shape and referential-integrity tests for the generated raw frames."""

from __future__ import annotations

import pandas as pd
import pytest

from src.telemetry_lab.config import LabConfig
from src.telemetry_lab.duck import StagingWarehouse, chunked
from src.telemetry_lab.generators.accounts import generate_accounts
from src.telemetry_lab.generators.plans import generate_plans
from src.telemetry_lab.generators.subscriptions import generate_subscriptions
from src.telemetry_lab.generators.users import generate_users
from src.telemetry_lab.schema import RAW_COLUMNS, RAW_DDL

CORE_TABLES = ("raw_plans", "raw_accounts", "raw_users", "raw_subscriptions")


@pytest.fixture(scope="module")
def frames(cfg: LabConfig, lifecycles, rng):
    accounts = generate_accounts(lifecycles, cfg, rng)
    domains = dict(zip(accounts["account_id"], accounts["domain"], strict=True))
    return {
        "raw_plans": generate_plans(),
        "raw_accounts": accounts,
        "raw_subscriptions": generate_subscriptions(lifecycles),
        "raw_users": generate_users(lifecycles, domains, cfg, rng),
    }


@pytest.mark.parametrize("table", CORE_TABLES)
def test_frame_has_the_declared_columns(frames, table: str):
    assert list(frames[table].columns) == list(RAW_COLUMNS[table])


@pytest.mark.parametrize("table", CORE_TABLES)
def test_frame_has_no_duplicate_primary_keys(frames, table: str):
    key = RAW_COLUMNS[table][0]
    assert frames[table][key].is_unique


def test_plans_cover_every_catalogue_entry():
    plans = generate_plans()
    assert len(plans) == 4
    assert plans["tier_rank"].tolist() == sorted(plans["tier_rank"])
    assert (plans["monthly_price_usd"] > 0).all()


def test_subscriptions_reference_known_accounts(frames, lifecycles):
    known = {lc.account_id for lc in lifecycles}
    assert set(frames["raw_subscriptions"]["account_id"]) <= known


def test_users_reference_known_accounts(frames, lifecycles):
    known = {lc.account_id for lc in lifecycles}
    assert set(frames["raw_users"]["account_id"]) <= known


def test_every_account_has_exactly_one_admin(frames, lifecycles):
    users = frames["raw_users"]
    admins = users[users["is_admin"]].groupby("account_id").size()
    assert set(admins.index) == {lc.account_id for lc in lifecycles}
    assert (admins == 1).all()


def test_user_emails_are_globally_unique_and_on_account_domains(frames):
    users = frames["raw_users"]
    assert users["email"].is_unique
    domains = dict(zip(frames["raw_accounts"]["account_id"], frames["raw_accounts"]["domain"], strict=True))
    for account_id, email in zip(users["account_id"], users["email"], strict=True):
        assert email.endswith("@" + domains[account_id])


def test_users_are_created_within_their_account_lifetime(cfg: LabConfig, frames, lifecycles):
    accounts = frames["raw_accounts"].set_index("account_id")
    for lc in lifecycles[:40]:
        subset = frames["raw_users"]
        subset = subset[subset["account_id"] == lc.account_id]
        signed_up = accounts.loc[lc.account_id, "signed_up_at"]
        assert (subset["created_at"] >= signed_up).all()
        ended = accounts.loc[lc.account_id, "churned_at"]
        if isinstance(ended, str) and ended:
            assert (subset["last_seen_at"] <= ended).all()


def test_churned_accounts_carry_a_churn_timestamp(cfg: LabConfig, frames):
    accounts = frames["raw_accounts"]
    churned = accounts["status"] == "churned"
    assert churned.any()
    assert accounts.loc[churned, "churned_at"].notna().all()
    assert accounts.loc[~churned, "churned_at"].isna().all()
    assert (accounts.loc[churned, "churned_at"] > accounts.loc[churned, "signed_up_at"]).all()


def test_staging_warehouse_enforces_the_declared_schema(frames):
    with StagingWarehouse() as warehouse:
        warehouse.create_all()
        for table in CORE_TABLES:
            warehouse.append(table, frames[table])
        assert warehouse.counts(CORE_TABLES) == {
            t: len(frames[t]) for t in CORE_TABLES
        }

        # A frame missing a declared column is rejected before it reaches CSV.
        with pytest.raises(ValueError, match="missing columns"):
            warehouse.append("raw_accounts", frames["raw_accounts"].drop(columns=["industry"]))


def test_staging_warehouse_rejects_duplicate_primary_keys(frames):
    with StagingWarehouse() as warehouse:
        warehouse.create_all()
        duplicated = pd.concat([frames["raw_plans"], frames["raw_plans"]], ignore_index=True)
        with pytest.raises(Exception, match="[Uu]nique|PRIMARY|duplicate"):
            warehouse.append("raw_plans", duplicated)


def test_export_csv_writes_every_requested_table(frames, tmp_path):
    with StagingWarehouse() as warehouse:
        warehouse.create_all()
        for table in CORE_TABLES:
            warehouse.append(table, frames[table])
        written = warehouse.export_csv(tmp_path, CORE_TABLES)

    assert {p.name for p in written.values()} == {f"{t}.csv" for t in CORE_TABLES}
    reloaded = pd.read_csv(written["raw_accounts"])
    assert len(reloaded) == len(frames["raw_accounts"])
    assert reloaded["account_id"].is_monotonic_increasing


def test_chunked_covers_every_row_exactly_once():
    frame = pd.DataFrame({"n": range(250)})
    pieces = list(chunked(frame, 100))
    assert [len(p) for p in pieces] == [100, 100, 50]
    assert pd.concat(pieces)["n"].tolist() == list(range(250))


def test_every_table_has_ddl():
    assert set(RAW_DDL) == set(RAW_COLUMNS)
