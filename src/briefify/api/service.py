import asyncio
import time
import uuid
from typing import Any, Dict

from fastapi import BackgroundTasks, HTTPException

from briefify.agents.agent_orchestrator import run_agentic_workflow_async
from briefify.api.models import CRMEventPayload
from briefify.api.repository import JobRepository
from briefify.api.responses import (
    accepted_event_response,
    duplicate_event_response,
    ignored_event_response,
)
from briefify.schemas.error_contract import build_error


def _initial_job_record(job_id: str, payload: CRMEventPayload) -> Dict[str, Any]:
    return {
        "job_id": job_id,
        "event_id": payload.event_id,
        "company_name": payload.company_name,
        "account_id": payload.account_id,
        "status": "queued",
        "created_at": time.time(),
    }


def _finalize_job(repository: JobRepository, job_id: str, started_at: float) -> None:
    completed_at = time.time()
    repository.update_job(
        job_id,
        {
            "completed_at": completed_at,
            "execution_time_sec": round(completed_at - started_at, 2),
        },
    )


def run_agent_task_background(repository: JobRepository, job_id: str, company_name: str, account_id: str) -> None:
    """Background worker executing the async workflow in a threadpool task."""
    if not repository.get_job(job_id):
        return

    started_at = time.time()
    if not repository.transition_status(
        job_id,
        from_statuses={"queued"},
        to_status="processing",
        updates={"started_at": started_at},
    ):
        return

    try:
        result = asyncio.run(
            run_agentic_workflow_async(company_name, job_id=job_id, account_id=account_id)
        )

        if result.get("status") == "error":
            update_payload = {
                "status": "failed",
                "error": result.get("message") or "Unknown workflow failure",
                "result": result,
            }
        else:
            update_payload = {
                "status": "completed",
                "result": result,
            }
        repository.update_job(job_id, update_payload)
    except Exception as exc:
        repository.update_job(
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
        _finalize_job(repository, job_id, started_at)


def queue_crm_event(
    repository: JobRepository,
    payload: CRMEventPayload,
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    existing_job_id = repository.get_job_id_for_event(payload.event_id)
    if existing_job_id:
        existing_job = repository.get_job(existing_job_id)
        return duplicate_event_response(
            payload.event_id,
            existing_job_id,
            (existing_job or {}).get("status", "unknown"),
        )

    if payload.status.lower() != "qualified":
        return ignored_event_response(payload.company_name, payload.status)

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    reserved, existing_job_id = repository.reserve_event(payload.event_id, job_id)
    if not reserved:
        duplicate_job_id = existing_job_id or "unknown"
        duplicate_job = repository.get_job(duplicate_job_id) if existing_job_id else None
        return duplicate_event_response(
            payload.event_id,
            duplicate_job_id,
            (duplicate_job or {}).get("status", "unknown"),
        )

    repository.create_job(job_id, _initial_job_record(job_id, payload))
    background_tasks.add_task(
        run_agent_task_background,
        repository,
        job_id,
        payload.company_name,
        payload.account_id,
    )
    return accepted_event_response(job_id, payload.company_name)


def get_job_status_or_404(repository: JobRepository, job_id: str) -> Dict[str, Any]:
    job = repository.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job ID not found.")
    return job
