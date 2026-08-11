import os
import asyncio
import time
import uuid
import json
import threading
from typing import Literal
from typing import Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, status, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict

from briefify.agents.agent_orchestrator import run_agentic_workflow_async
from briefify.schemas.error_contract import build_error

try:
    import redis
    from redis.exceptions import RedisError, WatchError
except Exception:  # pragma: no cover - keeps local dev functional without redis package
    redis = None

    class RedisError(Exception):
        pass

    class WatchError(Exception):
        pass

app = FastAPI(title="Briefify Agentic AI Webhook Engine", 
              description="Webhook listener triggering BigQuery telemetry extraction and Gemini strategic sales briefs.",
              version="2.0.0")

MAX_WEBHOOK_PAYLOAD_BYTES = int(os.getenv("MAX_WEBHOOK_PAYLOAD_BYTES", "16384"))
JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", "86400"))
IDEMPOTENCY_TTL_SECONDS = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "86400"))
REDIS_URL = os.getenv("REDIS_URL", "").strip()

# In-memory job state ledger (Can be swapped with Redis in multi-worker production)
JOB_LEDGER: Dict[str, Dict[str, Any]] = {}
EVENT_LEDGER: Dict[str, str] = {}


class JobRepository:
    """Persist job status and idempotency keys in Redis with memory fallback."""

    def __init__(self, redis_url: str, job_ttl: int, idempotency_ttl: int):
        self.job_ttl = job_ttl
        self.idempotency_ttl = idempotency_ttl
        self._lock = threading.Lock()
        self.client = None

        if redis and redis_url:
            try:
                candidate = redis.Redis.from_url(redis_url, decode_responses=True)
                candidate.ping()
                self.client = candidate
            except RedisError:
                self.client = None

    @staticmethod
    def _job_key(job_id: str) -> str:
        return f"briefify:job:{job_id}"

    @staticmethod
    def _event_key(event_id: str) -> str:
        return f"briefify:event:{event_id}"

    def create_job(self, job_id: str, payload: Dict[str, Any]) -> None:
        if self.client:
            self.client.set(self._job_key(job_id), json.dumps(payload), ex=self.job_ttl)
            return
        with self._lock:
            JOB_LEDGER[job_id] = payload

    def get_job(self, job_id: str) -> Dict[str, Any] | None:
        if self.client:
            raw = self.client.get(self._job_key(job_id))
            if not raw:
                return None
            return json.loads(raw)
        return JOB_LEDGER.get(job_id)

    def update_job(self, job_id: str, updates: Dict[str, Any]) -> bool:
        if self.client:
            key = self._job_key(job_id)
            with self.client.pipeline() as pipe:
                for _ in range(3):
                    try:
                        pipe.watch(key)
                        raw = pipe.get(key)
                        if not raw:
                            pipe.unwatch()
                            return False
                        payload = json.loads(raw)
                        payload.update(updates)
                        pipe.multi()
                        pipe.set(key, json.dumps(payload), ex=self.job_ttl)
                        pipe.execute()
                        return True
                    except WatchError:
                        continue
            return False

        with self._lock:
            if job_id not in JOB_LEDGER:
                return False
            JOB_LEDGER[job_id].update(updates)
            return True

    def transition_status(self, job_id: str, from_statuses: set[str], to_status: str, updates: Dict[str, Any] | None = None) -> bool:
        if self.client:
            key = self._job_key(job_id)
            with self.client.pipeline() as pipe:
                for _ in range(3):
                    try:
                        pipe.watch(key)
                        raw = pipe.get(key)
                        if not raw:
                            pipe.unwatch()
                            return False
                        payload = json.loads(raw)
                        if payload.get("status") not in from_statuses:
                            pipe.unwatch()
                            return False
                        payload["status"] = to_status
                        if updates:
                            payload.update(updates)
                        pipe.multi()
                        pipe.set(key, json.dumps(payload), ex=self.job_ttl)
                        pipe.execute()
                        return True
                    except WatchError:
                        continue
            return False

        with self._lock:
            payload = JOB_LEDGER.get(job_id)
            if not payload or payload.get("status") not in from_statuses:
                return False
            payload["status"] = to_status
            if updates:
                payload.update(updates)
            return True

    def reserve_event(self, event_id: str, job_id: str) -> tuple[bool, str | None]:
        if self.client:
            event_key = self._event_key(event_id)
            accepted = self.client.set(event_key, job_id, nx=True, ex=self.idempotency_ttl)
            if accepted:
                return True, None
            return False, self.client.get(event_key)

        with self._lock:
            existing = EVENT_LEDGER.get(event_id)
            if existing:
                return False, existing
            EVENT_LEDGER[event_id] = job_id
            return True, None

    def get_job_id_for_event(self, event_id: str) -> str | None:
        if self.client:
            return self.client.get(self._event_key(event_id))
        return EVENT_LEDGER.get(event_id)


JOB_REPOSITORY = JobRepository(
    redis_url=REDIS_URL,
    job_ttl=JOB_TTL_SECONDS,
    idempotency_ttl=IDEMPOTENCY_TTL_SECONDS,
)

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
    event_id: str = Field(
        ...,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
        example="evt_20260812_0001",
    )


