from typing import Any


def build_error(
    *,
    code: str,
    message: str,
    stage: str,
    retryable: bool,
    status: str = "error",
    details: Any | None = None,
) -> dict[str, Any]:
    """Return the canonical error envelope used across API and workflow nodes."""
    payload: dict[str, Any] = {
        "status": status,
        "code": code,
        "message": message,
        "stage": stage,
        "retryable": retryable,
    }
    if details is not None:
        payload["details"] = details
    return payload
