"""
data_gov_il_mcp
================
MCP server exposing the Israeli government open-data portal (data.gov.il)
as Claude tools. Supports searching datasets, inspecting resource schemas,
and querying any CKAN datastore resource with filters, sort, and pagination.

Public CKAN API — no authentication required.
"""

from __future__ import annotations

import json
import os
from enum import Enum
from typing import Any, Dict, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

# -------------------------------------------------------------
# Constants
# -------------------------------------------------------------
BASE_URL = "https://data.gov.il/api/3/action"
DEFAULT_TIMEOUT = 30.0
USER_AGENT = "data-gov-il-mcp/1.0 (+https://github.com)"

# -------------------------------------------------------------
# Server
# -------------------------------------------------------------
mcp = FastMCP(
    "data_gov_il_mcp",
    host=os.getenv("MCP_HOST", "0.0.0.0"),
    port=int(os.getenv("PORT", os.getenv("MCP_PORT", "8000"))),
)


# -------------------------------------------------------------
# Shared helpers
# -------------------------------------------------------------
async def _ckan_request(endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Call the CKAN action API and return the unwrapped `result` payload."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        response = await client.get(
            f"{BASE_URL}/{endpoint}",
            params=params,
            headers=headers,
            follow_redirects=True,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("success"):
            err = data.get("error", {})
            raise RuntimeError(f"CKAN API error: {err}")
        return data["result"]


def _format_error(e: Exception) -> str:
    """Return a single-line, agent-friendly error string."""
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code == 404:
            return "Error: Resource not found. Verify the resource_id (UUID) is correct."
        if code == 409:
            return "Error: Bad query. Check filter field names match the schema."
        if code == 429:
            return "Error: Rate limit exceeded. Wait a few seconds and retry."
        return f"Error: data.gov.il returned HTTP {code}."
    if isinstance(e, httpx.TimeoutException):
        return "Error: Request to data.gov.il timed out. The portal may be slow."
    if isinstance(e, RuntimeError):
        return f"Error: {e}"
    return f"Error: {type(e).__name__}: {e}"


def _resource_summary(resource: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": resource.get("id"),
        "name": resource.get("name"),
        "format": resource.get("format"),
        "datastore_active": resource.get("datastore_active"),
        "url": resource.get("url"),
    }


# -------------------------------------------------------------
# Tool 1: Search datasets
# -------------------------------------------------------------
class SearchDatasetsInput(BaseModel):
    """Search the data.gov.il dataset catalog."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(
        ...,
        description=(
            "Search query. Hebrew works well, e.g. 'אוכלוסייה', 'תושבים', 'תחבורה ציבורית', "
            "'בריאות', or English like 'population', 'transport', 'health'."
        ),
        min_length=1,
        max_length=200,
    )
    limit: int = Field(
        default=10,
        description="Max datasets to return (1–50).",
        ge=1,
        le=50,
    )


@mcp.tool(
    name="datagov_il_search_datasets",
    annotations={
        "title": "Search data.gov.il datasets",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def datagov_il_search_datasets(params: SearchDatasetsInput) -> str:
    """Search the Israeli government open-data catalog.

    Returns matching dataset packages with their titles, descriptions, and the
    list of resources (CSV/Excel/etc.) inside each dataset. Each resource has a
    UUID that can be passed to `datagov_il_get_resource_schema` and
    `datagov_il_query_resource`.

    Use Hebrew or English keywords. The Israeli portal is largely Hebrew-language,
    so Hebrew queries usually return more results.
    """
    try:
        result = await _ckan_request(
            "package_search",
            {"q": params.query, "rows": params.limit},
        )
        datasets = []
        for pkg in result.get("results", []):
            datasets.append(
                {
                    "id": pkg.get("id"),
                    "name": pkg.get("name"),
                    "title": pkg.get("title"),
                    "notes": (pkg.get("notes") or "")[:400],
                    "organization": (pkg.get("organization") or {}).get("title"),
                    "metadata_modified": pkg.get("metadata_modified"),
                    "resource_count": len(pkg.get("resources", [])),
                    "resources": [_resource_summary(r) for r in pkg.get("resources", [])],
                }
            )
        return json.dumps(
            {
                "total_matches": result.get("count", 0),
                "returned": len(datasets),
                "datasets": datasets,
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        return _format_error(e)


# -------------------------------------------------------------
# Tool 2: Get resource schema
# -------------------------------------------------------------
class GetResourceSchemaInput(BaseModel):
    """Inspect the columns of a data.gov.il resource."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    resource_id: str = Field(
        ...,
        description=(
            "CKAN resource UUID. Example: 'b8112650-a2f8-41f2-9c05-a9b9483fb4c0' "
            "(young residents 18–35 by Israeli settlement)."
        ),
        min_length=10,
        max_length=100,
    )


