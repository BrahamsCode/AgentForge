import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Provider = Literal["anthropic", "openai", "ollama"]


# --- Auth ---

class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    role: str
    created_at: datetime


# --- Agentes ---

class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    role: str = Field(min_length=1, max_length=128)
    model_provider: Provider = "anthropic"
    model_name: str = "claude-opus-4-8"
    system_prompt: str = ""
    max_steps: int = Field(default=30, ge=1, le=500)
    max_cost_usd: float = Field(default=1.0, gt=0)
    temperature: float | None = Field(default=None, ge=0, le=2)


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    role: str | None = None
    model_provider: Provider | None = None
    model_name: str | None = None
    system_prompt: str | None = None
    max_steps: int | None = Field(default=None, ge=1, le=500)
    max_cost_usd: float | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0, le=2)


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    role: str
    model_provider: Provider
    model_name: str
    system_prompt: str
    max_steps: int
    max_cost_usd: float
    temperature: float | None
    created_at: datetime


# --- Chat simple (entregable Fase 0) ---

class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=20_000)


class AskResponse(BaseModel):
    answer: str
    model_provider: Provider
    model_name: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
