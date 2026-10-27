from app import knowledge


def test_every_career_skill_is_in_taxonomy():
    known = set(knowledge.skills())
    for career in knowledge.careers():
        assert knowledge.career_skill_set(career) <= known, career["id"]


def test_careers_are_well_formed():
    ids = [c["id"] for c in knowledge.careers()]
    assert len(ids) == len(set(ids))
    for c in knowledge.careers():
        assert set(c["interests"]) <= set(knowledge.INTERESTS), c["id"]
        assert set(c["salary"]) == {"fresher", "mid", "senior"}
        assert all(r["weight"] in (1, 2, 3) for r in c["core"])
        assert c["scenarios"] and c["project_ideas"]


def test_question_bank_skills_exist_and_have_keywords():
    known = set(knowledge.skills())
    for skill, qs in knowledge.questions()["skills"].items():
        assert skill in known
        for q in qs:
            assert q["keywords"] and q["ideal"] and q["difficulty"] in ("easy", "medium", "hard")
