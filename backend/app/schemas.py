"""
Pydantic models = the shapes of data going in and out of the API.

FastAPI uses these to validate requests, serialize responses, and auto-generate
the interactive docs at /docs. Think of them as the backend equivalent of
TypeScript interfaces on the frontend.
"""

from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AskRequest(BaseModel):
    session_id: str = Field(..., description="Which chat session this belongs to")
    question: str = Field(..., min_length=1)
    use_web: bool = Field(
        default=False,
        description="If true and Dappier is configured, the agent may search the web.",
    )


class SourceChunk(BaseModel):
    text: str
    score: float
    document: Optional[str] = None


class AskResponse(BaseModel):
    answer: str
    grounded: bool = Field(
        ..., description="True if the answer came from the uploaded document(s)."
    )
    sources: list[SourceChunk] = []


class UploadResponse(BaseModel):
    filename: str
    chunks_indexed: int
    message: str


class SessionSummary(BaseModel):
    session_id: str
    title: str
    updated_at: datetime
    message_count: int


class SessionDetail(BaseModel):
    session_id: str
    title: str
    messages: list[ChatMessage]


class RenameRequest(BaseModel):
    title: str
