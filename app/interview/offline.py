"""Offline interview engine: question planning from the question bank and rule-based answer scoring.

Used when no Claude API credentials are configured, and as a fallback if an API call fails.
"""

import math
import random
import re

from app import knowledge

DIFFICULTY_ORDER = {"easy": ["easy", "medium", "hard"], "medium": ["medium", "easy", "hard"], "hard": ["hard", "medium", "easy"]}
DONT_KNOW = re.compile(r"\b(i\s*(do\s*not|don'?t)\s*know|no idea|not sure|i have no clue|skip|pass)\b", re.IGNORECASE)
STAR_SIGNALS = {
    "situation": re.compile(r"\b(when|during|while|at my|in my|once|last year|semester|internship)\b", re.I),
    # "I/we" followed by a past-tense verb: regular (-ed) or a common irregular one.
    "action": re.compile(r"\b(i|we)\s+(\w+ed|built|led|took|made|wrote|ran|set|broke|gave|found|got|did|spoke|chose|drove|taught|began|brought|kept|met|sent|won)\b", re.I),
    "result": re.compile(r"(\d+\s*%|\b(result|resulted|improved|reduced|increased|achieved|saved|delivered|won|learned|learnt|outcome)\b)", re.I),
}
EXAMPLE_SIGNALS = re.compile(r"\b(for example|e\.g|such as|for instance|in my project|i used|i built|i implemented|like when)\b", re.I)
REASONING_SIGNALS = re.compile(r"\b(because|which means|so that|therefore|trade-?off|however|whereas|instead|depends)\b", re.I)


def _stem(word: str) -> str:
    for suffix in ("ations", "ation", "ings", "ing", "ies", "ed", "es", "s", "ly"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _tokens(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower())}


def keyword_hits(answer: str, keywords: list[str]) -> tuple[list[str], list[str]]:
    lowered = answer.lower()
    answer_tokens = _tokens(answer)
    hit, miss = [], []
    for kw in keywords:
        kw_tokens = _tokens(kw)
        if kw.lower() in lowered or (kw_tokens and kw_tokens <= answer_tokens):
            hit.append(kw)
        else:
            miss.append(kw)
    return hit, miss


def evaluate_answer(question: dict, answer: str) -> dict:
    """Score an answer out of 10 using keyword coverage, depth and structure."""
    answer = (answer or "").strip()
    words = len(answer.split())
    keywords = question.get("keywords", [])
    hit, miss = keyword_hits(answer, keywords)

    needed = max(2.0, 0.5 * len(keywords))  # covering about half the key points earns full marks
    coverage = min(1.0, len(hit) / needed) if keywords else min(1.0, words / 60)
    if words < 8:
        length = 0.1
    elif words < 25:
        length = 0.5
    elif words <= 300:
        length = 1.0
    else:
        length = 0.8

    behavioral = question.get("category") in ("behavioral", "introduction", "project")
    if behavioral:
        found = [name for name, rx in STAR_SIGNALS.items() if rx.search(answer)]
        structure = len(found) / len(STAR_SIGNALS)
    else:
        signals = int(bool(EXAMPLE_SIGNALS.search(answer))) + int(bool(REASONING_SIGNALS.search(answer)))
        structure = signals / 2
        found = []

    score = 10 * (0.6 * coverage + 0.2 * length + 0.2 * structure)
    if not answer:
        score = 0.0
    elif DONT_KNOW.search(answer) and words < 15:
        score = min(score, 1.5)
    elif keywords and not hit and len(keywords) >= 3:
        # A long, well-structured answer that touches none of the key points is probably off-topic.
        score = min(score, 3.0)
    score = round(score, 1)

    strengths, improvements = [], []
    if hit:
        strengths.append("Covered key points: " + ", ".join(hit[:6]))
    if length == 1.0:
        strengths.append("Good level of detail")
    if behavioral and len(found) == 3:
        strengths.append("Clear STAR structure (situation, action, result)")
    if not behavioral and structure == 1.0:
        strengths.append("Explained the reasoning and backed it with an example")

    if keywords and not hit and len(keywords) >= 3:
        improvements.append("Your answer does not seem to address this question; re-read it and answer it directly")
    if miss and coverage < 1.0:
        improvements.append("Consider mentioning: " + ", ".join(miss[:5]))
    if words < 25:
        improvements.append("Your answer is short; aim for 4-8 sentences with specifics")
    elif words > 300:
        improvements.append("Be more concise; lead with the key point, then support it")
    if behavioral and len(found) < 3:
        missing_parts = [p for p in STAR_SIGNALS if p not in found]
        improvements.append("Use the STAR method; add the " + " and ".join(missing_parts))
    if not behavioral and structure < 1.0:
        improvements.append("Explain why (trade-offs) and add a concrete example from your experience")

    return {
        "score": score,
        "max_score": 10,
        "strengths": strengths,
        "improvements": improvements,
        "matched_keywords": hit,
        "missing_keywords": miss,
        "model_answer": question.get("ideal", ""),
        "evaluator": "offline",
    }


