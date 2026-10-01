# SaaS Telemetry Generator

Synthetic B2B SaaS data: 2,000 accounts, 20,000 users, 3,485 subscription terms and **1,000,000
product events** across 24 months, written into Postgres for
[`dwh-dbt`](https://github.com/matheus-amon/dwh-dbt) to model.

| | |
|---|---|
| **Output** | 5 raw tables · 1M events · 43 seconds · 1 GB peak RSS |
| **Reproducible** | Seeded — two runs with the same arguments are byte-identical |
| **Tests** | 53, including behavioural assertions about the data itself |
| **Constraint-checked** | Frames pass through DuckDB with declared types before export |

A dbt project is only as good as what it has to chew on. Most portfolio warehouses ship a few dozen
hand-written rows, which leaves the interesting parts untestable: no seasonality, no churn, no plan
upgrades, no volume, no declining usage before a cancellation. This generates the behaviour a real
B2B SaaS database has, so the warehouse downstream has something worth modelling.

---

## What makes it non-trivial

**Churn is preceded by a visible usage decline.** A third of accounts enter a terminal decline;
cancellation follows once engagement falls past a threshold, with a small baseline hazard for
accounts that simply leave.

Measured on the test fixture: usage in the eight weeks before a cancellation is **below the
account's own settled baseline for 87% of churned accounts**, median ratio **0.50**. This is the
signal `mart_account_health` in the warehouse ranks accounts on — and it is the reason the generator
exists rather than a `random.seed` loop.

**Subscriptions are periods, not rows.** An upgrade closes one term and opens the next; a churn
closes one for good. That shape is what makes new / expansion / contraction / churned MRR
derivable rather than guessed.

**Plan tiers gate product access.** `sso` and `audit_log` exist only on `scale` and above,
`advanced_analytics` only on `enterprise`. Adoption metrics therefore measure adoption instead of
plan mix.

**Terms chain on a single boundary timestamp**, so they neither overlap nor gap — and plan changes
snap to week starts, because entitlement is modelled weekly and a boundary partway through a week
lets the generator emit events for a tier the account has not reached yet.

**Seasons and weekdays.** Weekdays run about 2.5× weekends, business hours dominate, and December
carries an uplift.

**No event ever predates an account or outlasts it**, and API activity only ever appears on the
`api` platform.

---

## The raw layer

| Table | Grain | Rows |
|---|---|---|
| `raw_plans` | one row per plan tier | 4 |
| `raw_accounts` | one row per B2B customer | 2,000 |
| `raw_users` | one row per person inside an account | 20,000 |
| `raw_subscriptions` | one row per uninterrupted period on a plan | 3,485 |
| `raw_product_events` | one row per product action | 1,000,000 |

The schema is the contract with the warehouse's source definitions, and it is declared once in
`src/telemetry_lab/schema.py` — the DDL, the column order and the `COPY` statement are all derived
from that, after a join over bare column names produced invalid SQL.

Accounts churn and upgrade the way you'd expect:

```
2,000 accounts · 438 churned (22%) · 1,007 with a plan change · $4.1M active MRR
```

---

## Quickstart

```bash
cp .env.telemetry.example .env.telemetry
make install
make bootstrap      # starts Postgres, generates ~1M events, loads them into raw.*
```

About a minute end to end. `make test` runs the suite.

```bash
make smoke          # 50k events, seconds instead of a minute
```

`make smoke` is enough to check the pipeline and **not** enough to read
`mart_account_health`: at roughly one event per account per week, two thirds of accounts score as
dormant and only two of the five health bands ever appear. The mart's distribution depends on
telemetry density, which is why the full set is the default.

---

## Layout

```
src/telemetry_lab/
  cli.py             argparse entry point: generate, load
  config.py          volumes, history window, seed, output paths
  schema.py          raw table definitions — single source of truth for the DDL
  duck.py            DuckDB staging: validates and orders frames before export
  load.py            CSV → Postgres via COPY
  domain/
    plans.py         plan catalogue, pricing, feature gating
    lifecycle.py     the behaviour simulator
  generators/        one module per raw table
tests/
```

The generator hands frames to a DuckDB staging layer with the declared types and constraints
before export, so a generator bug fails here rather than as a dbt test failure in another repo.
That caught three real bugs during development, including one where a 2-D probability array made
`rng.multinomial` draw its entire event budget once per account.

---

## Tests

53, of which the useful ones are behavioural rather than structural:

- `test_churn_is_preceded_by_a_usage_decline` — the claim above, as an assertion
- `test_terms_chain_without_gaps` — boundaries cannot overlap or invert
- `test_plan_changes_land_on_a_week_start` — entitlement stays consistent with terms
- `test_signups_span_the_whole_history_window` — acquisition does not stop before the window does
- `test_every_account_has_exactly_one_admin` — by construction, asserted anyway
- `test_generation_is_reproducible` — seeded output is byte-identical
- `test_every_event_has_a_subscription_period` — no orphan telemetry
- `test_paid_features_never_appear_below_their_tier` — gating holds end to end

That signup-window test exists because reserving the final weeks for minimum tenure silently
produced three months of zero new MRR in the revenue mart — which reads as a broken model rather
than a truncated one. Exactly the kind of thing that gets spotted in review.

---

## Also in this repo

The market-data tooling: `src/get_quotes.py` and `src/upload_quotes.py`, with Terraform in
`.terraform/` and a Postgres service in `docker-compose.yml`. Untouched by the work here — the
telemetry generator has its own compose file on port 5434, partly because the other one tracks
`postgres:latest` against a persistent volume, which is what makes it fail to start after a major
version bump.

## Lineage

Independent implementation. Inspired by Airflow/dbt workshop material the author worked through — a
local-setup repo, a dbt warehouse, and an Airflow orchestration repo — and reusing no code from it.
The domain, the behaviour model, the naming and the structure here are original to this project.

## Licence

MIT