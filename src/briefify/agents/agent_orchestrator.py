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
) -> None:
    log_execution_event(
        job_id=job_id,
        company_name=company_name,
        account_id=account_id,
        latency_ms=_latency_ms(start_perf),
        usage_metadata=usage_metadata,
        status=status,
        error_message=error_message,
    )


def _is_schema_validation_error(message: str) -> bool:
    lowered = message.lower()
    return "validation" in lowered or "schema" in lowered


def _build_terminal_response(status: str, company_name: str, message: str) -> Dict[str, Any]:
    return {
        "status": status,
        "company_name": company_name,
        "message": message,
    }


async def run_agentic_workflow_async(company_name: str, account_id: str = "ACC-1001", job_id: str = "manual_run") -> Dict[str, Any]:
    """Orchestrates multi-agent execution using Google ADK Runner and Workflow graph."""
    # Optional delay to smooth bursty webhook traffic.
    if RATE_DELAY_SEC > 0:
        await asyncio.sleep(RATE_DELAY_SEC)

    print(f"\n[Pipeline Triggered] Processing Account: {company_name}")
    start_time = time.time()
    start_perf = time.perf_counter()
    session_id = f"session_{account_id}_{int(start_time)}"

    runner = Runner(
        node=pipeline,
        app_name=APP_NAME,
        session_service=session_service,
        auto_create_session=True
    )

    trigger_payload = AccountTrigger(account_id=account_id, company_name=company_name)
    message = gtypes.Content(
        role="user",
        parts=[gtypes.Part(text=trigger_payload.model_dump_json())]
    )
    
    schema_retry_count = 0

    while True:
        # Stream ADK execution through Directed Graph, collecting token usage from events
        final_output = {}
        terminal_error: str | None = None
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
                if isinstance(out, dict):
                    out_status = out.get("status")
                    if out_status == "published":
                        final_output = out
                    elif out_status == "refused":
                        terminal_error = out.get("message") or "Model refused to generate output"
                        _log_terminal_event(
                            job_id=job_id,
                            company_name=company_name,
                            account_id=account_id,
                            start_perf=start_perf,
                            usage_metadata=usage_metadata,
                            status="refused",
                            error_message=terminal_error
                        )
                        return _build_terminal_response("refused", company_name, terminal_error)
                    elif out_status == "error":
                        terminal_error = out.get("message") or "Workflow node emitted an error status"
        except Exception as exc:
            error_message = f"Runner execution failed: {str(exc)}"
            _log_terminal_event(
                job_id=job_id,
                company_name=company_name,
                account_id=account_id,
                start_perf=start_perf,
                usage_metadata=usage_metadata,
                status="error",
                error_message=error_message
            )
            return _build_terminal_response("error", company_name, f"Workflow execution failed: {str(exc)}")

        if final_output:
            try:
                brief_data = final_output.get("brief_data")
                SalesBriefSchema.model_validate(brief_data)
            except Exception as exc:
                terminal_error = f"Publisher validation failed: {str(exc)}"
            else:
                _log_terminal_event(
                    job_id=job_id,
                    company_name=company_name,
                    account_id=account_id,
                    start_perf=start_perf,
                    usage_metadata=usage_metadata,
                    status="success"
                )
                return final_output

        if terminal_error:
            is_schema_invalid = _is_schema_validation_error(terminal_error)
            if is_schema_invalid and schema_retry_count < MAX_SCHEMA_RETRIES:
                schema_retry_count += 1
                await asyncio.sleep(SCHEMA_RETRY_DELAY_SEC * schema_retry_count)
                continue

            _log_terminal_event(
                job_id=job_id,
                company_name=company_name,
                account_id=account_id,
                start_perf=start_perf,
                usage_metadata=usage_metadata,
                status="error",
                error_message=terminal_error
            )
            return _build_terminal_response("error", company_name, terminal_error)

        _log_terminal_event(
            job_id=job_id,
            company_name=company_name,
            account_id=account_id,
            start_perf=start_perf,
            usage_metadata=usage_metadata,
            status="error",
            error_message="Pipeline terminated without generating output"
        )
        return {"status": "error", "message": "Pipeline execution failed"}


if __name__ == "__main__":
    acme_output = asyncio.run(run_agentic_workflow_async("Acme Corp"))
    print(acme_output.get("published_location"))
    print("\n" + "=" * 80 + "\n")

    beta_output = asyncio.run(run_agentic_workflow_async("Beta Logistics"))
    print(beta_output.get("published_location"))