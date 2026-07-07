"""Loads generated seed CSVs into the Postgres warehouse."""
from __future__ import annotations

import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(__file__).parent / "data"

TABLE_SCHEMAS = {
    "raw_customers": """
        CREATE TABLE IF NOT EXISTS raw_customers (
            cust_id INTEGER PRIMARY KEY,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
    """,
    "raw_orders": """
        CREATE TABLE IF NOT EXISTS raw_orders (
            order_id INTEGER PRIMARY KEY,
            cust_id INTEGER NOT NULL REFERENCES raw_customers(cust_id),
            order_date TIMESTAMP NOT NULL,
            status TEXT NOT NULL,
            amount NUMERIC(10, 2) NOT NULL
        )
    """,
    "raw_payments": """
        CREATE TABLE IF NOT EXISTS raw_payments (
            payment_id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES raw_orders(order_id),
            payment_method TEXT NOT NULL,
            amount NUMERIC(10, 2) NOT NULL,
            payment_date TIMESTAMP NOT NULL
        )
    """,
}

LOAD_ORDER = ["raw_customers", "raw_orders", "raw_payments"]


def get_connection():
    return psycopg2.connect(
        host=os.environ.get("PG_HOST", "localhost"),
        port=os.environ.get("PG_PORT", "5433"),
        user=os.environ.get("PG_USER", "postgres_user"),
        password=os.environ.get("PG_PASSWORD", "postgres_password"),
        dbname=os.environ.get("PG_DATABASE", "warehouse"),
    )


def load_table(conn, table: str) -> int:
    csv_path = DATA_DIR / f"{table}.csv"
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
        with csv_path.open() as f:
            cur.copy_expert(f"COPY {table} FROM STDIN WITH CSV HEADER", f)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        return cur.fetchone()[0]


def main() -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for table in LOAD_ORDER:
                cur.execute(TABLE_SCHEMAS[table])
        conn.commit()

        for table in LOAD_ORDER:
            count = load_table(conn, table)
            print(f"Loaded {count} rows into {table}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
