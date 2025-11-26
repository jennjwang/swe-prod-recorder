from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Update(BaseModel):
    content: str = Field(..., description="The content of the update")
    content_type: Literal["input_text", "input_image"] = Field(
        ..., description="The type of the update"
    )
    event_ts: float | None = Field(
        None,
        description="Unix timestamp (seconds) when the underlying interaction occurred",
    )
