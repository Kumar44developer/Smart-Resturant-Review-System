"""Pydantic request/response schemas for the /api/v1 surface."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str
    password: str = Field(min_length=8, max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("invalid email")
        return v


class LoginIn(BaseModel):
    email: str
    password: str


class RestaurantIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=200)
    timezone: str = Field(default="UTC", max_length=60)


class MembershipIn(BaseModel):
    email: str
    role: Literal["owner", "manager", "member", "viewer"]


class ReviewIn(BaseModel):
    review_text: str = Field(min_length=1, max_length=5000)
    rating: float | None = Field(default=None, ge=1, le=5)
    source: str = Field(default="manual", max_length=60)
    external_source_id: str | None = Field(default=None, max_length=120)
    author_name: str | None = Field(default=None, max_length=120)
    review_ts: str | None = None
    language: str = Field(default="en", max_length=10)


class ReviewPatch(BaseModel):
    review_text: str | None = Field(default=None, min_length=1, max_length=5000)
    rating: float | None = Field(default=None, ge=1, le=5)
    author_name: str | None = None
    review_ts: str | None = None
    language: str | None = None


class DraftIn(BaseModel):
    tone: Literal["professional", "friendly", "empathetic", "concise"] = "professional"
    length: Literal["short", "medium", "long"] = "medium"


class DraftEdit(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    session_id: int | None = None
    filters: dict | None = None


class ActionIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    owner_user_id: int | None = None
    due_date: str | None = None
    review_ids: list[int] = Field(default_factory=list)


class ActionPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: Literal["open", "in_progress", "completed"] | None = None
    owner_user_id: int | None = None
    due_date: str | None = None
    resolution_note: str | None = None


class ErrorOut(BaseModel):
    error: dict
