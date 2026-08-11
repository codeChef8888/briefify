import os
import time
from json import JSONDecodeError
from typing import Any
from google.cloud import bigquery
from google.api_core import exceptions as gexc
from google.adk import Event
from briefify.telemetry.feature_engineering import compute_telemetry_features
from briefify.config import (
    GCP_PROJECT_ID,
    DATASET_ID,
    TABLE_ID,
)
from briefify.schemas.brief_schema import AccountTrigger


MAX_NODE_INPUT_BYTES = int(os.getenv("TELEMETRY_NODE_MAX_INPUT_BYTES", "8192"))
BQ_MAX_RETRIES = int(os.getenv("BQ_MAX_RETRIES", "2"))
BQ_RETRY_BASE_DELAY_SEC = float(os.getenv("BQ_RETRY_BASE_DELAY_SEC", "0.5"))
BQ_QUERY_TIMEOUT_SEC = float(os.getenv("BQ_QUERY_TIMEOUT_SEC", "15"))


def _error_event(code: str, message: str, retryable: bool = False) -> Event:
    return Event(output={
        "status": "error",
        "code": code,
        "message": message,
        "retryable": retryable,
    })


def _extract_text_from_content(node_input: Any) -> str | None:
    """Extract text from ADK/GenAI content-like payloads in a best-effort way."""
    parts = getattr(node_input, "parts", None)
    if not parts:
        return None

    text_chunks: list[str] = []
    for part in parts:
        text = getattr(part, "text", None)
        if isinstance(text, str) and text.strip():
            text_chunks.append(text)

    if not text_chunks:
        return None

    return "\n".join(text_chunks)


def _coerce_trigger(node_input: Any) -> AccountTrigger:
    """Normalize workflow input into AccountTrigger for ADK v2 compatibility."""
    if isinstance(node_input, AccountTrigger):
        return node_input

    if isinstance(node_input, dict):
        return AccountTrigger.model_validate(node_input)

    if isinstance(node_input, str):
        if len(node_input.encode("utf-8")) > MAX_NODE_INPUT_BYTES:
            raise ValueError(f"Trigger payload exceeds max size of {MAX_NODE_INPUT_BYTES} bytes")
        try:
            return AccountTrigger.model_validate_json(node_input)
        except Exception as exc:
            raise ValueError(f"Unable to parse JSON trigger payload string: {exc}") from exc

    # ADK passes google.genai.types.Content to the first workflow node.
    payload_text = _extract_text_from_content(node_input)
    if payload_text:
        if len(payload_text.encode("utf-8")) > MAX_NODE_INPUT_BYTES:
            raise ValueError(f"Content payload exceeds max size of {MAX_NODE_INPUT_BYTES} bytes")
        try:
            return AccountTrigger.model_validate_json(payload_text)
        except JSONDecodeError as exc:
            raise ValueError("Content payload text is not valid JSON for AccountTrigger") from exc
        except Exception as exc:
            raise ValueError(f"Invalid Content payload for AccountTrigger: {exc}") from exc

    raise ValueError(
        f"Invalid node_input payload type: {type(node_input)}. "
        "Expected AccountTrigger, dict, JSON string, or Content(parts[].text)."
    )


def query_account_usage(node_input: Any) -> Event:
    """Node 1: Executes parameterized SQL against BigQuery and runs ML feature engineering.
    
    Cost: $0 LLM Tokens.
    
    Queries historical 12-month software telemetry data for a target company.

    Returns MAU, seat allocation, API call volume, support tickets, feature adoption, and tier info.
    Use this data to assess account health, upsell readiness, or churn risks.
    """
    
    try:
        trigger = _coerce_trigger(node_input)
    except ValueError as exc:
        return _error_event("INVALID_TRIGGER_PAYLOAD", str(exc), retryable=False)
    
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
            bigquery.ScalarQueryParameter("company_name", "STRING", trigger.company_name)
        ]
    )

    for attempt in range(BQ_MAX_RETRIES + 1):
        try:
            query_job = client.query(sql_query, job_config=job_config)
            rows = [dict(row) for row in query_job.result(timeout=BQ_QUERY_TIMEOUT_SEC)]

            if not rows:
                return _error_event(
                    "TELEMETRY_NOT_FOUND",
                    f"No telemetry data found for account: {trigger.company_name}",
                    retryable=False,
                )

            # Format DATE objects for JSON serialization
            for r in rows:
                if "snapshot_month" in r and r["snapshot_month"]:
                    r["snapshot_month"] = str(r["snapshot_month"])

            # Compute ML quantitative features
            engineered_features = compute_telemetry_features(rows)

            print(f"[Telemetry MCP] Computed engineered features for {trigger.company_name}: {engineered_features}")

            # Payload passed directly to the next node via edge
            payload = {
                "account_id": trigger.account_id,
                "company_name": trigger.company_name,
                "records_returned": len(rows),
                "engineered_features": engineered_features.model_dump(),
                "telemetry": rows
            }
            return Event(output=payload)
        except (gexc.DeadlineExceeded, gexc.TooManyRequests, gexc.ServiceUnavailable) as exc:
            if attempt >= BQ_MAX_RETRIES:
                return _error_event(
                    "BIGQUERY_TRANSIENT_FAILURE",
                    f"BigQuery transient failure after retries: {str(exc)}",
                    retryable=True,
                )
            time.sleep(BQ_RETRY_BASE_DELAY_SEC * (2 ** attempt))
        except Exception as exc:
            return _error_event(
                "BIGQUERY_EXECUTION_FAILED",
                f"BigQuery execution failed: {str(exc)}",
                retryable=False,
            )


