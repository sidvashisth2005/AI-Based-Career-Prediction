"""Job-description match: how well a resume fits a specific job posting (an ATS-style check)."""

import re
from collections import Counter

from app import knowledge
from app.predictor import CareerPredictor, Profile
from app.resume_parser import detect_education
from app.skill_extractor import extract_skills

STOPWORDS = set("""
a about above across after again all also am an and any are as at be because been before being below between both but by
can could did do does doing down during each few for from further had has have having he her here hers him his how i if in
into is it its itself just me more most must my no nor not now of off on once only or other our ours out over own same she
should so some such than that the their them then there these they this those through to too under until up very was we
were what when where which while who whom why will with would you your yours
ability able across apply candidate candidates company etc experience good great help ideal including job join knowledge
looking new opportunity plus position preferred required requirements responsibilities role skills strong team teams
understanding using well work working years year year's within across environment based like make plus related
junior senior intern internship fresher hybrid remote onsite office location salary benefits apply hiring about
build building built ensure collaborate collaborating closely deliver million millions power powers welcome
familiarity hands-on hands excellent proven solid exposure least minimum degree bachelor bachelor's master's field
""".split())
EDUCATION_RANK = {"Higher Secondary": 1, "Diploma": 2, "Bachelors": 3, "Masters": 4, "PhD": 5}
YEARS_REQUIRED = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years?|yrs?)", re.I)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z][a-z+#.\-]{2,}", text.lower())


def _stem(word: str) -> str:
    word = word.strip(".-")
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def top_keywords(text: str, skills: list[str], limit: int = 12) -> list[str]:
    """Meaningful words a job description repeats, excluding skill names (those are scored separately).

    Words used at least twice are the strongest ATS signals; if there are too few, single
    mentions from bullet-point lines fill the list.
    """
    names = list(skills) + [a.lstrip("=") for s in skills for a in knowledge.skills().get(s, {}).get("aliases", [])]
    skill_words = {w for n in names for w in re.findall(r"[a-z0-9+#]+", n.lower())}

    def candidates(chunk: str) -> list[str]:
        return [w.strip(".-") for w in _words(chunk)
                if w.strip(".-") not in STOPWORDS and w.strip(".-") not in skill_words and len(w.strip(".-")) > 3]

    words = candidates(text)
    counts = Counter(_stem(w) for w in words)
    first_form = {}
    for w in words:
        first_form.setdefault(_stem(w), w)
    keywords = [first_form[st] for st, n in counts.most_common() if n >= 2]
    if len(keywords) < 6:
        bullets = "\n".join(ln for ln in text.splitlines() if ln.strip().startswith(("-", "•", "*", "●")))
        for w in candidates(bullets):
            if _stem(w) not in {_stem(k) for k in keywords}:
                keywords.append(w)
    return keywords[:limit]


def analyze_job_match(job_description: str, resume_text: str, profile_skills: list[str],
                      experience_years: float, predictor: CareerPredictor) -> dict:
    jd_skills = extract_skills(job_description)
    resume_skills = list(dict.fromkeys(extract_skills(resume_text) + list(profile_skills)))
    have = set(resume_skills)
    matched = [s for s in jd_skills if s in have]
    missing = [s for s in jd_skills if s not in have]

    keywords = top_keywords(job_description, jd_skills)
    resume_stems = {_stem(w) for w in _words(resume_text)}
    kw_matched = [k for k in keywords if _stem(k) in resume_stems]
    kw_missing = [k for k in keywords if k not in kw_matched]

    skill_score = len(matched) / len(jd_skills) if jd_skills else 0.0
    keyword_score = len(kw_matched) / len(keywords) if keywords else 0.0
    if jd_skills:
        match = 0.7 * skill_score + 0.3 * keyword_score
    else:
        match = keyword_score

    flags = []
    years = [int(m.group(1)) for m in YEARS_REQUIRED.finditer(job_description) if int(m.group(1)) <= 20]
    required_years = min(years) if years else None
    if required_years is not None and experience_years + 0.5 < required_years:
        flags.append(f"The job asks for about {required_years}+ years of experience; your profile shows {experience_years:g}.")
    jd_edu, cv_edu = detect_education(job_description), detect_education(resume_text)
    if jd_edu and cv_edu and EDUCATION_RANK[cv_edu] < EDUCATION_RANK[jd_edu]:
        flags.append(f"The job mentions a {jd_edu} degree; your resume shows {cv_edu}.")

    # Which career does this job look like? Run the career model on the job's own skills.
    role = None
    if jd_skills:
        prediction = predictor.predict(Profile(jd_skills, [], 0), top_k=1)["suited"][0]
        role = {"career_id": prediction["career_id"], "title": prediction["title"]}

    suggestions = []
    if missing:
        suggestions.append("If you genuinely have these skills, add them to your resume: " + ", ".join(missing[:6]) + ".")
        learn = sorted((s for s in missing if s in knowledge.skills()), key=lambda s: knowledge.skill_info(s)["weeks"])[:3]
        if learn:
            suggestions.append("Otherwise, these are the quickest wins to learn for this job: " + ", ".join(learn) + ".")
    if kw_missing:
        suggestions.append("Mirror the job's wording where it is true for you, e.g. " + ", ".join(kw_missing[:6]) + ".")
    if match < 0.5:
        suggestions.append("Tailor your summary and top project bullets to this job before applying.")

    score = round(100 * match)
    if score >= 75:
        label = "Strong match"
    elif score >= 50:
        label = "Moderate match"
    else:
        label = "Low match"
    return {
        "match_score": score,
        "label": label,
        "skill_score": round(100 * skill_score),
        "keyword_score": round(100 * keyword_score),
        "job_skills": jd_skills,
        "matched_skills": matched,
        "missing_skills": missing,
        "matched_keywords": kw_matched,
        "missing_keywords": kw_missing,
        "required_years": required_years,
        "flags": flags,
        "likely_role": role,
        "suggestions": suggestions,
        "resources": [{"skill": s, "url": knowledge.skill_info(s)["resource"]} for s in missing[:6]],
    }
