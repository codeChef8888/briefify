import os
import time
import datetime as dt
from functools import lru_cache
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
from briefify.schemas.error_contract import build_error


MAX_NODE_INPUT_BYTES = int(os.getenv("TELEMETRY_NODE_MAX_INPUT_BYTES", "8192"))
BQ_MAX_RETRIES = int(os.getenv("BQ_MAX_RETRIES", "2"))
BQ_RETRY_BASE_DELAY_SEC = float(os.getenv("BQ_RETRY_BASE_DELAY_SEC", "0.5"))
BQ_QUERY_TIMEOUT_SEC = float(os.getenv("BQ_QUERY_TIMEOUT_SEC", "15"))
TELEMETRY_LOOKBACK_MONTHS = int(os.getenv("TELEMETRY_LOOKBACK_MONTHS", "12"))
TELEMETRY_REQUIRE_CONTIGUOUS_MONTHS = os.getenv("TELEMETRY_REQUIRE_CONTIGUOUS_MONTHS", "1").lower() in {"1", "true", "yes", "on"}
TELEMETRY_ENABLE_PARTITION_PRUNING = os.getenv("TELEMETRY_ENABLE_PARTITION_PRUNING", "1").lower() in {"1", "true", "yes", "on"}

APP_ENV = os.getenv("APP_ENV", "dev").lower()
BQ_ENABLE_DRY_RUN_GUARD = os.getenv("BQ_ENABLE_DRY_RUN_GUARD", "0").lower() in {"1", "true", "yes", "on"}
BQ_DRY_RUN_MAX_BYTES = int(os.getenv("BQ_DRY_RUN_MAX_BYTES", "1000000000"))


def _is_prod_env() -> bool:
    return APP_ENV in {"prod", "production"}


def _subtract_months(date_value: dt.date, months: int) -> dt.date:
    """Return date shifted back by N months, clamped to day 1."""
    year = date_value.year
    month = date_value.month - months
    while month <= 0:
        month += 12
        year -= 1
    return dt.date(year, month, 1)


def _month_key(snapshot_month: Any) -> tuple[int, int]:
    if isinstance(snapshot_month, dt.datetime):
        snapshot_month = snapshot_month.date()

    if isinstance(snapshot_month, dt.date):
        return snapshot_month.year, snapshot_month.month

    parsed = dt.date.fromisoformat(str(snapshot_month)[:10])
    return parsed.year, parsed.month


def _validate_contiguous_months(rows: list[dict]) -> str | None:
    """Return error message when month series has gaps; otherwise None."""
    if not rows:
        return None

    month_keys = sorted({_month_key(row.get("snapshot_month")) for row in rows if row.get("snapshot_month")}, reverse=True)
    if len(month_keys) < 2:
        return None

    numeric_months = [year * 12 + month for year, month in month_keys]
    for idx in range(1, len(numeric_months)):
        if numeric_months[idx - 1] - numeric_months[idx] != 1:
            prev_year, prev_month = month_keys[idx - 1]
            curr_year, curr_month = month_keys[idx]
            return (
                "Telemetry snapshots are not contiguous month-over-month "
                f"between {prev_year:04d}-{prev_month:02d} and {curr_year:04d}-{curr_month:02d}."
            )

    return None


def _build_query(trigger: AccountTrigger) -> tuple[str, bigquery.QueryJobConfig]:
    where_partition_filter = "snapshot_month >= DATE_SUB(CURRENT_DATE(), INTERVAL @lookback_months MONTH)"
    query_parameters: list[bigquery.ScalarQueryParameter] = [
        bigquery.ScalarQueryParameter("company_name", "STRING", trigger.company_name),
        bigquery.ScalarQueryParameter("account_id", "STRING", trigger.account_id or None),
        bigquery.ScalarQueryParameter("lookback_months", "INT64", TELEMETRY_LOOKBACK_MONTHS),
    ]

    if TELEMETRY_ENABLE_PARTITION_PRUNING:
        lookback_start_date = _subtract_months(dt.date.today().replace(day=1), TELEMETRY_LOOKBACK_MONTHS)
        where_partition_filter = "snapshot_month >= @lookback_start_date"
        query_parameters.append(
            bigquery.ScalarQueryParameter("lookback_start_date", "DATE", lookback_start_date)
        )

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
        WHERE
            LOWER(company_name) = LOWER(@company_name)
            AND (@account_id IS NULL OR account_id = @account_id)
            AND {where_partition_filter}
        ORDER BY
            snapshot_month DESC,
            account_id ASC,
            company_name ASC
        LIMIT @lookback_months
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=query_parameters,
        labels={
            "pipeline": "briefify",
            "node": "telemetry",
        },
    )
    return sql_query, job_config


def _dry_run_cost_guard(client: bigquery.Client, sql_query: str, job_config: bigquery.QueryJobConfig) -> str | None:
    if _is_prod_env() or not BQ_ENABLE_DRY_RUN_GUARD:
        return None

    dry_run_config = bigquery.QueryJobConfig(
        query_parameters=job_config.query_parameters,
        labels=job_config.labels,
        dry_run=True,
        use_query_cache=False,
    )
    dry_run_job = client.query(sql_query, job_config=dry_run_config)
    bytes_processed = int(dry_run_job.total_bytes_processed or 0)
    if bytes_processed > BQ_DRY_RUN_MAX_BYTES:
        return (
            "Dry-run bytes guard exceeded for telemetry query: "
            f"{bytes_processed} bytes > {BQ_DRY_RUN_MAX_BYTES} bytes."
        )
    return None


def _error_event(code: str, message: str, retryable: bool = False) -> Event:
    return Event(output=build_error(
        code=code,
        message=message,
        stage="telemetry_node",
        retryable=retryable,
    ))


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


@lru_cache(maxsize=1)
def _get_bigquery_client() -> bigquery.Client:
    """Reuse client across calls to reduce connection/setup overhead."""
    return bigquery.Client(project=GCP_PROJECT_ID)


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
    
    Queries historical software telemetry data for a target company,
    constrained by TELEMETRY_LOOKBACK_MONTHS (default 12).

    Returns MAU, seat allocation, API call volume, support tickets, feature adoption, and tier info.
    Use this data to assess account health, upsell readiness, or churn risks.
    """
    
    try:
        trigger = _coerce_trigger(node_input)
    except ValueError as exc:
        return _error_event("INVALID_TRIGGER_PAYLOAD", str(exc), retryable=False)
    
    client = _get_bigquery_client()

    sql_query, job_config = _build_query(trigger)

    try:
        dry_run_error = _dry_run_cost_guard(client, sql_query, job_config)
        if dry_run_error:
            return _error_event(
                "BIGQUERY_DRY_RUN_COST_GUARD",
                dry_run_error,
                retryable=False,
            )
    except Exception as exc:
        return _error_event(
            "BIGQUERY_DRY_RUN_FAILED",
            f"BigQuery dry-run guard failed: {str(exc)}",
            retryable=False,
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

            if TELEMETRY_REQUIRE_CONTIGUOUS_MONTHS:
                contiguous_error = _validate_contiguous_months(rows)
                if contiguous_error:
                    return _error_event(
                        "TELEMETRY_NON_CONTIGUOUS_MONTHS",
                        contiguous_error,
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


