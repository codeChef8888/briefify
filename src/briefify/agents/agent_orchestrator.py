import time 
import asyncio
from typing import Dict, Any

from google.genai import types
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import Workflow

from briefify.mcp.telemetry_mcp import query_account_usage
from briefify.schemas.brief_schema import SalesBriefSchema
from briefify.publishers.publisher import LocalCMSPublisher
from briefify.telemetry.ledger import log_execution_event


def fetch_telemetry_tool(company_name: str) -> str:
    """Extracts historical software telemetry for a company from BigQuery.

    Args:
        company_name: Target company name (e.g., 'Acme Corp', 'Beta Logistics').

    Returns:
        JSON string with active users, seats, API calls, support tickets, and tier.
    """
    
    result = query_account_usage(company_name=company_name)
    
    time.sleep(4)
    
    return result


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

# 1. Instantiate Specialized Agents (Using Gemini 3.5 Flash)
data_agent = LlmAgent(
    name="DataAgent",
    model="gemini-3.5-flash", 
    instruction=(
            "Call fetch_telemetry_tool for the target company name provided in the user prompt. "
            "Return the exact, unmodified JSON string output from the tool. "
            "Do not summarize, alter, or omit any fields, ensuring 'engineered_features' "
            "and 'telemetry' are preserved completely in the output state."
        ),
    tools=[fetch_telemetry_tool],
    output_key="telemetry_raw"
)

strategist_agent = LlmAgent(
    name="StrategistAgent",
    model="gemini-3.5-flash",  
    instruction=STRATEGIST_INSTRUCTION,
    output_schema=SalesBriefSchema,  # Forces Gemini to generate JSON matching SalesBriefSchema
    output_key="brief_output"
)

# 2. Define Graph Workflow (Directed Node Edges)
pipeline = Workflow(
    name="SequentialPipeline",
    nodes=[data_agent, strategist_agent],
    edges=[
        ("START", data_agent),
        (data_agent, strategist_agent)
    ]
)

# 3. Setup Session Management & Execution Runner
session_service = InMemorySessionService()
runner = Runner(
    agent=pipeline,
    app_name="briefify_sales_brief",
    session_service=session_service,
    auto_create_session=True
)


async def run_agentic_workflow_async(company_name: str, account_id: str = "ACC-1001", job_id: str = "manual_run") -> Dict[str, Any]:
    """Orchestrates multi-agent execution using Google ADK Runner and Workflow graph."""
    # Prevent back-to-back webhook rate bursts
    await asyncio.sleep(4)
    
    print(f"\n[Pipeline Triggered] Processing Account: {company_name}")
    start_time = time.time()
    
    app_name = "briefify_sales_brief"
    user_id = "sales_rep"
    session_id = f"session_{account_id}_{int(start_time)}"

    print(" └── Executing ADK Graph Workflow (DataAgent -> StrategistAgent)...")
    prompt_content = types.Content(
        role="user",
        parts=[types.Part(text=f"Analyze sales brief telemetry for account: {company_name}")]
    )
    
    # Stream ADK execution through Directed Graph
    async for _ in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=prompt_content
    ):
        pass

    # Retrieve output state from the auto-created session
    session = await session_service.get_session(
        app_name=app_name,
        user_id=user_id,
        session_id=session_id
    )
    print(f" └── Session '{session_id}' completed. Extracting outputs...")
    brief_raw = session.state.get("brief_output", "")
    
    try:
        # Check type before validating with Pydantic
        if isinstance(brief_raw, SalesBriefSchema):
            validated_brief = brief_raw
        elif isinstance(brief_raw, dict):
            validated_brief = SalesBriefSchema.model_validate(brief_raw)
        elif isinstance(brief_raw, str):
            clean_json = brief_raw.strip()
            if clean_json.startswith("```"):
                clean_json = clean_json.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            validated_brief = SalesBriefSchema.model_validate_json(clean_json)
        else:
            raise ValueError(f"Unsupported output type in session state: {type(brief_raw)}")
    except Exception as e:
        print(f" ❌ [Pipeline Failed] Schema validation error: {e}")
        print(f" 🔍 [Raw LLM Output]: {brief_raw}")
        return {
            "status": "error",
            "company_name": company_name,
            "brief": f"Schema validation failed: {str(e)}. Raw output: {brief_raw}"
        }

    # Publish output via Publisher Adapter
    publisher = LocalCMSPublisher()
    artifact_location = publisher.publish(account_id, validated_brief)
    
    latency_ms = (time.time() - start_time) * 1000

    # Write FinOps Telemetry Log Entry
    log_execution_event(
        job_id=job_id,
        company_name=company_name,
        account_id=account_id,
        latency_ms=latency_ms,
        usage_metadata=None,
        status="success"
    )
    
    print(" [Pipeline Complete] Strategic brief generated successfully.\n")
    return {
        "status": "success",
        "company_name": company_name,
        "brief": brief_raw,
        "published_location": artifact_location,
        "data": validated_brief.model_dump()
    }


if __name__ == "__main__":
    acme_output = asyncio.run(run_agentic_workflow_async("Acme Corp"))
    print(acme_output.get("published_location"))
    print("\n" + "=" * 80 + "\n")

    beta_output = asyncio.run(run_agentic_workflow_async("Beta Logistics"))
    print(beta_output.get("published_location"))