import os
import time
import uuid
from typing import Literal
from typing import Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, status, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict

from briefify.agents.agent_orchestrator import run_agentic_workflow_async

app = FastAPI(title="Briefify Agentic AI Webhook Engine", 
              description="Webhook listener triggering BigQuery telemetry extraction and Gemini strategic sales briefs.",
              version="2.0.0")

MAX_WEBHOOK_PAYLOAD_BYTES = int(os.getenv("MAX_WEBHOOK_PAYLOAD_BYTES", "16384"))

# In-memory job state ledger (Can be swapped with Redis in multi-worker production)
JOB_LEDGER: Dict[str, Dict[str, Any]] = {}

class CRMEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    event_type: str = Field(
        ...,
        min_length=3,
        max_length=64,
        pattern=r"^[a-zA-Z0-9._-]+$",
        example="account.status_changed",
    )
    company_name: str = Field(..., min_length=2, max_length=120, example="Acme Corp")
    status: Literal["Qualified", "Prospect", "Negotiation"] = Field(..., example="Qualified")
    account_id: str = Field(
        default="ACC-UNKNOWN",
        min_length=4,
        max_length=40,
        pattern=r"^ACC-[A-Za-z0-9-]+$",
        example="ACC-1001",
    )


@app.middleware("http")
async def enforce_payload_size_limit(request: Request, call_next):
    """Reject oversized webhook payloads early to bound memory and parse costs."""
    if request.method == "POST" and request.url.path == "/webhook/crm-event":
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_WEBHOOK_PAYLOAD_BYTES:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={"status": "error", "message": "Webhook payload exceeds allowed size"},
            )

        body = await request.body()
        if len(body) > MAX_WEBHOOK_PAYLOAD_BYTES:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={"status": "error", "message": "Webhook payload exceeds allowed size"},
            )

    return await call_next(request)

@app.get("/health")
def health_check() -> Dict[str, str]:
    """Health check endpoint to verify server status."""
    return {"status": "healthy", "service": "Briefify Agentic Engine"}

async def async_agent_task(job_id: str, company_name: str, account_id: str):
    """Background worker executing BigQuery extraction, Gemini synthesis, and publishing."""
    if job_id not in JOB_LEDGER:
        return

    JOB_LEDGER[job_id]["status"] = "processing"
    JOB_LEDGER[job_id]["started_at"] = time.time()

    try:
        # Await the async pipeline directly without asyncio.run()
        result = await run_agentic_workflow_async(company_name, job_id=job_id, account_id=account_id)

        if result.get("status") == "error":
            JOB_LEDGER[job_id]["status"] = "failed"
            JOB_LEDGER[job_id]["error"] = result.get("message") or "Unknown workflow failure"
            JOB_LEDGER[job_id]["result"] = result
        else:
            JOB_LEDGER[job_id]["status"] = "completed"
            JOB_LEDGER[job_id]["result"] = result
    except Exception as exc:
        JOB_LEDGER[job_id]["status"] = "failed"
        JOB_LEDGER[job_id]["error"] = f"Unhandled background task failure: {str(exc)}"
    finally:
        JOB_LEDGER[job_id]["completed_at"] = time.time()
        JOB_LEDGER[job_id]["execution_time_sec"] = round(
            JOB_LEDGER[job_id]["completed_at"] - JOB_LEDGER[job_id]["started_at"], 2
        )

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