"""Pydantic-модели для API."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class QuestionItem(BaseModel):
    q_number: int
    q_title: str = ""
    q_summary: str = ""


class DecisionItem(BaseModel):
    d_number: int
    d_text: str = ""
    d_owner: str = ""
    d_due: str = ""


class OpenQuestionItem(BaseModel):
    o_number: int
    o_text: str = ""
    o_owner: str = ""
    o_due: str = ""


class Protocol(BaseModel):
    date: str = ""
    time_start: str = ""
    participants: str = ""
    agenda: str = ""
    questions: list[QuestionItem] = Field(default_factory=list)
    decisions: list[DecisionItem] = Field(default_factory=list)
    open_questions: list[OpenQuestionItem] = Field(default_factory=list)


class JobStatus(BaseModel):
    job_id: str
    status: Literal["pending", "transcribing", "analyzing", "rendering", "completed", "failed"]
    model_used: str
    is_video: bool
    file_name: str
    created_at: datetime
    finished_at: datetime | None = None
    error: str | None = None
    protocol: Protocol | None = None
    docx_url: str | None = None
