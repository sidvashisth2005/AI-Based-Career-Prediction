"""Interview sessions: question flow, scoring and the final report.

Sessions are cached in memory, and the full session state is also returned to the browser
with every response. The browser sends it back with each answer, so the interview keeps
working on serverless hosts (e.g. Vercel) where consecutive requests can reach different
instances that do not share memory.
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field

from app import config, knowledge
from app.gap_analyzer import analyze_gap
from app.interview import llm, offline

log = logging.getLogger(__name__)


@dataclass
class InterviewSession:
    id: str
    career: dict
    profile: dict
    difficulty: str
    questions: list[dict]
    mode: str  # "gemini", "claude" or "offline"
    answers: list[dict] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    notices: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def done(self) -> bool:
        return len(self.answers) >= len(self.questions)

    def to_state(self) -> dict:
        """Everything needed to continue this interview on another server instance."""
        return {
            "id": self.id,
            "career_id": self.career["id"],
            "difficulty": self.difficulty,
            "mode": self.mode,
            "questions": self.questions,
            "answers": self.answers,
            "notices": self.notices,
            "skills": self.profile.get("skills", []),
        }

    @classmethod
    def from_state(cls, state: dict) -> "InterviewSession":
        career = knowledge.get_career(state["career_id"])
        if career is None:
            raise KeyError(state["career_id"])
        if len(state["answers"]) > len(state["questions"]):
            raise ValueError("Invalid interview state")
        return cls(
            id=state["id"], career=career, profile={"skills": state.get("skills", [])},
            difficulty=state["difficulty"], questions=state["questions"], mode=state["mode"],
            answers=list(state["answers"]), notices=state.get("notices", []),
        )

    def question_payload(self, index: int) -> dict:
        q = self.questions[index]
        return {"index": index, "number": index + 1, "total": len(self.questions), "text": q["text"], "category": q["category"], "skill": q.get("skill")}


class SessionStore:
    def __init__(self, ttl_minutes: int = config.SESSION_TTL_MINUTES, max_sessions: int = config.MAX_SESSIONS):
        self._sessions: dict[str, InterviewSession] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_minutes * 60
        self._max = max_sessions

    def add(self, session: InterviewSession) -> None:
        with self._lock:
            self._purge()
            while len(self._sessions) >= self._max:  # drop the oldest to bound memory
                del self._sessions[min(self._sessions, key=lambda k: self._sessions[k].created)]
            self._sessions[session.id] = session

    def get(self, session_id: str) -> InterviewSession | None:
        with self._lock:
            self._purge()
            return self._sessions.get(session_id)

    def _purge(self) -> None:
        cutoff = time.time() - self._ttl
        for sid in [sid for sid, s in self._sessions.items() if s.created < cutoff]:
            del self._sessions[sid]


store = SessionStore()


def resolve_session(session_id: str, state: dict | None) -> InterviewSession | None:
    """Find a session in this instance's memory, or rebuild it from the state the browser sent."""
    session = store.get(session_id)
    if session is not None:
        return session
    if state is None or state.get("id") != session_id:
        return None
    session = InterviewSession.from_state(state)
    store.add(session)
    return session


def start_interview(career_id: str, profile: dict, num_questions: int = 6, difficulty: str = "medium") -> InterviewSession:
    career = knowledge.get_career(career_id)
    if career is None:
        raise KeyError(career_id)
    gap = analyze_gap(career_id, profile.get("skills", []), profile.get("experience_years", 0))
    notices = []
    questions, mode = None, "offline"
    provider = llm.provider()
    if provider:
        try:
            questions = llm.generate_questions(career, profile, gap, num_questions, difficulty)
            mode = provider
        except llm.LLMError as exc:
            log.warning("Falling back to offline questions: %s", exc)
            notices.append(f"AI question generation was unavailable ({exc}), so questions come from the built-in bank.")
    if questions is None:
        questions = offline.plan_questions(career, profile, num_questions, difficulty)
    session = InterviewSession(
        id=uuid.uuid4().hex, career=career, profile=profile, difficulty=difficulty,
        questions=questions, mode=mode, notices=notices,
    )
    store.add(session)
    return session


def submit_answer(session: InterviewSession, answer: str) -> dict:
    # Serialise answers per session so a double-click cannot record two answers for one question.
    with session.lock:
        return _submit_answer(session, answer)


def _submit_answer(session: InterviewSession, answer: str) -> dict:
    if session.done:
        raise ValueError("This interview is already complete")
    index = len(session.answers)
    question = session.questions[index]
    evaluation = None
    if session.mode != "offline":
        try:
            evaluation = llm.evaluate_answer(session.career, question, answer, session.difficulty)
        except llm.LLMError as exc:
            log.warning("Falling back to offline grading: %s", exc)
    if evaluation is None:
        evaluation = offline.evaluate_answer(question, answer)
    session.answers.append({"answer": answer, "evaluation": evaluation})
    result = {"question_index": index, "evaluation": evaluation, "done": session.done}
    if not session.done:
        result["next_question"] = session.question_payload(index + 1)
    return result


def verdict(avg: float) -> tuple[str, str]:
    if avg >= 7.5:
        return "Strong", "You are interview-ready for this role. Keep practising with harder questions and real projects."
    if avg >= 5.5:
        return "Promising", "Good foundation. Polish the weaker topics below and add more concrete examples to your answers."
    if avg >= 3.5:
        return "Needs practice", "Work through the skill-gap roadmap for this role and retake the mock interview in a few weeks."
    return "Not ready yet", "Focus on the core skills for this role first; use the learning roadmap, then practise again."


def build_report(session: InterviewSession) -> dict:
    items, by_category = [], {}
    for q, a in zip(session.questions, session.answers):
        ev = a["evaluation"]
        items.append({"question": q["text"], "category": q["category"], "skill": q.get("skill"), "answer": a["answer"], **ev})
        by_category.setdefault(q["category"], []).append(ev["score"])
    scores = [i["score"] for i in items]
    avg = round(sum(scores) / len(scores), 1) if scores else 0.0
    label, advice = verdict(avg)
    weak_skills = sorted({i["skill"] for i in items if i["skill"] and i["score"] < 6})
    strong = sorted({i["skill"] for i in items if i["skill"] and i["score"] >= 7.5})
    return {
        "session_id": session.id,
        "career_id": session.career["id"],
        "title": session.career["title"],
        "mode": session.mode,
        "difficulty": session.difficulty,
        "answered": len(items),
        "total": len(session.questions),
        "complete": session.done,
        "overall_score": avg,
        "overall_percent": round(avg * 10),
        "verdict": label,
        "advice": advice,
        "category_scores": {k: round(sum(v) / len(v), 1) for k, v in by_category.items()},
        "strong_topics": strong,
        "topics_to_improve": weak_skills,
        "resources": [{"skill": s, "url": knowledge.skill_info(s)["resource"]} for s in weak_skills if s in knowledge.skills()],
        "items": items,
    }
