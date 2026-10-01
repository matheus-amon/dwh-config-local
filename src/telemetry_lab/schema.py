"""Physical schema of the raw layer.

The dbt project in ``saas-metrics-dwh`` declares these tables as sources with the same column
names, so this module is the contract between the two repos. If a column changes here, the
source definition there has to change with it.

Column types are declared once, in :data:`RAW_TABLE_COLUMNS`; the DDL used to create the
Postgres tables and the column list used by ``COPY`` are both derived from it.
"""

from __future__ import annotations

#: table -> ordered column -> Postgres type (with any inline constraint).
RAW_TABLE_COLUMNS: dict[str, dict[str, str]] = {
    "raw_plans": {
        "plan_code": "VARCHAR PRIMARY KEY",
        "plan_name": "VARCHAR NOT NULL",
        "monthly_price_usd": "DECIMAL(10,2) NOT NULL",
        "included_seats": "INTEGER NOT NULL",
        "billing_interval": "VARCHAR NOT NULL",
        "tier_rank": "INTEGER NOT NULL",
    },
    "raw_accounts": {
        "account_id": "INTEGER PRIMARY KEY",
        "account_name": "VARCHAR NOT NULL",
        "domain": "VARCHAR NOT NULL",
        "industry": "VARCHAR NOT NULL",
        "employee_band": "VARCHAR NOT NULL",
        "country_code": "VARCHAR NOT NULL",
        "region": "VARCHAR NOT NULL",
        "signed_up_at": "TIMESTAMP NOT NULL",
        "plan_code_at_signup": "VARCHAR NOT NULL",
        "seats": "INTEGER NOT NULL",
        "status": "VARCHAR NOT NULL",
        "churned_at": "TIMESTAMP",
    },
    "raw_users": {
        "user_id": "INTEGER PRIMARY KEY",
        "account_id": "INTEGER NOT NULL",
        "email": "VARCHAR NOT NULL",
        "full_name": "VARCHAR NOT NULL",
        "role": "VARCHAR NOT NULL",
        "is_admin": "BOOLEAN NOT NULL",
        "created_at": "TIMESTAMP NOT NULL",
        "last_seen_at": "TIMESTAMP",
    },
    "raw_subscriptions": {
        "subscription_id": "BIGINT PRIMARY KEY",
        "account_id": "INTEGER NOT NULL",
        "plan_code": "VARCHAR NOT NULL",
        "billing_interval": "VARCHAR NOT NULL",
        "seats": "INTEGER NOT NULL",
        "discount_pct": "DECIMAL(5,2) NOT NULL",
        "mrr_usd": "DECIMAL(10,2) NOT NULL",
        "started_at": "TIMESTAMP NOT NULL",
        "ended_at": "TIMESTAMP",
        "ended_reason": "VARCHAR",
    },
    "raw_product_events": {
        "event_id": "BIGINT PRIMARY KEY",
        "account_id": "INTEGER NOT NULL",
        "user_id": "INTEGER NOT NULL",
        "event_name": "VARCHAR NOT NULL",
        "feature": "VARCHAR NOT NULL",
        "platform": "VARCHAR NOT NULL",
        "session_id": "VARCHAR NOT NULL",
        "country_code": "VARCHAR NOT NULL",
        "event_ts": "TIMESTAMP NOT NULL",
        "event_date": "DATE NOT NULL",
    },
}

#: Column order per table. Derived, so it can never drift from the type declarations.
RAW_COLUMNS: dict[str, tuple[str, ...]] = {
    table: tuple(columns) for table, columns in RAW_TABLE_COLUMNS.items()
}


def _ddl(table: str) -> str:
    columns = ",\n    ".join(
        f"{name} {sql_type}" for name, sql_type in RAW_TABLE_COLUMNS[table].items()
    )
    return f"CREATE TABLE IF NOT EXISTS {table} (\n    {columns}\n)"


RAW_DDL: dict[str, str] = {table: _ddl(table) for table in RAW_TABLE_COLUMNS}
