import os
from typing import Any, Dict

from fastapi import FastAPI, BackgroundTasks, status, Request
from briefify.api.models import CRMEventPayload
from briefify.api.repository import JOB_REPOSITORY
from briefify.api.responses import payload_too_large_response
from briefify.api.service import get_job_status_or_404, queue_crm_event

app = FastAPI(title="Briefify Agentic AI Webhook Engine", 
              description="Webhook listener triggering BigQuery telemetry extraction and Gemini strategic sales briefs.",
              version="2.0.0")

MAX_WEBHOOK_PAYLOAD_BYTES = int(os.getenv("MAX_WEBHOOK_PAYLOAD_BYTES", "16384"))


@app.middleware("http")
async def enforce_payload_size_limit(request: Request, call_next):
    """Reject oversized webhook payloads early to bound memory and parse costs."""
    if request.method == "POST" and request.url.path == "/webhook/crm-event":
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_WEBHOOK_PAYLOAD_BYTES:
            return payload_too_large_response()

        body = await request.body()
        if len(body) > MAX_WEBHOOK_PAYLOAD_BYTES:
            return payload_too_large_response()

    return await call_next(request)

@app.get("/health")
def health_check() -> Dict[str, str]:
    """Health check endpoint to verify server status."""
    return {"status": "healthy", "service": "Briefify Agentic Engine"}

@app.post("/webhook/crm-event", status_code=status.HTTP_202_ACCEPTED)
def handle_crm_event(payload: CRMEventPayload, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Listens for Salesforce CRM status changes, receives CRM webhook triggers, responds immediately with 202 Accepted, and queues the agent pipeline."""
    return queue_crm_event(JOB_REPOSITORY, payload, background_tasks)


@app.get("/jobs/{job_id}")
def get_job_status(job_id: str) -> Dict[str, Any]:
    """Polls the status of an asynchronous briefing job."""
    return get_job_status_or_404(JOB_REPOSITORY, job_id)