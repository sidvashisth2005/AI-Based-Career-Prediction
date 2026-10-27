"""Exercises the Claude integration against a mocked HTTP transport (no network, no API key)."""

import json

import anthropic
import httpx2
import pytest

from app import knowledge
from app.gap_analyzer import analyze_gap
from app.interview import engine, llm


def _message(payload: dict, stop_reason: str = "end_turn") -> dict:
    return {
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": [{"type": "text", "text": json.dumps(payload)}],
        "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }


@pytest.fixture
def mock_claude(monkeypatch):
    calls, replies = [], []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append({"headers": dict(request.headers), "body": json.loads(request.content)})
        return httpx2.Response(200, json=replies.pop(0))

    client = anthropic.Anthropic(api_key="test-key", max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr(llm, "_client", client)
    monkeypatch.setattr(llm.config, "LLM_MODE", "on")
    return calls, replies


def test_generate_questions_request_and_parsing(mock_claude):
    calls, replies = mock_claude
    replies.append(_message({"questions": [
        {"question": f"Q{i}?", "category": "technical", "skill": "Python", "keywords": ["a", "b"], "ideal_answer": "x"} for i in range(5)
    ]}))
    career = knowledge.get_career("backend_developer")
    profile = {"skills": ["Python"], "projects": ["Library API"], "experience_years": 1, "resume_text": "Built a Library API in Flask."}
    qs = llm.generate_questions(career, profile, analyze_gap(career["id"], ["Python"], 1), 5, "medium")

    assert [q["text"] for q in qs] == [f"Q{i}?" for i in range(5)]
    body = calls[0]["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in calls[0]["headers"]["anthropic-beta"]
    assert "Library API" in body["messages"][0]["content"]


def test_evaluate_answer_clamps_score(mock_claude):
    _, replies = mock_claude
    replies.append(_message({"score": 14, "strengths": ["clear"], "improvements": ["add example"], "missing_points": ["index"], "model_answer": "Use an index."}))
    q = {"text": "What is an index?", "category": "technical", "skill": "SQL", "keywords": ["b-tree"], "ideal": ""}
    ev = llm.evaluate_answer(knowledge.get_career("backend_developer"), q, "It speeds up lookups.", "easy")
    assert ev["score"] == 10 and ev["evaluator"] == "claude" and ev["missing_keywords"] == ["index"]


def test_refusal_falls_back_to_offline(mock_claude):
    _, replies = mock_claude
    replies.append(_message({}, stop_reason="refusal"))
    s = engine.start_interview("frontend_developer", {"skills": ["React"]}, 5, "easy")
    assert s.mode == "offline" and s.notices
    assert len(s.questions) == 5
