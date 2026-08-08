import json
import time
from pathlib import Path
from typing import Dict, Any

LOG_DIR = Path("output/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LEDGER_FILE = LOG_DIR / "execution_ledger.jsonl"


def log_execution_event(
    job_id: str,
    company_name: str,
    account_id: str,
    latency_ms: float,
    usage_metadata: Any,
    status: str = "success",
    error_message: str = None
) -> Dict[str, Any]:
    """Records pipeline execution metrics, token counts, and cost telemetry to an append-only JSONL log."""
    
    # Extract GenAI token usage metadata
    prompt_tokens = getattr(usage_metadata, "prompt_token_count", 0) if usage_metadata else 0
    completion_tokens = getattr(usage_metadata, "candidates_token_count", 0) if usage_metadata else 0
    total_tokens = getattr(usage_metadata, "total_token_count", 0) if usage_metadata else 0

    # Calculate estimated cost (Gemini 2.5 Flash pricing: ~$0.075 / 1M input tokens, $0.30 / 1M output tokens)
    estimated_cost_usd = (prompt_tokens * 0.000000075) + (completion_tokens * 0.00000030)

    log_entry = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "job_id": job_id,
        "company_name": company_name,
        "account_id": account_id,
        "status": status,
        "latency_ms": round(latency_ms, 2),
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