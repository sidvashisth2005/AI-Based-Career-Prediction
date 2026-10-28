from pathlib import Path

from app.resume_quality import assess_resume

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
JD = (SAMPLES / "sample_job_description.txt").read_text(encoding="utf-8")


def test_resume_quality_good_vs_poor(resume_text):
    good = assess_resume(resume_text, ["Python"] * 10)
    assert good["score"] >= 70 and good["stats"]["quantified_bullets"] >= 2
    poor = assess_resume("I am a hard working team player. I worked on various things etc.", [])
    assert poor["score"] < 30 and poor["label"] == "Weak"
    names = {c["name"] for c in poor["checks"] if not c["passed"]}
    assert {"Contact details", "Skills section", "Quantified impact", "No weak phrases"} <= names
    assert any("short" in t for t in poor["tips"])


def test_parse_includes_quality(client, resume_text):
    r = client.post("/api/resume/parse", data={"text": resume_text}).json()
    assert 0 <= r["quality"]["score"] <= 100 and r["quality"]["checks"]


def test_job_match(client, resume_text):
    r = client.post("/api/jobmatch", json={"job_description": JD, "resume_text": resume_text, "experience_years": 0.2})
    assert r.status_code == 200
    body = r.json()
    assert body["likely_role"]["career_id"] == "ml_engineer"
    assert {"Python", "SQL", "Docker"} <= set(body["matched_skills"])
    assert {"Kubernetes", "AWS"} <= set(body["missing_skills"])
    assert "spark" not in body["missing_keywords"]  # covered by the Big Data skill, not double counted
    assert 0 < body["match_score"] < 100 and body["suggestions"]
    assert body["ai"] is None  # no provider configured in tests
    assert body["quality"]["score"] > 0


def test_job_match_flags_experience_gap(client, resume_text):
    jd = "Senior Backend Engineer. Requires 5+ years of experience with Python, Django, PostgreSQL and AWS."
    body = client.post("/api/jobmatch", json={"job_description": jd, "resume_text": resume_text, "experience_years": 0}).json()
    assert body["required_years"] == 5 and any("5+ years" in f for f in body["flags"])


def test_job_match_validation(client):
    assert client.post("/api/jobmatch", json={"job_description": "too short"}).status_code == 422
    assert client.post("/api/jobmatch", json={"job_description": JD}).status_code == 400


def test_what_if_improves_readiness(client):
    r = client.post("/api/whatif", json={"career_id": "devops_engineer", "skills": ["Linux", "Git"],
                                          "add_skills": ["Docker", "CI/CD", "AWS", "Linux"]})
    assert r.status_code == 200
    body = r.json()
    assert body["added_skills"] == ["Docker", "CI/CD", "AWS"]  # already-known Linux is ignored
    assert body["after"]["readiness"] > body["before"]["readiness"]
    assert body["after"]["rank"] <= body["before"]["rank"]
    assert body["after"]["remaining_weeks"] < body["before"]["remaining_weeks"]
    assert body["learning_weeks"] > 0
    assert client.post("/api/whatif", json={"career_id": "x", "skills": []}).status_code == 404


def test_health_reports_ai_status(client):
    h = client.get("/api/health").json()
    assert h["interview_engine"] == "offline" and h["ai"]["label"] == "Offline"
