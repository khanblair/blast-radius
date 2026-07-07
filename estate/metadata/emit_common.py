"""Shared helpers for DataHub metadata emission scripts."""
from __future__ import annotations

import os

from datahub.emitter.mce_builder import make_dataset_urn
from datahub.emitter.rest_emitter import DatahubRestEmitter
from dotenv import load_dotenv

load_dotenv()

ENV = "PROD"
DATABASE = os.environ.get("PG_DATABASE", "warehouse")
SCHEMA = "public"


def get_emitter() -> DatahubRestEmitter:
    server = os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080")
    token = os.environ.get("DATAHUB_GMS_TOKEN") or None
    return DatahubRestEmitter(gms_server=server, token=token)


def dataset_urn(table_name: str) -> str:
    """URN for a table, matching the postgres-source-ingested identifier
    (`database.schema.table`) so ownership/glossary/lineage attach to the
    same physical entity raw-Postgres and dbt ingestion both resolve to."""
    return make_dataset_urn(platform="postgres", name=f"{DATABASE}.{SCHEMA}.{table_name}", env=ENV)
