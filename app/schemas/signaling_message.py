"""Read-only dictionary-backed signaling message contract."""
from typing import Literal
from pydantic import BaseModel


class SignalingParameter(BaseModel):
    path: str
    name: str
    value: str | None
    unit: str | None
    display_name: str | None
    category: str | None


class SignalingMessage(BaseModel):
    project_id: str
    capture_id: str
    seq: int
    message_name: str | None
    protocol: Literal['rrc_lte', 'rrc_nr', 'nas']
    direction: str | None
    channel: str | None
    size_bytes: int | None
    tree: list[SignalingParameter]
    text: str
    hex: str | None
    reason: str | None
    tree_reason: str | None = None
