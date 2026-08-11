import os
import time 
import asyncio
from typing import Dict, Any

from google.genai import types as gtypes
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import Workflow
from google.adk.workflow import START

from briefify.schemas.brief_schema import SalesBriefSchema, AccountTrigger
from briefify.nodes.telemetry_node import query_account_usage
from briefify.nodes.publisher_node import publish_brief_node
from briefify.telemetry.ledger import log_execution_event

MODEL_NAME = os.getenv("ADK_MODEL", "gemini-3.5-flash")
RATE_DELAY_SEC = float(os.getenv("WORKFLOW_RATE_DELAY_SEC", "0"))

STRATEGIST_INSTRUCTION = """You are a Senior Strategic Sales Executive at an Enterprise AI company.
Synthesize software telemetry into an executive brief payload strictly following the SalesBriefSchema JSON structure.

CRITICAL GROUNDING RULES:
1. You MUST directly leverage the pre-computed quantitative metrics inside `engineered_features` 
   (`saturation_index_S_t`, `mau_delta_ΔU_6m`, `api_growth_ΔA_12m`, and `heuristic_signal`).
2. Do not recalculate these values manually.
3. Designate `primary_signal` strictly as one of the following exact strings:
   - "🟢 UPSELL OPPORTUNITY" (If seat utilization > 90%, high API growth, low ticket volume)
   - "🔴 CHURN / ENGAGEMENT RISK" (If MAU dropping, low feature adoption, or support ticket spikes)
   - "🟡 UNTAPPED CAPACITY" (If under-utilizing allocated seats)
4. Ensure all fields in SalesBriefSchema are fully populated. 
"""

# Node 2: Strategist Agent - LLM that synthesizes telemetry into a structured SalesBriefSchema (1 LLM Call)
strategist_agent = Agent(
    name="StrategistAgent",
    model=MODEL_NAME,
    instruction=STRATEGIST_INSTRUCTION,
    output_schema=SalesBriefSchema,  # Forces Gemini to generate JSON matching SalesBriefSchema
    output_key="brief_output"
)

# Static Graph Assembly: Fetch -> Reason -> Publish
pipeline = Workflow(
    name="sales_brief_workflow",
    description="Atomic Event-Driven Sales Brief Pipeline",
    edges=[(START, query_account_usage, strategist_agent, publish_brief_node)]
)

# 3. Setup Session Management & Execution Runner
session_service = InMemorySessionService()


async def run_agentic_workflow_async(company_name: str, account_id: str = "ACC-1001", job_id: str = "manual_run") -> Dict[str, Any]:
    """Orchestrates multi-agent execution using Google ADK Runner and Workflow graph."""
    # Optional delay to smooth bursty webhook traffic.
    if RATE_DELAY_SEC > 0:
        await asyncio.sleep(RATE_DELAY_SEC)
    
    print(f"\n[Pipeline Triggered] Processing Account: {company_name}")
    start_time = time.time()
    
    app_name = "briefify_sales_brief"
    user_id = "sales_rep"
    session_id = f"session_{account_id}_{int(start_time)}"


    runner = Runner(
        node=pipeline,
        app_name=app_name,
        session_service=session_service,
        auto_create_session=True
    )

    trigger_payload = AccountTrigger(account_id=account_id, company_name=company_name)
    message = gtypes.Content(
        role="user",
        parts=[gtypes.Part(text=trigger_payload.model_dump_json())]
    )
    
    # Stream ADK execution through Directed Graph, collecting token usage from events
    final_output = {}
    usage_metadata = None
    
    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=message
        ):
            if hasattr(event, "usage_metadata") and event.usage_metadata:
                usage_metadata = event.usage_metadata
                
            # Capture terminal output event from publish_brief_node
            out = getattr(event, "output", None)
            if isinstance(out, dict) and out.get("status") == "published":
                final_output = out
    except Exception as exc:
        latency_ms = (time.time() - start_time) * 1000
        log_execution_event(
            job_id=job_id,
            company_name=company_name,
            account_id=account_id,
            latency_ms=latency_ms,
            usage_metadata=usage_metadata,
            status="error",
            error_message=f"Runner execution failed: {str(exc)}"
        )
        return {
            "status": "error",
            "company_name": company_name,
            "message": f"Workflow execution failed: {str(exc)}"
        }

    latency_ms = (time.time() - start_time) * 1000

    if final_output:
        log_execution_event(
            job_id=job_id,
            company_name=company_name,
            account_id=account_id,
            latency_ms=latency_ms,
            usage_metadata=usage_metadata,
            status="success"
        )
        return final_output
    else:
        log_execution_event(
            job_id=job_id,
            company_name=company_name,
            account_id=account_id,
            latency_ms=latency_ms,
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