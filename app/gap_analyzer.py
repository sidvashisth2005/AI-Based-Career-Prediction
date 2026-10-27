"""Skill gap analysis: what a person has, what is missing for a target career, and a learning plan."""

from . import knowledge
from .predictor import experience_level, skill_match

PRIORITY_BY_WEIGHT = {3: "High", 2: "Medium", 1: "Low"}
HOURS_PER_WEEK_ASSUMED = 10


def readiness_label(score: float) -> str:
    if score >= 80:
        return "Job ready"
    if score >= 60:
        return "Almost there"
    if score >= 35:
        return "Building foundations"
    return "Just starting"


def analyze_gap(career_id: str, user_skills: list[str], experience_years: float = 0.0) -> dict:
    career = knowledge.get_career(career_id)
    if career is None:
        raise KeyError(career_id)
    have = set(user_skills)
    score, matched, _ = skill_match(career, have)

    core_status, missing = [], []
    for req in sorted(career["core"], key=lambda r: -r["weight"]):
        options = knowledge.requirement_options(req)
        hits = [s for s in options if s in have]
        entry = {
            "requirement": knowledge.requirement_label(req),
            "options": options,
            "weight": req["weight"],
            "priority": PRIORITY_BY_WEIGHT[req["weight"]],
            "status": "have" if hits else "missing",
            "matched": hits,
        }
        core_status.append(entry)
        if not hits:
            # For "any of" groups recommend the quickest option to learn.
            best = min(options, key=lambda s: knowledge.skill_info(s)["weeks"])
            info = knowledge.skill_info(best)
            missing.append({
                **entry,
                "recommended_skill": best,
                "alternatives": [o for o in options if o != best],
                "weeks": info["weeks"],
                "resource": info["resource"],
                "category": info["category"],
                "kind": "core",
            })

    missing_secondary = []
    for name in career.get("secondary", []):
        if name not in have:
            info = knowledge.skill_info(name)
            missing_secondary.append({
                "requirement": name, "recommended_skill": name, "priority": "Nice to have",
                "weeks": info["weeks"], "resource": info["resource"], "category": info["category"],
                "kind": "secondary",
            })

    relevant = knowledge.career_skill_set(career)
    transferable = [s for s in user_skills if s not in relevant]

    roadmap = _roadmap(missing, missing_secondary)
    # Optional phases (nice-to-have skills) are not needed to become job ready.
    total_weeks = sum(phase["weeks"] for phase in roadmap if not phase["optional"])
    readiness = round(100 * score, 1)
    level = experience_level(experience_years)
    return {
        "career_id": career["id"],
        "title": career["title"],
        "domain": career["domain"],
        "description": career["description"],
        "readiness": readiness,
        "readiness_label": readiness_label(readiness),
        "level": level,
        "salary": career["salary"][level],
        "salary_bands": career["salary"],
        "outlook": career["outlook"],
        "matched_skills": matched,
        "transferable_skills": transferable,
        "core_requirements": core_status,
        "missing_core": missing,
        "missing_secondary": missing_secondary,
        "roadmap": roadmap,
        "estimated_weeks": total_weeks,
        "hours_per_week_assumed": HOURS_PER_WEEK_ASSUMED,
        "roadmap_url": career.get("roadmap_url"),
        "project_ideas": career.get("project_ideas", []),
        "certifications": career.get("certifications", []),
    }


def _roadmap(missing_core: list[dict], missing_secondary: list[dict]) -> list[dict]:
    """Group missing skills into phases: must-haves first, then important, then nice-to-have."""
    phases = [
        ("Phase 1: Core foundations", [m for m in missing_core if m["weight"] == 3]),
        ("Phase 2: Important skills", [m for m in missing_core if m["weight"] < 3]),
        ("Phase 3: Stand out (optional)", missing_secondary[:4]),
    ]
    roadmap = []
    for title, items in phases:
        if not items:
            continue
        # Skills inside a phase can partly overlap; assume 70% of the sequential time.
        weeks = max(1, round(sum(i["weeks"] for i in items) * (0.7 if len(items) > 1 else 1)))
        roadmap.append({
            "phase": title,
            "skills": [i["recommended_skill"] for i in items],
            "weeks": weeks,
            "resources": [{"skill": i["recommended_skill"], "url": i["resource"]} for i in items],
            "optional": "optional" in title,
        })
    roadmap.append({
        "phase": "Phase 4: Prove it",
        "skills": ["Portfolio project", "Mock interviews"],
        "weeks": 3,
        "resources": [],
        "optional": False,
    })
    return roadmap