def _bank_question(skill: str, difficulty: str, used: set[str], rng: random.Random) -> dict | None:
    pool = knowledge.questions()["skills"].get(skill, [])
    for level in DIFFICULTY_ORDER.get(difficulty, DIFFICULTY_ORDER["medium"]):
        options = [q for q in pool if q.get("difficulty", "medium") == level and q["question"] not in used]
        if options:
            return rng.choice(options)
    return None


def _technical(skill: str, career: dict, difficulty: str, used: set[str], rng: random.Random, claimed: bool) -> dict:
    q = _bank_question(skill, difficulty, used, rng)
    if q:
        text = q["question"]
        if claimed and rng.random() < 0.5:
            text = f"You list {skill} as one of your skills. {text}"
        return {"text": text, "category": "technical", "skill": skill, "keywords": q["keywords"], "ideal": q["ideal"], "bank_text": q["question"]}
    info = knowledge.skill_info(skill)
    concepts = info["concepts"] or [skill.lower()]
    return {
        "text": f"Explain the key concepts of {skill} and describe how you have used it, or would use it, as a {career['title']}.",
        "category": "technical",
        "skill": skill,
        "keywords": concepts[:8],
        "ideal": f"Cover the core ideas of {skill} ({', '.join(concepts[:6])}), give a concrete example of applying it, and mention best practices and pitfalls.",
    }


def plan_questions(career: dict, profile: dict, num_questions: int = 6, difficulty: str = "medium", seed: int | None = None) -> list[dict]:
    """Build an interview: introduction, technical (claimed + required skills), project, scenario, behavioral."""
    rng = random.Random(seed)
    num_questions = max(4, min(12, num_questions))
    user_skills = set(profile.get("skills", []))
    projects = profile.get("projects", [])
    core_skills = {o for req in career["core"] for o in knowledge.requirement_options(req)}
    matched_top = [s for s in profile.get("skills", []) if s in core_skills][:3]

    intro = {
        "text": f"Tell me about yourself and why you are interested in the {career['title']} role.",
        "category": "introduction",
        "skill": None,
        "keywords": ["experience", "project", "skills", "goal", "interest"] + [s.lower() for s in matched_top],
        "ideal": "Give a 60-90 second pitch: who you are, your most relevant experience or projects, the skills that fit this role, and why this role and company are your next step.",
    }

    if projects:
        project = rng.choice(projects)
        project_q = {
            "text": f"Your resume mentions \"{project}\". Walk me through it: the problem, your role, the tech stack, and the hardest challenge you solved.",
            "category": "project",
            "skill": None,
            "keywords": ["problem", "role", "architecture", "challenge", "result", "learned", "team"],
            "ideal": "Explain the problem and why it mattered, your specific contribution, the architecture and technology choices (and why), the hardest technical challenge and how you solved it, the measurable result, and what you would improve.",
        }
    else:
        project_q = {
            "text": f"Describe a project (academic, personal or professional) that best shows you are a good fit for a {career['title']} role.",
            "category": "project",
            "skill": None,
            "keywords": ["problem", "role", "tools", "challenge", "result", "learned"],
            "ideal": "Pick your most relevant project, state the problem, your role, the tools you used and why, a challenge you overcame and a measurable outcome.",
        }

    scenarios = career.get("scenarios", [])
    scenario_q = None
    if scenarios and num_questions >= 5:
        s = rng.choice(scenarios)
        scenario_q = {"text": s["question"], "category": "scenario", "skill": None, "keywords": s["keywords"], "ideal": s["ideal"]}

    behavioral = rng.choice(knowledge.questions()["behavioral"])
    behavioral_q = {"text": behavioral["question"], "category": "behavioral", "skill": None, "keywords": behavioral["keywords"], "ideal": behavioral["ideal"]}

    tech_slots = num_questions - 3 - (1 if scenario_q else 0)
    # Verify claimed skills first, then probe required skills the candidate lacks, then the rest.
    claimed, gaps = [], []
    for req in sorted(career["core"], key=lambda r: -r["weight"]):
        options = knowledge.requirement_options(req)
        hits = [o for o in options if o in user_skills]
        if hits:
            claimed.append(hits[0])
        else:
            gaps.append(min(options, key=lambda o: 0 if o in knowledge.questions()["skills"] else 1))
    claimed += [s for s in career.get("secondary", []) if s in user_skills]
    n_claimed = min(len(claimed), max(1, math.ceil(tech_slots * 0.6)))
    order = claimed[:n_claimed] + gaps + claimed[n_claimed:] + career.get("secondary", [])

    technical, used, seen = [], set(), set()
    for skill in order:
        if len(technical) >= tech_slots:
            break
        if skill in seen:
            continue
        seen.add(skill)
        q = _technical(skill, career, difficulty, used, rng, claimed=skill in user_skills)
        used.add(q.pop("bank_text", q["text"]))
        technical.append(q)

    plan = [intro, *technical, project_q]
    if scenario_q:
        plan.append(scenario_q)
    plan.append(behavioral_q)
    return plan[:num_questions]
