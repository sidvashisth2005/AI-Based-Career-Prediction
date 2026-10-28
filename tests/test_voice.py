"""Interviewer voice (TTS) and dictation (transcription) against a mocked Gemini API."""

import base64
import io
import json
import wave

import httpx
import pytest
from google import genai
from google.genai import types

from app import config, voice
from app.interview import llm


@pytest.fixture
def gemini(monkeypatch):
    calls, replies = [], []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"url": str(request.url), "body": json.loads(request.content)})
        status, payload = replies.pop(0)
        return httpx.Response(status, json=payload)

    llm.reset_clients()
    voice._cache.clear()
    monkeypatch.setattr(voice, "_working_tts_model", None)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "LLM_PROVIDER", "gemini")
    llm._clients["gemini"] = genai.Client(api_key="test-key", http_options=types.HttpOptions(
        httpx_client=httpx.Client(transport=httpx.MockTransport(handler))))
    yield calls, replies
    llm.reset_clients()


def _voice_name(body: dict) -> str:
    """The SDK may send nested speech settings in snake_case or camelCase; the API accepts both."""
    cfg = body["generationConfig"]["speechConfig"]
    vc = cfg.get("voiceConfig") or cfg["voice_config"]
    pvc = vc.get("prebuiltVoiceConfig") or vc["prebuilt_voice_config"]
    return pvc.get("voiceName") or pvc["voice_name"]


def _audio_reply(pcm: bytes):
    return 200, {"candidates": [{"content": {"role": "model", "parts": [{"inlineData": {
        "mimeType": "audio/L16;codec=pcm;rate=24000", "data": base64.b64encode(pcm).decode()}}]}, "finishReason": "STOP"}]}


def test_speak_returns_wav_in_chosen_voice(gemini, client):
    calls, replies = gemini
    replies.append(_audio_reply(b"\x00\x01" * 2400))
    r = client.post("/api/speak", json={"text": "Tell me about yourself.", "voice": "Achird"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    with wave.open(io.BytesIO(r.content)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (24000, 1, 2, 2400)
    body = calls[0]["body"]
    assert f"models/{config.GEMINI_TTS_MODEL}:generateContent" in calls[0]["url"]
    assert body["generationConfig"]["responseModalities"] == ["AUDIO"]
    assert _voice_name(body) == "Achird"
    assert "Tell me about yourself." in body["contents"][0]["parts"][0]["text"]

    # Repeating the same line is served from the cache, not a second API call.
    assert client.post("/api/speak", json={"text": "Tell me about yourself.", "voice": "Achird"}).status_code == 200
    assert len(calls) == 1


def test_speak_falls_back_to_older_tts_model(gemini):
    calls, replies = gemini
    replies.append((404, {"error": {"code": 404, "message": "model not found", "status": "NOT_FOUND"}}))
    replies.append(_audio_reply(b"\x00\x00" * 10))
    assert voice.speak("Hello there", "Unknown voice").startswith(b"RIFF")
    assert config.GEMINI_TTS_FALLBACK_MODEL in calls[1]["url"]
    assert _voice_name(calls[1]["body"]) == config.GEMINI_TTS_VOICE


def test_transcribe_sends_audio_and_returns_text(gemini, client):
    calls, replies = gemini
    replies.append((200, {"candidates": [{"content": {"role": "model", "parts": [{"text": "I built a churn model.\n"}]}, "finishReason": "STOP"}]}))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\x00\x00" * 1600)
    r = client.post("/api/transcribe", files={"file": ("answer.wav", buf.getvalue(), "audio/wav")})
    assert r.status_code == 200 and r.json()["text"] == "I built a churn model."
    parts = calls[0]["body"]["contents"][0]["parts"]
    blob = parts[0].get("inlineData") or parts[0]["inline_data"]
    assert (blob.get("mimeType") or blob["mime_type"]) == "audio/wav" and blob["data"]
    assert "Transcribe" in parts[1]["text"]


def test_transcribe_rejects_non_audio(gemini, client):
    r = client.post("/api/transcribe", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400


def test_voice_endpoints_need_gemini(client):
    # Tests run with LLM_PROVIDER=off: the browser's own voice is used instead.
    assert client.post("/api/speak", json={"text": "Hi"}).status_code == 503
    assert client.post("/api/transcribe", files={"file": ("a.wav", b"RIFF", "audio/wav")}).status_code == 503
    ai = client.get("/api/health").json()["ai"]
    assert ai["speech"] is False and ai["transcription"] is False and ai["voices"] == {}
