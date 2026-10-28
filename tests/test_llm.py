"""Exercises the Gemini and Claude integrations against mocked HTTP transports (no network, no API key)."""

import json

import anthropic
import httpx
import httpx2
import pytest
from google import genai
from google.genai import types

from app import config, knowledge
from app.gap_analyzer import analyze_gap
from app.interview import engine, llm


@pytest.fixture(autouse=True)
def _fresh_clients():
    llm.reset_clients()
    yield
    llm.reset_clients()


# ------------------------------------------------------------------ provider selection

@pytest.mark.parametrize("setting,env,expected", [
    ("auto", {}, None),
    ("auto", {"GEMINI_API_KEY": "key"}, "gemini"),
    ("auto", {"ANTHROPIC_API_KEY": "key"}, "claude"),
    ("auto", {"GEMINI_API_KEY": "g", "ANTHROPIC_API_KEY": "a"}, "gemini"),
    ("auto", {"GEMINI_API_KEY": "paste-your-gemini-api-key-here"}, None),
    ("claude", {"GEMINI_API_KEY": "g"}, "claude"),
    ("gemini", {}, None),
    ("off", {"GEMINI_API_KEY": "g"}, None),
])
def test_provider_selection(monkeypatch, setting, env, expected):
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(config, "LLM_PROVIDER", setting)
    assert llm.provider() == expected


# ------------------------------------------------------------------ Gemini

def _gemini_reply(payload, finish="STOP"):
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(payload)}]}, "finishReason": finish}]}


@pytest.fixture
def mock_gemini(monkeypatch):
    calls, replies = [], []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"url": str(request.url), "headers": dict(request.headers), "body": json.loads(request.content)})
        return httpx.Response(200, json=replies.pop(0))

    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(config, "LLM_PROVIDER", "gemini")
    client = genai.Client(api_key="test-gemini-key", http_options=types.HttpOptions(
        httpx_client=httpx.Client(transport=httpx.MockTransport(handler))))
    llm._clients["gemini"] = client
    return calls, replies


def test_gemini_questions_request_and_parsing(mock_gemini):
    calls, replies = mock_gemini
    replies.append(_gemini_reply({"questions": [
        {"question": f"Q{i}?", "category": "technical", "skill": "Python", "keywords": ["a"], "ideal_answer": "x"} for i in range(5)
    ]}))
    career = knowledge.get_career("backend_developer")
    profile = {"skills": ["Python"], "projects": ["Library API"], "experience_years": 1, "resume_text": "Built a Library API."}
    qs = llm.generate_questions(career, profile, analyze_gap(career["id"], ["Python"], 1), 5, "medium")

    assert [q["text"] for q in qs] == [f"Q{i}?" for i in range(5)]
    call = calls[0]
    assert f"models/{config.GEMINI_MODEL}:generateContent" in call["url"]
    assert call["headers"]["x-goog-api-key"] == "test-gemini-key"
    gen = call["body"]["generationConfig"]
    assert gen["responseMimeType"] == "application/json"
    assert "additionalProperties" not in json.dumps(gen["responseJsonSchema"])
    assert "Library API" in call["body"]["contents"][0]["parts"][0]["text"]
    assert "interviewer" in call["body"]["systemInstruction"]["parts"][0]["text"]


def test_gemini_full_interview_and_tailoring(mock_gemini):
    _, replies = mock_gemini
    replies.append(_gemini_reply({"questions": [
        {"question": f"Q{i}?", "category": "behavioral", "skill": "general", "keywords": [], "ideal_answer": ""} for i in range(4)
    ]}))
    s = engine.start_interview("data_analyst", {"skills": ["SQL"]}, 4, "easy")
    assert s.mode == "gemini"
    replies.append(_gemini_reply({"score": 7.5, "strengths": ["clear"], "improvements": [], "missing_points": [], "model_answer": "m"}))
    r = engine.submit_answer(s, "My answer")
    assert r["evaluation"]["score"] == 7.5 and r["evaluation"]["evaluator"] == "gemini"

    replies.append(_gemini_reply({"fit_summary": "ok", "tailored_summary": "sum",
                                  "bullet_rewrites": [{"original": "a", "improved": "b"}], "tips": ["t"]}))
    out = llm.tailor_resume("JD text", "resume", {"match_score": 50, "matched_skills": [], "missing_skills": ["AWS"], "missing_keywords": []})
    assert out["bullet_rewrites"] == [{"original": "a", "improved": "b"}] and out["provider"] == "gemini"


def test_gemini_api_error_falls_back_to_offline(monkeypatch):
    def handler(request):
        return httpx.Response(403, json={"error": {"code": 403, "message": "API key not valid", "status": "PERMISSION_DENIED"}})

    monkeypatch.setenv("GEMINI_API_KEY", "bad")
    monkeypatch.setattr(config, "LLM_PROVIDER", "gemini")
    llm._clients["gemini"] = genai.Client(api_key="bad", http_options=types.HttpOptions(
        httpx_client=httpx.Client(transport=httpx.MockTransport(handler))))
    with pytest.raises(llm.LLMError, match="403"):
        llm.evaluate_answer(knowledge.get_career("qa_engineer"), {"text": "Q", "category": "technical"}, "a", "easy")
    s = engine.start_interview("qa_engineer", {"skills": []}, 4, "easy")
    assert s.mode == "offline" and "403" in s.notices[0]


# ------------------------------------------------------------------ Claude

def _claude_message(payload: dict, stop_reason: str = "end_turn") -> dict:
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

    llm._clients["claude"] = anthropic.Anthropic(
        api_key="test-key", max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr(config, "LLM_PROVIDER", "claude")
    return calls, replies


def test_claude_questions_request_and_parsing(mock_claude):
    calls, replies = mock_claude
    replies.append(_claude_message({"questions": [
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


def test_claude_evaluate_answer_clamps_score(mock_claude):
    _, replies = mock_claude
    replies.append(_claude_message({"score": 14, "strengths": ["clear"], "improvements": [], "missing_points": ["index"], "model_answer": "m"}))
    q = {"text": "What is an index?", "category": "technical", "skill": "SQL", "keywords": ["b-tree"], "ideal": ""}
    ev = llm.evaluate_answer(knowledge.get_career("backend_developer"), q, "It speeds up lookups.", "easy")
    assert ev["score"] == 10 and ev["evaluator"] == "claude" and ev["missing_keywords"] == ["index"]


def test_claude_refusal_falls_back_to_offline(mock_claude):
    _, replies = mock_claude
    replies.append(_claude_message({}, stop_reason="refusal"))
    s = engine.start_interview("frontend_developer", {"skills": ["React"]}, 5, "easy")
    assert s.mode == "offline" and s.notices
    assert len(s.questions) == 5
