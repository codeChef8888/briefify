from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
