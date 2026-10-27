import pytest

from app import predictor
from app.gap_analyzer import analyze_gap


@pytest.fixture(scope="module")
def model():
    return predictor.CareerPredictor.load_or_train()


@pytest.mark.parametrize("skills,interests,expected", [
    (["Python", "Machine Learning", "Statistics", "Pandas", "SQL"], ["data", "math"], "data_scientist"),
    (["HTML", "CSS", "JavaScript", "React", "TypeScript"], ["design"], "frontend_developer"),
    (["Linux", "Docker", "Kubernetes", "CI/CD", "AWS"], ["infrastructure"], "devops_engineer"),
    (["Figma", "UX Research", "Wireframing", "UI Design"], [], "ui_ux_designer"),
    (["Networking", "Network Security", "SIEM", "Ethical Hacking"], ["security"], "cybersecurity_analyst"),
    (["SEO", "Social Media Marketing", "Digital Advertising"], ["business"], "digital_marketer"),
])
def test_top_prediction(model, skills, interests, expected):
    result = model.predict(predictor.Profile(skills, interests, 0))
    assert result["suited"][0]["career_id"] == expected
    assert len(result["all"]) == len(result["all"]) and result["all"][0]["fit_score"] >= result["all"][-1]["fit_score"]


def test_model_quality_on_holdout(model):
    assert model.metrics["accuracy"] > 0.85
    assert model.metrics["top3_accuracy"] > 0.95


def test_experience_level():
    assert predictor.experience_level(0) == "fresher"
    assert predictor.experience_level(3) == "mid"
    assert predictor.experience_level(8) == "senior"


def test_gap_for_partial_profile():
    g = analyze_gap("backend_developer", ["Python", "Git"], 0)
    missing = {m["requirement"] for m in g["missing_core"]}
    assert "SQL" in missing and "REST APIs" in missing
    assert "Backend language" not in missing  # satisfied by Python
    assert 0 < g["readiness"] < 60
    assert g["roadmap"][0]["phase"].startswith("Phase 1")
    assert g["estimated_weeks"] > 0
    assert g["salary"] == g["salary_bands"]["fresher"]


def test_gap_complete_profile_is_ready():
    from app import knowledge

    career = knowledge.get_career("data_analyst")
    skills = sorted(knowledge.career_skill_set(career))
    g = analyze_gap("data_analyst", skills, 2)
    assert g["readiness"] == 100
    assert g["missing_core"] == [] and g["readiness_label"] == "Job ready"


def test_gap_unknown_career():
    with pytest.raises(KeyError):
        analyze_gap("astronaut", [], 0)
