from app import knowledge
from app.interview import engine, offline


def _career():
    return knowledge.get_career("backend_developer")


def test_plan_structure_and_personalisation():
    profile = {"skills": ["Python", "Django", "Git"], "projects": ["Library API"], "experience_years": 0}
    plan = offline.plan_questions(_career(), profile, num_questions=7, difficulty="medium", seed=1)
    assert len(plan) == 7
    assert plan[0]["category"] == "introduction"
    assert plan[-1]["category"] == "behavioral"
    cats = [q["category"] for q in plan]
    assert "project" in cats and "scenario" in cats and cats.count("technical") == 3
    assert any("Library API" in q["text"] for q in plan)
    tested = {q["skill"] for q in plan if q["category"] == "technical"}
    assert "Python" in tested  # verifies a claimed skill
    assert tested & {"SQL", "REST APIs"}  # probes a missing required skill
    assert all(q["keywords"] for q in plan)


def test_plan_respects_bounds():
    assert len(offline.plan_questions(_career(), {}, num_questions=2, seed=0)) == 4
    assert len(offline.plan_questions(_career(), {}, num_questions=50, seed=0)) <= 12


def test_evaluation_rewards_good_answers():
    q = knowledge.questions()["skills"]["SQL"][0]
    question = {"text": q["question"], "category": "technical", "keywords": q["keywords"], "ideal": q["ideal"]}
    good = ("An INNER JOIN returns only the matching rows from both tables, while a LEFT JOIN returns all rows from the "
            "left table and NULL where there is no match. A RIGHT JOIN is the reverse and a FULL OUTER join keeps rows from "
            "both sides. For example, in my project I used customers LEFT JOIN orders to find customers without orders, "
            "because an inner join would have dropped them.")
    weak = "Join combines tables."
    g, w = offline.evaluate_answer(question, good), offline.evaluate_answer(question, weak)
    assert g["score"] >= 8 and w["score"] < 4
    assert g["matched_keywords"] and w["improvements"]
    assert offline.evaluate_answer(question, "")["score"] == 0
    assert offline.evaluate_answer(question, "I don't know")["score"] <= 1.5


def test_full_session_and_report():
    profile = {"skills": ["Python", "SQL"], "projects": [], "experience_years": 1}
    s = engine.start_interview("data_analyst", profile, num_questions=5, difficulty="easy")
    assert s.mode == "offline"
    for i in range(len(s.questions)):
        r = engine.submit_answer(s, "When I was an intern I built a dashboard and it improved reporting time by 30%.")
        assert r["done"] == (i == len(s.questions) - 1)
    report = engine.build_report(s)
    assert report["complete"] and report["answered"] == 5
    assert 0 <= report["overall_score"] <= 10
    assert report["verdict"] in ("Strong", "Promising", "Needs practice", "Not ready yet")
    assert set(report["category_scores"]) >= {"introduction", "behavioral"}
