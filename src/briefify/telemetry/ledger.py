import os
import json
import time
from pathlib import Path
from typing import Dict, Any

DEFAULT_LOG_DIR = Path(__file__).resolve().parents[3] / "output" / "logs"
LOG_DIR = Path(os.getenv("BRIEFIFY_LOG_DIR", str(DEFAULT_LOG_DIR))).expanduser()
LOG_DIR.mkdir(parents=True, exist_ok=True)
LEDGER_FILE = LOG_DIR / "execution_ledger.jsonl"

MODEL_NAME = os.getenv("BRIEFIFY_LLM_MODEL", "gemini-3.5-flash")
PRICING_VERSION = os.getenv("BRIEFIFY_PRICING_VERSION", "gemini_flash_default_v1")
INPUT_COST_PER_MILLION = float(os.getenv("BRIEFIFY_INPUT_COST_PER_MILLION", "0.075"))
OUTPUT_COST_PER_MILLION = float(os.getenv("BRIEFIFY_OUTPUT_COST_PER_MILLION", "0.30"))


USAGE_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "prompt_token_count": ("prompt_token_count", "prompt_tokens", "input_token_count", "input_tokens"),
    "completion_token_count": (
        "completion_token_count",
        "completion_tokens",
        "output_token_count",
        "output_tokens",
        "candidates_token_count",
        "candidate_token_count",
    ),
    "total_token_count": ("total_token_count", "total_tokens"),
}


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _extract_usage_value(usage_metadata: Any, field_name: str) -> int:
    if not usage_metadata:
        return 0

    aliases = USAGE_FIELD_ALIASES.get(field_name, (field_name,))

    if isinstance(usage_metadata, dict):
        search_space: list[dict[str, Any]] = [usage_metadata]
        nested_usage = usage_metadata.get("usage")
        if isinstance(nested_usage, dict):
            search_space.append(nested_usage)

        for scope in search_space:
            for alias in aliases:
                if alias in scope:
                    return _coerce_int(scope.get(alias))
        return 0

    for alias in aliases:
        value = getattr(usage_metadata, alias, None)
        if value is not None:
            return _coerce_int(value)

    nested_usage = getattr(usage_metadata, "usage", None)
    if isinstance(nested_usage, dict):
        for alias in aliases:
            if alias in nested_usage:
                return _coerce_int(nested_usage.get(alias))

    return 0


def log_execution_event(
    job_id: str,
    company_name: str,
    account_id: str,
    latency_ms: float,
    usage_metadata: Any,
    status: str = "success",
    error_message: str = None,
    pipeline_stage: str = "full_pipeline",
    retry_count: int = 0,
    max_retries: int = 0,
    session_id: str | None = None,
    app_name: str | None = None,
) -> Dict[str, Any]:
    """Records pipeline execution metrics, token counts, and cost telemetry to an append-only JSONL log."""
    
    # Extract GenAI token usage metadata
    prompt_tokens = _extract_usage_value(usage_metadata, "prompt_token_count")
    completion_tokens = _extract_usage_value(usage_metadata, "completion_token_count")
    total_tokens = _extract_usage_value(usage_metadata, "total_token_count")

    # Some SDK events omit total while still reporting prompt/output.
    if total_tokens == 0 and (prompt_tokens > 0 or completion_tokens > 0):
        total_tokens = prompt_tokens + completion_tokens

    # Calculate estimated cost from configurable per-million token rates.
    input_cost_per_token = INPUT_COST_PER_MILLION / 1_000_000
    output_cost_per_token = OUTPUT_COST_PER_MILLION / 1_000_000
    estimated_cost_usd = (prompt_tokens * input_cost_per_token) + (completion_tokens * output_cost_per_token)

    log_entry = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "job_id": job_id,
        "company_name": company_name,
        "account_id": account_id,
        "status": status,
        "pipeline_stage": pipeline_stage,
        "retry_count": retry_count,
        "max_retries": max_retries,
        "latency_ms": round(latency_ms, 2),
        "session_id": session_id,
        "app_name": app_name,
        "model": {
            "name": MODEL_NAME,
            "pricing_version": PRICING_VERSION,
            "input_cost_per_million": INPUT_COST_PER_MILLION,
            "output_cost_per_million": OUTPUT_COST_PER_MILLION,
        },
        "tokens": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens
        },
        "estimated_cost_usd": round(estimated_cost_usd, 8),
        "error": error_message
    }

    # Append to JSONL audit log
    with open(LEDGER_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

    return log_entry