@mcp.tool(
    name="datagov_il_get_resource_schema",
    annotations={
        "title": "Get data.gov.il resource schema",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def datagov_il_get_resource_schema(params: GetResourceSchemaInput) -> str:
    """Get the field schema of a data.gov.il datastore resource.

    Always call this BEFORE `datagov_il_query_resource` so you know the exact
    field names (often Hebrew) to use in `filters` and `sort`. Returns the field
    list, total record count, and one sample record.
    """
    try:
        result = await _ckan_request(
            "datastore_search",
            {"resource_id": params.resource_id, "limit": 1},
        )
        records = result.get("records", [])
        return json.dumps(
            {
                "resource_id": params.resource_id,
                "total_records": result.get("total"),
                "fields": [
                    {"id": f.get("id"), "type": f.get("type")}
                    for f in result.get("fields", [])
                    if f.get("id") != "_id"
                ],
                "sample_record": records[0] if records else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        return _format_error(e)


# -------------------------------------------------------------
# Tool 3: Query resource
# -------------------------------------------------------------
class QueryResourceInput(BaseModel):
    """Query records from a data.gov.il resource."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    resource_id: str = Field(
        ...,
        description=(
            "CKAN resource UUID. The featured resource is "
            "'b8112650-a2f8-41f2-9c05-a9b9483fb4c0' — young residents (18–35) "
            "of Israel by settlement, useful for media-planning audience sizing."
        ),
        min_length=10,
        max_length=100,
    )
    q: Optional[str] = Field(
        default=None,
        description=(
            "Full-text search across all string fields. Hebrew works "
            "(e.g. 'תל אביב', 'חיפה', 'ירושלים')."
        ),
        max_length=500,
    )
    filters: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Exact-match filters as a dict. Field names must match the schema "
            "exactly (often Hebrew). Example: {\"שם_ישוב\": \"חיפה\"}."
        ),
    )
    sort: Optional[str] = Field(
        default=None,
        description=(
            "CKAN sort expression. Format: '<field> <asc|desc>'. "
            "Example: 'סהכ desc' to sort by total descending."
        ),
        max_length=200,
    )
    limit: int = Field(
        default=20,
        description="Max records to return (1–500).",
        ge=1,
        le=500,
    )
    offset: int = Field(
        default=0,
        description="Pagination offset (records to skip).",
        ge=0,
    )


@mcp.tool(
    name="datagov_il_query_resource",
    annotations={
        "title": "Query data.gov.il resource",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def datagov_il_query_resource(params: QueryResourceInput) -> str:
    """Query records from a data.gov.il datastore resource.

    Workflow:
      1. (Optional) Run `datagov_il_search_datasets` to find datasets.
      2. Run `datagov_il_get_resource_schema` to learn the field names.
      3. Run this tool with `q`, `filters`, `sort`, `limit`, and `offset` as needed.

    Returns total match count, returned records, and pagination metadata
    (`has_more`, `next_offset`).
    """
    try:
        api_params: Dict[str, Any] = {
            "resource_id": params.resource_id,
            "limit": params.limit,
            "offset": params.offset,
        }
        if params.q:
            api_params["q"] = params.q
        if params.filters:
            api_params["filters"] = json.dumps(params.filters, ensure_ascii=False)
        if params.sort:
            api_params["sort"] = params.sort

        result = await _ckan_request("datastore_search", api_params)
        records = result.get("records", [])
        total = result.get("total", 0)
        next_offset = params.offset + len(records)
        has_more = next_offset < total

        return json.dumps(
            {
                "resource_id": params.resource_id,
                "total": total,
                "returned": len(records),
                "offset": params.offset,
                "next_offset": next_offset if has_more else None,
                "has_more": has_more,
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        return _format_error(e)


# -------------------------------------------------------------
# Tool 4: Convenience — youth (18–35) by settlement
# -------------------------------------------------------------
YOUTH_RESOURCE_ID = "b8112650-a2f8-41f2-9c05-a9b9483fb4c0"


class YouthBySettlementInput(BaseModel):
    """Look up young-resident counts for one or many Israeli settlements."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    settlement: Optional[str] = Field(
        default=None,
        description=(
            "Hebrew settlement name (full or partial). Example: 'תל אביב', 'חיפה', "
            "'ירושלים', 'רמת גן'. If omitted, returns the top settlements by "
            "population."
        ),
        max_length=100,
    )
    limit: int = Field(
        default=20,
        description="Max settlements to return (1–500).",
        ge=1,
        le=500,
    )


@mcp.tool(
    name="datagov_il_youth_by_settlement",
    annotations={
        "title": "Israeli youth (18–35) by settlement",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def datagov_il_youth_by_settlement(params: YouthBySettlementInput) -> str:
    """Convenience tool — young Israeli residents (ages 18–35) by settlement.

    Wraps the featured CMS Bureau of Statistics resource
    (b8112650-a2f8-41f2-9c05-a9b9483fb4c0) with sensible defaults so you don't
    need to remember the resource_id. Useful for media-planning audience sizing
    in the Israeli market.
    """
    try:
        api_params: Dict[str, Any] = {
            "resource_id": YOUTH_RESOURCE_ID,
            "limit": params.limit,
        }
        if params.settlement:
            api_params["q"] = params.settlement
        result = await _ckan_request("datastore_search", api_params)
        return json.dumps(
            {
                "source": "data.gov.il / CBS — youth (18–35) by settlement",
                "total": result.get("total", 0),
                "returned": len(result.get("records", [])),
                "fields": [
                    f.get("id")
                    for f in result.get("fields", [])
                    if f.get("id") != "_id"
                ],
                "records": result.get("records", []),
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        return _format_error(e)


# -------------------------------------------------------------
# Entrypoint
# -------------------------------------------------------------
def main() -> None:
    transport = os.getenv("MCP_TRANSPORT", "streamable-http").lower()
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        # Streamable HTTP — use this for hosted / claude.ai connector use.
        # Endpoint will be available at: http://<host>:<port>/mcp
        mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
