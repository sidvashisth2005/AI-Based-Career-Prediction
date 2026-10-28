"""FastAPI application: REST API plus the single-page web UI."""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Serverless hosts may load this file directly rather than as "app.main"; make sure the project
# root is importable so the absolute "app.*" imports below work either way.
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app import __version__, config, knowledge
from app.gap_analyzer import analyze_gap
from app.interview import engine, llm
from app.job_match import analyze_job_match
from app.predictor import CareerPredictor, Profile
from app.resume_parser import ResumeError, extract_text, parse_resume
from app.resume_quality import assess_resume
from app import voice
from app.schemas import AnswerIn, GapIn, InterviewStartIn, JobMatchIn, PredictIn, ReportIn, SpeakIn, WhatIfIn
from app.skill_extractor import extract_skills, normalize_skills

MAX_RESUME_TEXT = 200_000

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

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


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    """Return a readable JSON error instead of a bare 500 page, and log the traceback."""
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"Server error: {type(exc).__name__}: {exc}"[:300]})


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": __version__,
        "interview_engine": llm.provider() or "offline",
        "ai": {**llm.status(), "speech": voice.available(), "transcription": voice.available(),
               "voices": voice.VOICES if voice.available() else {}, "default_voice": config.GEMINI_TTS_VOICE},
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
    if len(resume_text) > MAX_RESUME_TEXT:
        raise HTTPException(413, "Resume text is too long")
    parsed = parse_resume(resume_text)
    parsed["quality"] = assess_resume(resume_text, parsed["skills"])
    return parsed


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


@app.post("/api/whatif")
def what_if(body: WhatIfIn):
    """Simulate learning new skills: readiness and career ranking before and after."""
    skills, _ = normalize_skills(body.skills)
    added, _ = normalize_skills(body.add_skills)
    added = [s for s in added if s not in skills]
    interests = [i.lower() for i in body.interests if i.lower() in knowledge.INTERESTS]
    if knowledge.get_career(body.career_id) is None:
        raise HTTPException(404, "Unknown career")

    def snapshot(skill_list):
        gap_report = analyze_gap(body.career_id, skill_list, body.experience_years)
        ranking = predictor().predict(Profile(skill_list, interests, body.experience_years), top_k=3)
        rank = next(i for i, r in enumerate(ranking["all"], 1) if r["career_id"] == body.career_id)
        fit = next(r["fit_score"] for r in ranking["all"] if r["career_id"] == body.career_id)
        return {
            "readiness": gap_report["readiness"],
            "readiness_label": gap_report["readiness_label"],
            "remaining_weeks": gap_report["estimated_weeks"],
            "missing_core": [m["requirement"] for m in gap_report["missing_core"]],
            "fit_score": fit,
            "rank": rank,
            "top": [{"career_id": r["career_id"], "title": r["title"], "fit_score": r["fit_score"]} for r in ranking["suited"]],
        }

    before, after = snapshot(skills), snapshot(skills + added)
    return {"career_id": body.career_id, "added_skills": added, "before": before, "after": after,
            "learning_weeks": sum(knowledge.skill_info(s)["weeks"] for s in added)}


@app.post("/api/jobmatch")
def job_match(body: JobMatchIn):
    """Compare a resume against a job description; optionally add AI tailoring advice."""
    skills, _ = normalize_skills(body.skills)
    resume_text = body.resume_text or ""
    if not resume_text.strip() and not skills:
        raise HTTPException(400, "Upload a resume or add skills on the Profile step first")
    result = analyze_job_match(body.job_description, resume_text, skills, body.experience_years, predictor())
    result["quality"] = assess_resume(resume_text, extract_skills(resume_text)) if resume_text.strip() else None
    result["ai"] = None
    result["ai_error"] = None
    if body.use_ai and llm.enabled():
        try:
            result["ai"] = llm.tailor_resume(body.job_description, resume_text or ", ".join(skills), result)
        except llm.LLMError as exc:
            result["ai_error"] = str(exc)
    return result


@app.post("/api/speak", responses={200: {"content": {"audio/wav": {}}}})
def speak(body: SpeakIn):
    """The interviewer's voice: natural-sounding speech from Gemini (WAV)."""
    if not voice.available():
        raise HTTPException(503, "Natural voice needs GEMINI_API_KEY; the browser voice is used instead")
    try:
        audio = voice.speak(body.text, body.voice)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except llm.LLMError as exc:
        raise HTTPException(502, f"Voice unavailable: {exc}") from exc
    return Response(audio, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})


@app.post("/api/transcribe")
def transcribe(file: UploadFile = File(...)):
    """Dictation fallback for browsers without a working speech service: audio in, text out."""
    if not voice.available():
        raise HTTPException(503, "Dictation in this browser needs GEMINI_API_KEY on the server")
    # A plain (sync) endpoint: FastAPI runs it in a worker thread, so the Gemini call does not block.
    data = file.file.read(voice.MAX_AUDIO_BYTES + 1)
    try:
        text = voice.transcribe(data, file.content_type or "audio/wav")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except llm.LLMError as exc:
        raise HTTPException(502, f"Transcription failed: {exc}") from exc
    return {"text": text}


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
        "state": session.to_state(),
    }


def _session(session_id: str, state=None) -> engine.InterviewSession:
    try:
        session = engine.resolve_session(session_id, state.model_dump() if state else None)
    except (KeyError, ValueError):
        raise HTTPException(400, "Invalid interview state") from None
    if session is None:
        raise HTTPException(404, "Interview session not found or expired. Please start a new interview.")
    return session


@app.post("/api/interview/{session_id}/answer")
def interview_answer(session_id: str, body: AnswerIn):
    session = _session(session_id, body.state)
    try:
        result = engine.submit_answer(session, body.answer)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {**result, "state": session.to_state()}


@app.post("/api/interview/{session_id}/report")
def interview_report_from_state(session_id: str, body: ReportIn):
    return engine.build_report(_session(session_id, body.state))


@app.get("/api/interview/{session_id}/report")
def interview_report(session_id: str):
    return engine.build_report(_session(session_id))


# The web UI (index.html, app.js, styles.css). Mounted last so it never shadows /api or /docs.
# On Vercel, public/ is served by the CDN and is not part of the Python function bundle, so
# only mount it when it is present (mounting a missing folder would crash every API route).
if config.PUBLIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=config.PUBLIC_DIR, html=True), name="ui")
