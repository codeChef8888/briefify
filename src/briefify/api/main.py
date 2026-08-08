import os
from pathlib import Path
from typing import Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from briefify.agents.agent_orchestrator import run_agentic_workflow

app = FastAPI(
    title="Briefify Agentic AI Engine",
    description="Webhook listener triggering BigQuery telemetry extraction and Gemini strategic sales briefs.",
    version="1.0.0"
)

# Output directory for published strategic briefs
OUTPUT_DIR = Path("output/briefs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


class CRMEventPayload(BaseModel):
    event_type: str = Field(..., example="account.status_changed")
    company_name: str = Field(..., example="Acme Corp")
    status: str = Field(..., example="Qualified")
    account_id: str = Field(default="UNKNOWN", example="ACC-1001")


def publish_brief_artifact(company_name: str, brief_content: str) -> str:
    """Publishing Step: Writes the generated brief to the local knowledge repository."""
    sanitized_name = company_name.lower().replace(" ", "_")
    file_path = OUTPUT_DIR / f"{sanitized_name}_brief.md"
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(brief_content)
        
    return str(file_path.absolute())


@app.get("/health")
def health_check() -> Dict[str, str]:
    """Health check endpoint to verify server status."""
    return {"status": "healthy", "service": "Briefify Agentic Engine"}


@app.post("/webhook/crm-event")
def handle_crm_event(payload: CRMEventPayload) -> Dict[str, Any]:
    """Listens for Salesforce CRM status changes and triggers the multi-agent pipeline when 'Qualified'."""
    if payload.status.lower() != "qualified":
        return {
            "status": "ignored",
            "message": f"Account '{payload.company_name}' is in '{payload.status}' state. Pipeline triggers only for 'Qualified'."
        }

    # Execute the agentic workflow
    result = run_agentic_workflow(payload.company_name)

    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("brief"))

    # Execute publishing step
    artifact_path = publish_brief_artifact(payload.company_name, result["brief"])

    return {
        "status": "success",
        "company_name": payload.company_name,
        "trigger_event": payload.event_type,
        "brief_artifact_published": artifact_path,
        "brief_preview": result["brief"][:300] + "..."
    }