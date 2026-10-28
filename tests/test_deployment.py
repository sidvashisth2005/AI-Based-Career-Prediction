"""Checks that matter for serverless hosting (Vercel): read-only disk, stateless requests, packaging."""

import re
import runpy
import tomllib
from pathlib import Path

import numpy as np

from app import predictor
from app.interview import engine

ROOT = Path(__file__).resolve().parent.parent


def test_shipped_model_is_current():
    """The committed model must match the knowledge base so serverless hosts never need to train."""
    bundle = predictor.load_bundle(ROOT / "models" / predictor.MODEL_FILE)
    assert bundle["version"] == predictor.MODEL_VERSION
    assert bundle["features"] == predictor._feature_names()
    assert bundle["classes"] == predictor._class_names()
    assert bundle["metrics"]["accuracy"] > 0.85


def test_training_survives_read_only_disk(monkeypatch, tmp_path):
    monkeypatch.setattr(predictor, "MODEL_PATH", Path("/proc/not-writable/career_model.npz"))
    monkeypatch.setattr(predictor.tempfile, "gettempdir", lambda: str(tmp_path))
    model = predictor.CareerPredictor.load_or_train()
    assert (tmp_path / predictor.MODEL_FILE).exists()  # fell back to the temp dir
    assert model.predict(predictor.Profile(["Python", "SQL"], [], 0))["suited"]

    # Even with nowhere writable, it still trains in memory instead of crashing.
    monkeypatch.setattr(predictor.tempfile, "gettempdir", lambda: "/proc/also-not-writable")
    assert predictor.save_bundle(predictor.train(samples_per_career=20, save=False)) is None


def test_softmax_probabilities_are_valid():
    model = predictor.CareerPredictor.load_or_train()
    probs = model.probabilities(predictor.Profile(["Python"], ["data"], 0))
    assert set(probs) == set(predictor._class_names())
    assert np.isclose(sum(probs.values()), 1.0)


def test_interview_continues_on_another_instance(client):
    """Simulate Vercel: each request may reach a fresh instance with an empty session store."""
    start = client.post("/api/interview/start", json={"career_id": "backend_developer", "num_questions": 4,
                                                       "profile": {"skills": ["Python", "SQL"]}}).json()
    sid, state = start["session_id"], start["state"]
    for i in range(start["total"]):
        engine.store._sessions.clear()  # new instance: nothing in memory
        r = client.post(f"/api/interview/{sid}/answer", json={"answer": f"Answer {i} with an index and a join.", "state": state})
        assert r.status_code == 200, r.text
        state = r.json()["state"]
        assert len(state["answers"]) == i + 1
    engine.store._sessions.clear()
    report = client.post(f"/api/interview/{sid}/report", json={"state": state}).json()
    assert report["complete"] and report["answered"] == start["total"]

    # Without state, a fresh instance cannot know the session.
    engine.store._sessions.clear()
    assert client.post(f"/api/interview/{sid}/answer", json={"answer": "x"}).status_code == 404


def test_tampered_state_is_rejected(client):
    start = client.post("/api/interview/start", json={"career_id": "qa_engineer", "num_questions": 4}).json()
    engine.store._sessions.clear()
    bad = dict(start["state"], career_id="not_a_career")
    assert client.post(f"/api/interview/{start['session_id']}/answer", json={"answer": "x", "state": bad}).status_code == 400
    bad = dict(start["state"], mode="hacker")
    assert client.post(f"/api/interview/{start['session_id']}/answer", json={"answer": "x", "state": bad}).status_code == 422


def test_entrypoint_loads_as_plain_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # not the project root
    namespace = runpy.run_path(str(ROOT / "app" / "main.py"))
    assert namespace["app"].title == "AI-Based Career Prediction"


def test_pyproject_matches_requirements():
    reqs = [ln.strip() for ln in (ROOT / "requirements.txt").read_text().splitlines()
            if ln.strip() and not ln.startswith("#")]
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert project["project"]["dependencies"] == reqs
    assert project["tool"]["vercel"]["entrypoint"] == "app.main:app"
    assert not any(re.match(r"scikit-learn|scipy|joblib", r) for r in reqs)  # keep the bundle small


def test_api_works_without_public_folder(tmp_path, monkeypatch):
    """On Vercel, public/ is served by the CDN and is absent from the function bundle."""
    import shutil
    import subprocess
    import sys

    bundle = tmp_path / "bundle"
    shutil.copytree(ROOT / "app", bundle / "app", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "models", bundle / "models")
    code = ("from fastapi.testclient import TestClient\n"
            "from app.main import app\n"
            "c = TestClient(app)\n"
            "assert c.get('/api/meta').status_code == 200\n"
            "r = c.post('/api/resume/parse', files={'file': ('cv.txt', b'Skills: Python, SQL, Docker', 'text/plain')})\n"
            "assert r.status_code == 200 and 'Python' in r.json()['skills'], r.text\n"
            "print('ok')\n")
    env = {**__import__("os").environ, "LLM_PROVIDER": "off", "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("MODEL_DIR", None)
    out = subprocess.run([sys.executable, "-c", code], cwd=bundle, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0 and "ok" in out.stdout, out.stderr[-2000:]


def test_unexpected_errors_return_json(client, monkeypatch):
    from app import main

    def boom(*_args, **_kwargs):
        raise ValueError("simulated failure")

    monkeypatch.setattr(main, "parse_resume", boom)
    from fastapi.testclient import TestClient

    with TestClient(main.app, raise_server_exceptions=False) as c:
        r = c.post("/api/resume/parse", data={"text": "Python developer"})
    assert r.status_code == 500 and "simulated failure" in r.json()["detail"]
