import json

from fastmcp import FastMCP
from google.cloud import bigquery

from briefify.telemetry.feature_engineering import compute_telemetry_features
from briefify.config import (
    GCP_PROJECT_ID,
    DATASET_ID,
    TABLE_ID,
)

# Initialize FastMCP Server
mcp = FastMCP("Account Telemetry MCP Server")

@mcp.tool()
def query_account_usage(company_name: str) -> str:
    """Queries historical 12-month software telemetry data for a target company.

    Returns MAU, seat allocation, API call volume, support tickets, feature adoption, and tier info.
    Use this data to assess account health, upsell readiness, or churn risks.
    """
    client = bigquery.Client(project=GCP_PROJECT_ID)

    sql_query = f"""
        SELECT 
            account_id,
            company_name,
            snapshot_month,
            active_users,
            allocated_seats,
            api_call_volume,
            advanced_features_enabled,
            critical_support_tickets,
            contract_tier
        FROM `{GCP_PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
        WHERE LOWER(company_name) = LOWER(@company_name)
        ORDER BY snapshot_month DESC
        LIMIT 12
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("company_name", "STRING", company_name)
        ]
    )

    try:
        query_job = client.query(sql_query, job_config=job_config)
        rows = [dict(row) for row in query_job.result()]

        if not rows:
            return json.dumps({
                "status": "error",
                "message": f"No telemetry data found for account: {company_name}"
            })

        # Format DATE objects for JSON serialization
        for r in rows:
            if "snapshot_month" in r and r["snapshot_month"]:
                r["snapshot_month"] = str(r["snapshot_month"])
                
        # Compute ML quantitative features
        engineered_features = compute_telemetry_features(rows)
        print(f"[Telemetry MCP] Computed engineered features for {company_name}: {engineered_features}")
        return json.dumps({
            "status": "success",
            "company_name": company_name,
            "records_returned": len(rows),
            "engineered_features": engineered_features.model_dump(), # Quantitative vectors passed to Gemini
            "telemetry": rows
        }, indent=2)

    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"BigQuery Query Execution Failed: {str(e)}"
        })


if __name__ == "__main__":
    # Default stdio execution for MCP integrations
    mcp.run()