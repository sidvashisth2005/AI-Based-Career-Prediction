"""FastAPI application: REST API plus the single-page web UI."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, config, knowledge
from .gap_analyzer import analyze_gap
from .interview import engine, llm
from .predictor import CareerPredictor, Profile
from .resume_parser import ResumeError, extract_text, parse_resume
from .schemas import AnswerIn, GapIn, InterviewStartIn, PredictIn
from .skill_extractor import normalize_skills

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

_predictor: CareerPredictor | None = None


def predictor() -> CareerPredictor:
    global _predictor
    if _predictor is None:
        _predictor = CareerPredictor.load_or_train()
    return _predictor


@asynccontextmanager
async def lifespan(_app: FastAPI):
    predictor()  # load or train the model before serving requests
    yield


app = FastAPI(
    title="AI-Based Career Prediction",
    version=__version__,
    description="Predict suitable careers, analyse skill gaps and practise mock interviews based on your resume.",
    lifespan=lifespan,
)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": __version__,
        "interview_engine": "claude" if llm.enabled() else "offline",
        "claude_model": config.CLAUDE_MODEL if llm.enabled() else None,
        "model_metrics": predictor().metrics,
    }


@app.get("/api/meta")
def meta():
    return {
        "skills": sorted(knowledge.skills()),
        "interests": knowledge.INTERESTS,
        "careers": [{"id": c["id"], "title": c["title"], "domain": c["domain"]} for c in knowledge.careers()],
    }


@app.get("/api/careers")
def list_careers():
    return [
        {k: c[k] for k in ("id", "title", "domain", "description", "outlook", "salary", "interests")}
        for c in knowledge.careers()
    ]


@app.get("/api/careers/{career_id}")
def get_career(career_id: str):
    career = knowledge.get_career(career_id)
    if career is None:
        raise HTTPException(404, "Unknown career")
    return career


@app.post("/api/resume/parse")
async def parse_resume_endpoint(file: UploadFile | None = File(None), text: str | None = Form(None)):
    if file is None and not (text and text.strip()):
        raise HTTPException(400, "Upload a resume file or paste resume text")
    if file is not None:
        data = await file.read(int(config.MAX_UPLOAD_MB * 1024 * 1024) + 1)
        if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(413, f"File too large (max {config.MAX_UPLOAD_MB:g} MB)")
        try:
            resume_text = extract_text(file.filename or "", data)
        except ResumeError as exc:
            raise HTTPException(422, str(exc)) from exc
    else:
        resume_text = text
    return parse_resume(resume_text)


@app.post("/api/predict")
def predict(body: PredictIn):
    skills, unknown = normalize_skills(body.skills)
    interests = [i.lower() for i in body.interests if i.lower() in knowledge.INTERESTS]
    if not skills and not interests:
        raise HTTPException(400, "Add at least one recognised skill or interest")
    result = predictor().predict(Profile(skills, interests, body.experience_years), top_k=body.top_k)
    return {**result, "recognized_skills": skills, "unrecognized_skills": unknown, "interests": interests}


@app.post("/api/gap")
def gap(body: GapIn):
    skills, unknown = normalize_skills(body.skills)
    try:
        report = analyze_gap(body.career_id, skills, body.experience_years)
    except KeyError:
        raise HTTPException(404, "Unknown career") from None
    return {**report, "unrecognized_skills": unknown}


@app.post("/api/interview/start")
def interview_start(body: InterviewStartIn):
    profile = body.profile.model_dump()
    profile["skills"], _ = normalize_skills(profile["skills"])
    try:
        session = engine.start_interview(body.career_id, profile, body.num_questions, body.difficulty)
    except KeyError:
        raise HTTPException(404, "Unknown career") from None
    return {
        "session_id": session.id,
        "mode": session.mode,
        "title": session.career["title"],
        "total": len(session.questions),
        "notices": session.notices,
        "question": session.question_payload(0),
    }


def _session(session_id: str) -> engine.InterviewSession:
    session = engine.store.get(session_id)
    if session is None:
        raise HTTPException(404, "Interview session not found or expired")
    return session


@app.post("/api/interview/{session_id}/answer")
def interview_answer(session_id: str, body: AnswerIn):
    session = _session(session_id)
    try:
        return engine.submit_answer(session, body.answer)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/interview/{session_id}/report")
def interview_report(session_id: str):
    return engine.build_report(_session(session_id))


app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(config.FRONTEND_DIR / "index.html")
