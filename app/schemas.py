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


class AnswerIn(BaseModel):
    answer: str = Field("", max_length=10_000)
