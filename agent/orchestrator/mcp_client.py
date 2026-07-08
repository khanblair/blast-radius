"""Reusable async MCP client session for talking to the DataHub MCP server.

Every agent stage that needs DataHub goes through this, not the raw SDK --
Loop 2's demo surface is the MCP call trace, and "Use of DataHub" (tiebreaker
#1) is scored on going through the required MCP Server, not around it.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()


def _server_params() -> StdioServerParameters:
    return StdioServerParameters(
        command="uvx",
        args=["mcp-server-datahub"],
        env={
            "DATAHUB_GMS_URL": os.environ.get("DATAHUB_GMS_URL", "http://localhost:8080"),
            "DATAHUB_GMS_TOKEN": os.environ.get("DATAHUB_GMS_TOKEN", ""),
            "TOOLS_IS_MUTATION_ENABLED": "true",
        },
    )


@asynccontextmanager
async def datahub_mcp_session():
    async with stdio_client(_server_params()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session
