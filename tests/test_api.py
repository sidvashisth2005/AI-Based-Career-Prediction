def test_health_and_meta(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["interview_engine"] == "offline"
    meta = client.get("/api/meta").json()
    assert "Python" in meta["skills"] and "coding" in meta["interests"] and len(meta["careers"]) >= 20


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Career Compass" in r.text
    assert client.get("/app.js").status_code == 200 and client.get("/styles.css").status_code == 200
    assert client.get("/docs").status_code == 200  # API docs are not shadowed by the UI mount


def test_resume_upload_and_text(client, resume_text):
    r = client.post("/api/resume/parse", files={"file": ("cv.txt", resume_text.encode(), "text/plain")})
    assert r.status_code == 200 and "Python" in r.json()["skills"]
    r = client.post("/api/resume/parse", data={"text": resume_text})
    assert r.status_code == 200
    assert client.post("/api/resume/parse").status_code == 400
    assert client.post("/api/resume/parse", files={"file": ("cv.exe", b"MZ", "application/octet-stream")}).status_code == 422


def test_predict_gap_interview_flow(client):
    p = client.post("/api/predict", json={"skills": ["python", "ml", "pandas", "sql", "statistics", "juggling"], "interests": ["data"]})
    assert p.status_code == 200
    body = p.json()
    assert body["suited"][0]["career_id"] == "data_scientist"
    assert body["unrecognized_skills"] == ["juggling"]

    g = client.post("/api/gap", json={"career_id": "ml_engineer", "skills": body["recognized_skills"]})
    assert g.status_code == 200 and g.json()["missing_core"]
    assert client.post("/api/gap", json={"career_id": "nope", "skills": []}).status_code == 404

    s = client.post("/api/interview/start", json={"career_id": "data_scientist", "num_questions": 4,
                                                   "profile": {"skills": ["Python"], "projects": ["Churn model"]}})
    assert s.status_code == 200
    sid, total = s.json()["session_id"], s.json()["total"]
    for _ in range(total):
        r = client.post(f"/api/interview/{sid}/answer", json={"answer": "Overfitting means the model memorises noise; I used cross validation."})
        assert r.status_code == 200
    assert r.json()["done"]
    assert client.post(f"/api/interview/{sid}/answer", json={"answer": "extra"}).status_code == 409
    report = client.get(f"/api/interview/{sid}/report").json()
    assert report["complete"] and len(report["items"]) == total
    assert client.get("/api/interview/missing/report").status_code == 404


def test_predict_requires_input(client):
    assert client.post("/api/predict", json={"skills": ["juggling"]}).status_code == 400
