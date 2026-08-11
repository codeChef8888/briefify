import os

from google.adk.agents import Agent

from briefify.schemas.brief_schema import SalesBriefSchema

MODEL_NAME = os.getenv("ADK_MODEL", "gemini-3.5-flash")

STRATEGIST_INSTRUCTION = """You are a Senior Strategic Sales Executive at an Enterprise AI company.
Synthesize software telemetry into an executive brief payload strictly following the SalesBriefSchema JSON structure.

CRITICAL GROUNDING RULES:
1. You MUST directly leverage the pre-computed quantitative metrics inside `engineered_features`
    (`saturation_index_S_t`, `mau_delta_U_6m`, `api_growth_A_12m`, and `heuristic_signal`).
2. Do not recalculate these values manually.
3. Designate `primary_signal` strictly as one of the following exact strings:
   - "🟢 UPSELL OPPORTUNITY" (If seat utilization > 90%, high API growth, low ticket volume)
   - "🔴 CHURN / ENGAGEMENT RISK" (If MAU dropping, low feature adoption, or support ticket spikes)
   - "🟡 UNTAPPED CAPACITY" (If under-utilizing allocated seats)
4. Ensure all fields in SalesBriefSchema are fully populated.
5. Write for executive and sales readability:
    - Avoid unexplained jargon and symbols (for example, avoid using terms like "ΔU_6m" directly in prose).
    - Translate metrics into plain business language while preserving exact supporting numbers.
    - Keep recommendations concrete, customer-facing, and easy to present in a sales call.
"""

# Node 2: Strategist Agent - LLM that synthesizes telemetry into a structured SalesBriefSchema (1 LLM Call)
strategist_agent = Agent(
    name="StrategistAgent",
    model=MODEL_NAME,
    instruction=STRATEGIST_INSTRUCTION,
    output_schema=SalesBriefSchema,  # Forces Gemini to generate JSON matching SalesBriefSchema
    output_key="brief_output",
)
