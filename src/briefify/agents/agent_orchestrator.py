import os
import time
import asyncio
from typing import Any, Dict

from google.genai import types as gtypes
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import Workflow
from google.adk.workflow import START

from briefify.schemas.brief_schema import SalesBriefSchema, AccountTrigger
from briefify.schemas.error_contract import build_error
from briefify.nodes.telemetry_node import query_account_usage
from briefify.nodes.strategist_node import strategist_agent
from briefify.nodes.publisher_node import publish_brief_node
from briefify.telemetry.ledger import log_execution_event

RATE_DELAY_SEC = float(os.getenv("WORKFLOW_RATE_DELAY_SEC", "0"))
MAX_SCHEMA_RETRIES = int(os.getenv("WORKFLOW_MAX_SCHEMA_RETRIES", "2"))
SCHEMA_RETRY_DELAY_SEC = float(os.getenv("WORKFLOW_SCHEMA_RETRY_DELAY_SEC", "0.5"))
APP_NAME = "briefify_sales_brief"
USER_ID = "sales_rep"

# Static Graph Assembly: Fetch -> Reason -> Publish
pipeline = Workflow(
    name="sales_brief_workflow",
    description="Atomic Event-Driven Sales Brief Pipeline",
    edges=[(START, query_account_usage, strategist_agent, publish_brief_node)]
)

# 3. Setup Session Management & Execution Runner
session_service = InMemorySessionService()


TERMINAL_STATES = {"published", "refused", "error"}


def _latency_ms(start_perf: float) -> float:
    return (time.perf_counter() - start_perf) * 1000


def _log_terminal_event(
    *,
    job_id: str,
    company_name: str,
    account_id: str,
    start_perf: float,
    usage_metadata: Any,
    status: str,
    error_message: str | None = None,
    pipeline_stage: str = "full_pipeline",
    retry_count: int = 0,
    max_retries: int = MAX_SCHEMA_RETRIES,
    session_id: str | None = None,
) -> None:
    log_execution_event(
        job_id=job_id,
        company_name=company_name,
        account_id=account_id,
        latency_ms=_latency_ms(start_perf),
        usage_metadata=usage_metadata,
        status=status,
        error_message=error_message,
        pipeline_stage=pipeline_stage,
        retry_count=retry_count,
        max_retries=max_retries,
        session_id=session_id,
        app_name=APP_NAME,
    )


def _is_schema_validation_error(message: str) -> bool:
    lowered = message.lower()
    return "validation" in lowered or "schema" in lowered


