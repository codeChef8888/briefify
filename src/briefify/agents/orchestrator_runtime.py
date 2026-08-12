import json
import os
import time
from typing import Any, Dict

from google.genai import types as gtypes
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import Workflow

from briefify.schemas.brief_schema import AccountTrigger
from briefify.schemas.error_contract import build_error
from briefify.telemetry.ledger import log_execution_event

TERMINAL_STATES = {"published", "refused", "error"}
DEBUG_NODE_IO = os.getenv("WORKFLOW_DEBUG_NODE_IO", "0").lower() in {"1", "true", "yes", "on"}
DEBUG_NODE_IO_MAX_CHARS = int(os.getenv("WORKFLOW_DEBUG_NODE_IO_MAX_CHARS", "5000"))
DEBUG_USAGE_METADATA = os.getenv("WORKFLOW_DEBUG_USAGE_METADATA", "0").lower() in {"1", "true", "yes", "on"}


def latency_ms(start_perf: float) -> float:
    return (time.perf_counter() - start_perf) * 1000


def is_schema_validation_error(message: str) -> bool:
    lowered = message.lower()
    return "validation" in lowered or "schema" in lowered


def build_terminal_response(
    status: str,
    company_name: str,
    message: str,
    *,
    code: str | None = None,
    stage: str = "agent_orchestrator",
    retryable: bool = False,
    details: Any | None = None,
) -> Dict[str, Any]:
    if status in {"error", "refused"}:
        payload = build_error(
            code=code or "WORKFLOW_EXECUTION_ERROR",
            message=message,
            stage=stage,
            retryable=retryable,
            status=status,
            details=details,
        )
        payload["company_name"] = company_name
        return payload

    return {
        "status": status,
        "company_name": company_name,
        "message": message,
    }


def build_runner_message(account_id: str, company_name: str) -> gtypes.Content:
    trigger_payload = AccountTrigger(account_id=account_id, company_name=company_name)
    return gtypes.Content(
        role="user",
        parts=[gtypes.Part(text=trigger_payload.model_dump_json())],
    )


def build_runner(
    *,
    pipeline: Workflow,
    app_name: str,
    session_service: InMemorySessionService,
) -> Runner:
    return Runner(
        node=pipeline,
        app_name=app_name,
        session_service=session_service,
        auto_create_session=True,
    )


def extract_terminal_output(out: dict) -> tuple[str, str, str, bool, Any | None]:
    out_status = out.get("status") or "error"
    out_message = out.get("message") or "Workflow node emitted an error status"
    out_code = out.get("code", "WORKFLOW_NODE_ERROR")
    out_stage = out.get("stage", "workflow_node")
    out_retryable = bool(out.get("retryable", False))
    out_details = out.get("details")
    return out_status, out_message, out_code, out_retryable, (out_stage, out_details)


def merge_usage_metadata(existing: Any, incoming: Any) -> Dict[str, int]:
    """Consolidate usage across events into canonical token counters.

    ADK may emit usage on multiple events with different field names.
    We avoid last-event overwrites dropping completion tokens, while also
    avoiding additive overcounting when the same usage appears on multiple events.
    """

    def _extract(scope: Any, keys: tuple[str, ...]) -> int:
        if not scope:
            return 0
        if isinstance(scope, dict):
            for key in keys:
                if key in scope and scope.get(key) is not None:
                    try:
                        return int(scope.get(key) or 0)
                    except (TypeError, ValueError):
                        return 0
            nested = scope.get("usage")
            if isinstance(nested, dict):
                for key in keys:
                    if key in nested and nested.get(key) is not None:
                        try:
                            return int(nested.get(key) or 0)
                        except (TypeError, ValueError):
                            return 0
            return 0

        for key in keys:
            value = getattr(scope, key, None)
            if value is not None:
                try:
                    return int(value or 0)
                except (TypeError, ValueError):
                    return 0

        nested = getattr(scope, "usage", None)
        if isinstance(nested, dict):
            for key in keys:
                if key in nested and nested.get(key) is not None:
                    try:
                        return int(nested.get(key) or 0)
                    except (TypeError, ValueError):
                        return 0
        return 0

    consolidated = {
        "prompt_token_count": 0,
        "completion_token_count": 0,
        "total_token_count": 0,
    }

    if isinstance(existing, dict):
        consolidated["prompt_token_count"] = int(existing.get("prompt_token_count", 0) or 0)
        consolidated["completion_token_count"] = int(existing.get("completion_token_count", 0) or 0)
        consolidated["total_token_count"] = int(existing.get("total_token_count", 0) or 0)

    prompt = _extract(incoming, ("prompt_token_count", "prompt_tokens", "input_token_count", "input_tokens"))
    completion = _extract(
        incoming,
        (
            "completion_token_count",
            "completion_tokens",
            "output_token_count",
            "output_tokens",
            "candidates_token_count",
            "candidate_token_count",
        ),
    )
    total = _extract(incoming, ("total_token_count", "total_tokens"))

    # Use max-by-field to preserve non-zero values without double counting.
    consolidated["prompt_token_count"] = max(consolidated["prompt_token_count"], prompt)
    consolidated["completion_token_count"] = max(consolidated["completion_token_count"], completion)

    derived_total = consolidated["prompt_token_count"] + consolidated["completion_token_count"]
    consolidated["total_token_count"] = max(consolidated["total_token_count"], total, derived_total)

    return consolidated


