from typing import Any, Dict

from fastapi import status
from fastapi.responses import JSONResponse

from briefify.schemas.error_contract import build_error


def payload_too_large_response() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        content=build_error(
            code="PAYLOAD_TOO_LARGE",
            message="Webhook payload exceeds allowed size",
            stage="api_webhook",
            retryable=False,
        ),
    )


def duplicate_event_response(event_id: str, job_id: str, job_status: str) -> Dict[str, Any]:
    return {
        "status": "duplicate",
        "message": f"Duplicate webhook event '{event_id}' detected.",
        "job_id": job_id,
        "check_status_url": f"/jobs/{job_id}",
        "job_status": job_status,
    }


def ignored_event_response(company_name: str, account_status: str) -> Dict[str, Any]:
    return {
        "status": "ignored",
        "message": f"Account '{company_name}' status is '{account_status}'. Pipeline requires 'Qualified'.",
    }


def accepted_event_response(job_id: str, company_name: str) -> Dict[str, Any]:
    return {
        "status": "accepted",
        "job_id": job_id,
        "check_status_url": f"/jobs/{job_id}",
        "message": f"Agent workflow queued for account '{company_name}'.",
    }
