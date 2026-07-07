"""Captures golden outputs (row counts + checksums) for later V4 data-parity checks."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

GOLDEN_DIR = Path(__file__).parent
TABLES = ["fct_orders", "fct_revenue"]


def get_connection():
    return psycopg2.connect(
        host=os.environ.get("PG_HOST", "localhost"),
        port=os.environ.get("PG_PORT", "5433"),
        user=os.environ.get("PG_USER", "postgres_user"),
        password=os.environ.get("PG_PASSWORD", "postgres_password"),
        dbname=os.environ.get("PG_DATABASE", "warehouse"),
    )


def compute_checksum(rows: list[tuple]) -> str:
    """Order-independent checksum over row contents."""
    row_hashes = sorted(hashlib.sha256(repr(row).encode("utf-8")).hexdigest() for row in rows)
    return hashlib.sha256("".join(row_hashes).encode("utf-8")).hexdigest()


def capture_table(conn, table: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {table} ORDER BY 1")
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
    return {
        "table": table,
        "row_count": len(rows),
        "columns": columns,
        "checksum": compute_checksum(rows),
    }


def main() -> None:
    conn = get_connection()
    try:
        for table in TABLES:
            golden = capture_table(conn, table)
            out_path = GOLDEN_DIR / f"{table}.json"
            out_path.write_text(json.dumps(golden, indent=2) + "\n")
            print(f"Captured golden output for {table}: {golden['row_count']} rows -> {out_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
