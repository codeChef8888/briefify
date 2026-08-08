import os
import json
from typing import Dict, Any
from google import genai

# Import Phase 1 BigQuery tool via package-relative import
from briefify.mcp.telemetry_mcp import query_account_usage


def fetch_telemetry_tool(company_name: str) -> str:
    """Extracts 12-month historical software telemetry for a company from BigQuery.

    Args:
        company_name: Target company name (e.g., 'Acme Corp', 'Beta Logistics').

    Returns:
        JSON string with active users, seats, API calls, support tickets, and tier.
    """
    return query_account_usage(company_name)


STRATEGIST_INSTRUCTION = """You are a Senior Strategic Sales Executive at an Enterprise AI company.
Your goal is to synthesize 12-month software telemetry into an executive briefing for a sales rep
preparing for a call with a newly "Qualified" target account.

Format your response strictly using the following Markdown structure:

# 📊 Executive Strategic Brief: {Company Name}
**Contract Tier:** {Current Tier} | **Analysis Date:** {Current Date}

---

## 1. Executive Summary
Provide a 2-3 sentence overview of account health, capacity utilization, and key narrative drivers.

## 2. Telemetry Breakdown & Key Metrics
- **Seat Utilization:** {Average and Peak % over last 6 months}
- **API Call Volume Trend:** {Growth / Decline trajectory and technical stress indicators}
- **Support & Operational Health:** {Total critical support tickets in last 6 months}

## 3. Strategic Signal & Risk Assessment
Explicitly designate one primary status: 
- 🟢 **UPSELL OPPORTUNITY** (If seat utilization > 90%, high API growth, low ticket volume)
- 🔴 **CHURN / ENGAGEMENT RISK** (If MAU dropping, zero/low feature adoption, or support ticket spikes)
- 🟡 **UNTAPPED CAPACITY** (If under-utilizing allocated seats)

Summarize the evidence supporting this signal.

## 4. Actionable Next Steps for Sales Call
Provide 3 concrete, specific talking points or proposals for the account rep.
"""


def run_agentic_workflow(company_name: str) -> Dict[str, Any]:
    """Orchestrates sequential execution across BigQuery extraction and Gemini 3.5 Flash synthesis."""
    print(f"\n[Pipeline Triggered] Processing Account: {company_name}")
    
    # Step 1: Extract telemetry via BigQuery tool
    print(" └── Step 1: Data Agent retrieving BigQuery telemetry...")
    telemetry_json = fetch_telemetry_tool(company_name)
    
    try:
        telemetry_data = json.loads(telemetry_json)
        if telemetry_data.get("status") == "error":
            return {
                "status": "error",
                "company_name": company_name,
                "brief": f"Workflow failed: {telemetry_data.get('message')}"
            }
    except Exception as e:
        return {
            "status": "error",
            "company_name": company_name,
            "brief": f"JSON parsing failed: {str(e)}"
        }

    # Step 2: Synthesize strategic brief using Gemini 3.5 Flash
    print(" └── Step 2: Strategist Agent synthesizing sales brief with Gemini...")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set.")

    client = genai.Client(api_key=api_key)
    
    prompt = (
        f"{STRATEGIST_INSTRUCTION}\n\n"
        f"Target Account Telemetry Payload:\n{telemetry_json}"
    )
    
    response = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=prompt
    )

    print(" [Pipeline Complete] Strategic brief generated successfully.\n")
    return {
        "status": "success",
        "company_name": company_name,
        "brief": response.text
    }


if __name__ == "__main__":
    # Test Case 1: Acme Corp (Expansion Archetype)
    acme_output = run_agentic_workflow("Acme Corp")
    print(acme_output["brief"])
    print("\n" + "=" * 80 + "\n")

    # Test Case 2: Beta Logistics (Churn Risk Archetype)
    beta_output = run_agentic_workflow("Beta Logistics")
    print(beta_output["brief"])