def log_terminal_event(
    *,
    job_id: str,
    company_name: str,
    account_id: str,
    start_perf: float,
    usage_metadata: Any,
    status: str,
    app_name: str,
    max_schema_retries: int,
    error_message: str | None = None,
    pipeline_stage: str = "full_pipeline",
    retry_count: int = 0,
    session_id: str | None = None,
) -> None:
    log_execution_event(
        job_id=job_id,
        company_name=company_name,
        account_id=account_id,
        latency_ms=latency_ms(start_perf),
        usage_metadata=usage_metadata,
        status=status,
        error_message=error_message,
        pipeline_stage=pipeline_stage,
        retry_count=retry_count,
        max_retries=max_schema_retries,
        session_id=session_id,
        app_name=app_name,
    )


def log_and_return_error(
    *,
    job_id: str,
    company_name: str,
    account_id: str,
    start_perf: float,
    usage_metadata: Any,
    message: str,
    code: str,
    stage: str,
    retryable: bool,
    session_id: str,
    retry_count: int,
    app_name: str,
    max_schema_retries: int,
    details: Any | None = None,
    status: str = "error",
) -> Dict[str, Any]:
    log_terminal_event(
        job_id=job_id,
        company_name=company_name,
        account_id=account_id,
        start_perf=start_perf,
        usage_metadata=usage_metadata,
        status=status,
        app_name=app_name,
        max_schema_retries=max_schema_retries,
        error_message=message,
        pipeline_stage=stage,
        retry_count=retry_count,
        session_id=session_id,
    )
    return build_terminal_response(
        status,
        company_name,
        message,
        code=code,
        stage=stage,
        retryable=retryable,
        details=details,
    )


def _safe_dump(value: Any) -> str:
    try:
        return json.dumps(value, default=str)
    except Exception:
        return str(value)


def _clip(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}...<truncated {len(text) - max_chars} chars>"


def trace_workflow_event(event: Any) -> None:
    """Best-effort event tracing for input/output visibility across workflow nodes."""
    if not DEBUG_NODE_IO:
        return

    event_stage = (
        getattr(event, "author", None)
        or getattr(event, "node_name", None)
        or getattr(event, "stage", None)
        or "unknown_stage"
    )
    event_input = getattr(event, "input", None)
    event_output = getattr(event, "output", None)

    input_text = _clip(_safe_dump(event_input), DEBUG_NODE_IO_MAX_CHARS) if event_input is not None else "<none>"
    output_text = _clip(_safe_dump(event_output), DEBUG_NODE_IO_MAX_CHARS) if event_output is not None else "<none>"

    print(f"[Workflow Trace] stage={event_stage} input={input_text} output={output_text}")

    if DEBUG_USAGE_METADATA:
        usage = getattr(event, "usage_metadata", None)
        usage_text = _clip(_safe_dump(usage), DEBUG_NODE_IO_MAX_CHARS) if usage is not None else "<none>"
        print(f"[Workflow Usage] stage={event_stage} usage_metadata={usage_text}")