@app.middleware("http")
async def enforce_payload_size_limit(request: Request, call_next):
    """Reject oversized webhook payloads early to bound memory and parse costs."""
    if request.method == "POST" and request.url.path == "/webhook/crm-event":
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_WEBHOOK_PAYLOAD_BYTES:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content=build_error(
                    code="PAYLOAD_TOO_LARGE",
                    message="Webhook payload exceeds allowed size",
                    stage="api_webhook",
                    retryable=False,
                ),
            )

        body = await request.body()
        if len(body) > MAX_WEBHOOK_PAYLOAD_BYTES:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content=build_error(
                    code="PAYLOAD_TOO_LARGE",
                    message="Webhook payload exceeds allowed size",
                    stage="api_webhook",
                    retryable=False,
                ),
            )

    return await call_next(request)

@app.get("/health")
def health_check() -> Dict[str, str]:
    """Health check endpoint to verify server status."""
    return {"status": "healthy", "service": "Briefify Agentic Engine"}

def run_agent_task_background(job_id: str, company_name: str, account_id: str):
    """Background worker executing the async workflow in a threadpool task.

    Using a sync wrapper keeps long blocking calls (BigQuery/SDK internals) off
    the main event loop so `/jobs/{job_id}` polling remains responsive.
    """
    if not JOB_REPOSITORY.get_job(job_id):
        return

    started_at = time.time()
    status_changed = JOB_REPOSITORY.transition_status(
        job_id,
        from_statuses={"queued"},
        to_status="processing",
        updates={"started_at": started_at},
    )
    if not status_changed:
        return

    try:
        result = asyncio.run(
            run_agentic_workflow_async(company_name, job_id=job_id, account_id=account_id)
        )

        if result.get("status") == "error":
            JOB_REPOSITORY.update_job(
                job_id,
                {
                    "status": "failed",
                    "error": result.get("message") or "Unknown workflow failure",
                    "result": result,
                },
            )
        else:
            JOB_REPOSITORY.update_job(
                job_id,
                {
                    "status": "completed",
                    "result": result,
                },
            )
    except Exception as exc:
        JOB_REPOSITORY.update_job(
            job_id,
            {
                "status": "failed",
                "error": f"Unhandled background task failure: {str(exc)}",
                "result": build_error(
                    code="BACKGROUND_TASK_FAILED",
                    message=f"Unhandled background task failure: {str(exc)}",
                    stage="api_worker",
                    retryable=False,
                ),
            },
        )
    finally:
        completed_at = time.time()
        JOB_REPOSITORY.update_job(
            job_id,
            {
                "completed_at": completed_at,
                "execution_time_sec": round(completed_at - started_at, 2),
            },
        )

@app.post("/webhook/crm-event", status_code=status.HTTP_202_ACCEPTED)
def handle_crm_event(payload: CRMEventPayload, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Listens for Salesforce CRM status changes, receives CRM webhook triggers, responds immediately with 202 Accepted, and queues the agent pipeline."""
    existing_job_id = JOB_REPOSITORY.get_job_id_for_event(payload.event_id)
    if existing_job_id:
        existing_job = JOB_REPOSITORY.get_job(existing_job_id)
        return {
            "status": "duplicate",
            "message": f"Duplicate webhook event '{payload.event_id}' detected.",
            "job_id": existing_job_id,
            "check_status_url": f"/jobs/{existing_job_id}",
            "job_status": existing_job.get("status") if existing_job else "unknown",
        }

    if payload.status.lower() != "qualified":
        return {
            "status": "ignored",
            "message": f"Account '{payload.company_name}' status is '{payload.status}'. Pipeline requires 'Qualified'."
        }

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    
    reserved, existing_job_id = JOB_REPOSITORY.reserve_event(payload.event_id, job_id)
    if not reserved:
        duplicate_job_id = existing_job_id or "unknown"
        duplicate_job = JOB_REPOSITORY.get_job(duplicate_job_id) if existing_job_id else None
        return {
            "status": "duplicate",
            "message": f"Duplicate webhook event '{payload.event_id}' detected.",
            "job_id": duplicate_job_id,
            "check_status_url": f"/jobs/{duplicate_job_id}",
            "job_status": duplicate_job.get("status") if duplicate_job else "unknown",
        }

    JOB_REPOSITORY.create_job(job_id, {
        "job_id": job_id,
        "event_id": payload.event_id,
        "company_name": payload.company_name,
        "account_id": payload.account_id,
        "status": "queued",
        "created_at": time.time()
    })

    # Decouple execution from HTTP request lifecycle
    background_tasks.add_task(run_agent_task_background, job_id, payload.company_name, payload.account_id)

    return {
        "status": "accepted",
        "job_id": job_id,
        "check_status_url": f"/jobs/{job_id}",
        "message": f"Agent workflow queued for account '{payload.company_name}'."
    }


@app.get("/jobs/{job_id}")
def get_job_status(job_id: str) -> Dict[str, Any]:
    """Polls the status of an asynchronous briefing job."""
    job = JOB_REPOSITORY.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job ID not found.")
    return job