def _build_terminal_response(
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


def _build_runner_message(account_id: str, company_name: str) -> gtypes.Content:
    trigger_payload = AccountTrigger(account_id=account_id, company_name=company_name)
    return gtypes.Content(
        role="user",
        parts=[gtypes.Part(text=trigger_payload.model_dump_json())],
    )


def _build_runner(session_id: str) -> Runner:
    return Runner(
        node=pipeline,
        app_name=APP_NAME,
        session_service=session_service,
        auto_create_session=True,
    )


def _log_and_return_error(
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
    details: Any | None = None,
    status: str = "error",
) -> Dict[str, Any]:
    _log_terminal_event(
        job_id=job_id,
        company_name=company_name,
        account_id=account_id,
        start_perf=start_perf,
        usage_metadata=usage_metadata,
        status=status,
        error_message=message,
        pipeline_stage=stage,
        retry_count=retry_count,
        session_id=session_id,
    )
    return _build_terminal_response(
        status,
        company_name,
        message,
        code=code,
        stage=stage,
        retryable=retryable,
        details=details,
    )


def _extract_terminal_output(out: dict) -> tuple[str, str, str, bool, Any | None]:
    out_status = out.get("status") or "error"
    out_message = out.get("message") or "Workflow node emitted an error status"
    out_code = out.get("code", "WORKFLOW_NODE_ERROR")
    out_stage = out.get("stage", "workflow_node")
    out_retryable = bool(out.get("retryable", False))
    out_details = out.get("details")
    return out_status, out_message, out_code, out_retryable, (out_stage, out_details)


async def run_agentic_workflow_async(company_name: str, account_id: str = "ACC-1001", job_id: str = "manual_run") -> Dict[str, Any]:
    """Orchestrates multi-agent execution using Google ADK Runner and Workflow graph."""
    # Optional delay to smooth bursty webhook traffic.
    if RATE_DELAY_SEC > 0:
        await asyncio.sleep(RATE_DELAY_SEC)

    print(f"\n[Pipeline Triggered] Processing Account: {company_name}")
    start_perf = time.perf_counter()
    session_id = f"session_{account_id}_{int(time.time())}"

    runner = _build_runner(session_id)
    message = _build_runner_message(account_id, company_name)
    
    schema_retry_count = 0

    while True:
        # Stream ADK execution through Directed Graph, collecting token usage from events
        final_output = {}
        terminal_error: str | None = None
        terminal_error_payload: Dict[str, Any] = {
            "code": "WORKFLOW_NODE_ERROR",
            "stage": "workflow_node",
            "retryable": False,
            "details": None,
        }
        usage_metadata = None

        try:
            async for event in runner.run_async(
                user_id=USER_ID,
                session_id=session_id,
                new_message=message
            ):
                if hasattr(event, "usage_metadata") and event.usage_metadata:
                    usage_metadata = event.usage_metadata

                out = getattr(event, "output", None)
                if isinstance(out, dict) and out.get("status") in TERMINAL_STATES:
                    out_status, out_message, out_code, out_retryable, out_context = _extract_terminal_output(out)
                    out_stage, out_details = out_context

                    if out_status == "published":
                        final_output = out
                    elif out_status == "refused":
                        return _log_and_return_error(
                            job_id=job_id,
                            company_name=company_name,
                            account_id=account_id,
                            start_perf=start_perf,
                            usage_metadata=usage_metadata,
                            message=out_message,
                            code=out_code,
                            stage=out_stage,
                            retryable=out_retryable,
                            session_id=session_id,
                            retry_count=schema_retry_count,
                            details=out_details,
                            status="refused",
                        )
                    elif out_status == "error":
                        terminal_error = out_message
                        terminal_error_payload = {
                            "code": out_code,
                            "stage": out_stage,
                            "retryable": out_retryable,
                            "details": out_details,
                        }
        except Exception as exc:
            return _log_and_return_error(
                job_id=job_id,
                company_name=company_name,
                account_id=account_id,
                start_perf=start_perf,
                usage_metadata=usage_metadata,
                message=f"Workflow execution failed: {str(exc)}",
                code="RUNNER_EXECUTION_FAILED",
                stage="agent_orchestrator",
                retryable=True,
                session_id=session_id,
                retry_count=schema_retry_count,
            )

        if final_output:
            try:
                brief_data = final_output.get("brief_data")
                SalesBriefSchema.model_validate(brief_data)
            except Exception as exc:
                terminal_error = f"Publisher validation failed: {str(exc)}"
                terminal_error_payload = {
                    "code": "PUBLISHER_VALIDATION_FAILED",
                    "stage": "publisher_node",
                    "retryable": False,
                    "details": None,
                }
            else:
                _log_terminal_event(
                    job_id=job_id,
                    company_name=company_name,
                    account_id=account_id,
                    start_perf=start_perf,
                    usage_metadata=usage_metadata,
                    status="success",
                    pipeline_stage="publish_brief_node",
                    retry_count=schema_retry_count,
                    session_id=session_id,
                )
                return final_output

        if terminal_error:
            is_schema_invalid = _is_schema_validation_error(terminal_error)
            if is_schema_invalid and schema_retry_count < MAX_SCHEMA_RETRIES:
                schema_retry_count += 1
                await asyncio.sleep(SCHEMA_RETRY_DELAY_SEC * schema_retry_count)
                continue

            return _log_and_return_error(
                job_id=job_id,
                company_name=company_name,
                account_id=account_id,
                start_perf=start_perf,
                usage_metadata=usage_metadata,
                message=terminal_error,
                code=terminal_error_payload.get("code", "WORKFLOW_NODE_ERROR"),
                stage=terminal_error_payload.get("stage", "workflow_node"),
                retryable=bool(terminal_error_payload.get("retryable", False)),
                session_id=session_id,
                retry_count=schema_retry_count,
                details=terminal_error_payload.get("details"),
            )

        return _log_and_return_error(
            job_id=job_id,
            company_name=company_name,
            account_id=account_id,
            start_perf=start_perf,
            usage_metadata=usage_metadata,
            message="Pipeline execution failed",
            code="PIPELINE_EMPTY_OUTPUT",
            stage="agent_orchestrator",
            retryable=True,
            session_id=session_id,
            retry_count=schema_retry_count,
        )


if __name__ == "__main__":
    acme_output = asyncio.run(run_agentic_workflow_async("Acme Corp"))
    print(acme_output.get("published_location"))
    print("\n" + "=" * 80 + "\n")

    beta_output = asyncio.run(run_agentic_workflow_async("Beta Logistics"))
    print(beta_output.get("published_location"))