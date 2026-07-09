"""Deterministic Faker-based seed data for the raw warehouse layer.

Column naming is deliberate: raw_customers keeps the original `cust_id`
column (not `customer_id`) because the canonical Blast Radius demo change
is the later rename of `raw_customers.cust_id` -> `customer_id`.
"""
from __future__ import annotations

import csv
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from faker import Faker

SEED = 42
NUM_CUSTOMERS = 300
NUM_ORDERS = 800
DATA_DIR = Path(__file__).parent / "data"

ORDER_STATUSES = ["completed", "pending", "cancelled", "refunded"]
PAYMENT_METHODS = ["credit_card", "paypal", "bank_transfer", "gift_card"]

# Fixed, absolute bounds -- NOT relative strings like "-2y"/"-30d"/"now".
# Faker resolves relative bounds against the real datetime.now() at call
# time, which `fake.seed_instance(seed)` does not control: the exact window
# a date is drawn from (and so the exact date drawn) shifted depending on
# what day this script happened to run, despite SEED being fixed --
# genuinely non-deterministic output from a script whose whole premise is
# "seed=42 is deterministic." Fixed bounds make every run byte-identical
# regardless of today's date.
CUSTOMER_CREATED_START = datetime(2023, 1, 1)
CUSTOMER_CREATED_END = datetime(2024, 12, 1)
ORDER_DATE_START = datetime(2023, 1, 1)
ORDER_DATE_END = datetime(2025, 1, 1)


def generate_customers(n: int, seed: int) -> list[dict[str, Any]]:
    fake = Faker()
    fake.seed_instance(seed)
    customers = []
    for cust_id in range(1, n + 1):
        customers.append(
            {
                "cust_id": cust_id,
                "first_name": fake.first_name(),
                "last_name": fake.last_name(),
                "email": fake.unique.email(),
                "created_at": fake.date_time_between(
                    start_date=CUSTOMER_CREATED_START, end_date=CUSTOMER_CREATED_END
                ).isoformat(sep=" "),
            }
        )
    return customers


def generate_orders(customers: list[dict[str, Any]], n: int, seed: int) -> list[dict[str, Any]]:
    fake = Faker()
    fake.seed_instance(seed)
    rng = random.Random(seed)
    orders = []
    for order_id in range(1, n + 1):
        customer = rng.choice(customers)
        orders.append(
            {
                "order_id": order_id,
                "cust_id": customer["cust_id"],
                "order_date": fake.date_time_between(
                    start_date=ORDER_DATE_START, end_date=ORDER_DATE_END
                ).isoformat(sep=" "),
                "status": rng.choice(ORDER_STATUSES),
                "amount": round(rng.uniform(15.0, 500.0), 2),
            }
        )
    return orders


def generate_payments(orders: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    payments = []
    payment_id = 1
    for order in orders:
        if order["status"] == "cancelled":
            continue
        payments.append(
            {
                "payment_id": payment_id,
                "order_id": order["order_id"],
                "payment_method": rng.choice(PAYMENT_METHODS),
                "amount": order["amount"],
                "payment_date": order["order_date"],
            }
        )
        payment_id += 1
    return payments


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    customers = generate_customers(NUM_CUSTOMERS, SEED)
    orders = generate_orders(customers, NUM_ORDERS, SEED)
    payments = generate_payments(orders, SEED)

    write_csv(customers, DATA_DIR / "raw_customers.csv")
    write_csv(orders, DATA_DIR / "raw_orders.csv")
    write_csv(payments, DATA_DIR / "raw_payments.csv")

    print(f"Wrote {len(customers)} customers, {len(orders)} orders, {len(payments)} payments to {DATA_DIR}")


if __name__ == "__main__":
    main()
