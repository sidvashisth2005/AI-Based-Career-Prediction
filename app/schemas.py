"""Request models for the API."""

from typing import Literal

from pydantic import BaseModel, Field


class ProfileIn(BaseModel):
    skills: list[str] = Field(default_factory=list, max_length=200)
    interests: list[str] = Field(default_factory=list, max_length=20)
    experience_years: float = Field(0.0, ge=0, le=50)
    education: str | None = None


class PredictIn(ProfileIn):
    top_k: int = Field(5, ge=1, le=30)


class GapIn(BaseModel):
    career_id: str
    skills: list[str] = Field(default_factory=list, max_length=200)
    experience_years: float = Field(0.0, ge=0, le=50)


class InterviewProfile(BaseModel):
    skills: list[str] = Field(default_factory=list, max_length=200)
    projects: list[str] = Field(default_factory=list, max_length=20)
    experience_years: float = Field(0.0, ge=0, le=50)
    resume_text: str | None = Field(None, max_length=200_000)


class InterviewStartIn(BaseModel):
    career_id: str
    profile: InterviewProfile = Field(default_factory=InterviewProfile)
    num_questions: int = Field(6, ge=4, le=12)
    difficulty: Literal["easy", "medium", "hard"] = "medium"


class StateQuestion(BaseModel):
    text: str = Field(..., max_length=3000)
    category: Literal["introduction", "technical", "project", "scenario", "behavioral"]
    skill: str | None = Field(None, max_length=100)
    keywords: list[str] = Field(default_factory=list, max_length=12)
    ideal: str = Field("", max_length=4000)


class StateEvaluation(BaseModel):
    score: float = Field(..., ge=0, le=10)
    max_score: int = 10
    strengths: list[str] = Field(default_factory=list, max_length=10)
    improvements: list[str] = Field(default_factory=list, max_length=10)
    matched_keywords: list[str] = Field(default_factory=list, max_length=20)
    missing_keywords: list[str] = Field(default_factory=list, max_length=20)
    model_answer: str = Field("", max_length=4000)
    evaluator: str | None = Field(None, max_length=20)


class StateAnswer(BaseModel):
    answer: str = Field("", max_length=10_000)
    evaluation: StateEvaluation


class InterviewState(BaseModel):
    """Interview state the browser keeps and sends back, so any server instance can continue it."""

    id: str = Field(..., min_length=8, max_length=64)
    career_id: str = Field(..., max_length=64)
    difficulty: Literal["easy", "medium", "hard"]
    mode: Literal["gemini", "claude", "offline"]
    questions: list[StateQuestion] = Field(..., min_length=1, max_length=12)
    answers: list[StateAnswer] = Field(default_factory=list, max_length=12)
    notices: list[str] = Field(default_factory=list, max_length=5)
    skills: list[str] = Field(default_factory=list, max_length=200)


class AnswerIn(BaseModel):
    answer: str = Field("", max_length=10_000)
    state: InterviewState | None = None


class ReportIn(BaseModel):
    state: InterviewState | None = None


class WhatIfIn(BaseModel):
    career_id: str
    skills: list[str] = Field(default_factory=list, max_length=200)
    add_skills: list[str] = Field(default_factory=list, max_length=50)
    interests: list[str] = Field(default_factory=list, max_length=20)
    experience_years: float = Field(0.0, ge=0, le=50)


class JobMatchIn(BaseModel):
    job_description: str = Field(..., min_length=30, max_length=50_000)
    resume_text: str | None = Field(None, max_length=200_000)
    skills: list[str] = Field(default_factory=list, max_length=200)
    experience_years: float = Field(0.0, ge=0, le=50)
    use_ai: bool = True
