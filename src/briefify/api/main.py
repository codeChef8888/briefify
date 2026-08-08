import time
import uuid
from pathlib import Path
from typing import Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, status
from pydantic import BaseModel, Field

from briefify.agents.agent_orchestrator import run_agentic_workflow

app = FastAPI(title="Briefify Agentic AI Webhook Engine", 
              description="Webhook listener triggering BigQuery telemetry extraction and Gemini strategic sales briefs.",
              version="2.0.0")

# In-memory job state ledger (Can be swapped with Redis in multi-worker production)
JOB_LEDGER: Dict[str, Dict[str, Any]] = {}

class CRMEventPayload(BaseModel):
    event_type: str = Field(..., example="account.status_changed")
    company_name: str = Field(..., example="Acme Corp")
    status: str = Field(..., example="Qualified")
    account_id: str = Field(default="ACC-UNKNOWN", example="ACC-1001")

@app.get("/health")
def health_check() -> Dict[str, str]:
    """Health check endpoint to verify server status."""
    return {"status": "healthy", "service": "Briefify Agentic Engine"}


def async_agent_task(job_id: str, company_name: str, account_id: str):
    """Background worker executing BigQuery extraction, Gemini synthesis, and publishing."""
    JOB_LEDGER[job_id]["status"] = "processing"
    JOB_LEDGER[job_id]["started_at"] = time.time()

    result = run_agentic_workflow(company_name)

    if result.get("status") == "error":
        JOB_LEDGER[job_id]["status"] = "failed"
        JOB_LEDGER[job_id]["error"] = result.get("brief")
    else:
        JOB_LEDGER[job_id]["status"] = "completed"
        JOB_LEDGER[job_id]["completed_at"] = time.time()
        JOB_LEDGER[job_id]["execution_time_sec"] = round(time.time() - JOB_LEDGER[job_id]["started_at"], 2)
        JOB_LEDGER[job_id]["result"] = result


@app.post("/webhook/crm-event", status_code=status.HTTP_202_ACCEPTED)
def handle_crm_event(payload: CRMEventPayload, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Listens for Salesforce CRM status changes, receives CRM webhook triggers, responds immediately with 202 Accepted, and queues the agent pipeline."""
    if payload.status.lower() != "qualified":
        return {
            "status": "ignored",
            "message": f"Account '{payload.company_name}' status is '{payload.status}'. Pipeline requires 'Qualified'."
        }

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    
    JOB_LEDGER[job_id] = {
        "job_id": job_id,
        "company_name": payload.company_name,
        "account_id": payload.account_id,
        "status": "queued",
        "created_at": time.time()
    }

    # Decouple execution from HTTP request lifecycle
    background_tasks.add_task(async_agent_task, job_id, payload.company_name, payload.account_id)

    return {
        "status": "accepted",
        "job_id": job_id,
        "check_status_url": f"/jobs/{job_id}",
        "message": f"Agent workflow queued for account '{payload.company_name}'."
    }


@app.get("/jobs/{job_id}")
def get_job_status(job_id: str) -> Dict[str, Any]:
    """Polls the status of an asynchronous briefing job."""
    if job_id not in JOB_LEDGER:
        raise HTTPException(status_code=404, detail="Job ID not found.")
    return JOB_LEDGER[job_id]