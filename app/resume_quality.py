"""Resume health check: ATS-friendliness and recruiter best practices, scored out of 100."""

import re

from .resume_parser import split_sections

ACTION_VERBS = {
    "achieved", "analysed", "analyzed", "architected", "automated", "built", "collaborated", "conducted",
    "created", "decreased", "delivered", "deployed", "designed", "developed", "drove", "engineered",
    "established", "generated", "implemented", "improved", "increased", "integrated", "launched", "led",
    "managed", "mentored", "migrated", "optimised", "optimized", "organised", "organized", "presented",
    "reduced", "researched", "resolved", "scaled", "spearheaded", "streamlined", "trained", "won", "wrote",
}
WEAK_PHRASES = ["responsible for", "worked on", "helped with", "involved in", "various", "etc", "hard working", "team player"]
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(\+?\d[\d\s-]{8,}\d)")
LINK = re.compile(r"(linkedin\.com|github\.com|gitlab\.com|portfolio|behance\.net|kaggle\.com|leetcode\.com)", re.I)
METRIC = re.compile(r"(\d+(\.\d+)?\s*(%|x\b|k\b|\+|lpa|users|ms|seconds|hours|rows|students|customers)|\b\d{2,}\b)", re.I)
PRONOUN = re.compile(r"\b(i|me|my)\b", re.I)


def _bullets(text: str) -> list[str]:
    return [ln.strip(" •●▪-–*\t") for ln in text.splitlines() if len(ln.split()) >= 4]


def assess_resume(text: str, skills: list[str] | None = None) -> dict:
    sections = split_sections(text)
    words = len(text.split())
    body = "\n".join(sections.get(k, "") for k in ("experience", "projects"))
    lines = _bullets(body)
    action_lines = [ln for ln in lines if ln.split()[0].lower().strip(",.:") in ACTION_VERBS]
    metric_lines = [ln for ln in lines if METRIC.search(ln)]
    lowered = text.lower()
    weak = [p for p in WEAK_PHRASES if re.search(rf"\b{re.escape(p)}\b", lowered)]
    pronouns = len(PRONOUN.findall(" ".join(lines)))
    skills = skills or []

    checks = [
        ("Contact details", 10, bool(EMAIL.search(text)) and bool(PHONE.search(text)),
         "Add a professional email and phone number at the top."),
        ("Professional links", 5, bool(LINK.search(text)),
         "Add LinkedIn and GitHub/portfolio links so recruiters can verify your work."),
        ("Education section", 10, "education" in sections, "Add an Education section with degree, institute, year and CGPA/percentage."),
        ("Skills section", 10, "skills" in sections, "Add a dedicated Skills section; ATS software looks for it."),
        ("Projects or experience", 15, "projects" in sections or "experience" in sections,
         "Add Projects and/or Experience sections; they carry the most weight for freshers."),
        ("Enough relevant skills", 10, len(skills) >= 8, "List at least 8 relevant tools and technologies you can discuss in an interview."),
        ("Action verbs", 10, bool(lines) and len(action_lines) >= max(2, len(lines) // 3),
         "Start bullet points with action verbs such as Built, Designed, Improved or Led."),
        ("Quantified impact", 15, len(metric_lines) >= 2,
         "Quantify results (for example 'reduced load time by 40%' or 'used by 500+ students')."),
        ("Good length", 10, 250 <= words <= 900,
         f"Your resume is short ({words} words); add detail on projects, internships and achievements (aim for 300-700 words)."
         if words < 250 else
         f"Your resume is long ({words} words); keep it to 1 page for freshers and 2 pages at most."),
        ("No weak phrases", 5, not weak,
         "Replace weak phrases (" + ", ".join(weak[:3]) + ") with specific achievements." if weak else ""),
    ]
    score = sum(weight for _, weight, ok, _ in checks if ok)
    if pronouns > 3:
        score = max(0, score - 5)
    tips = [tip for _, _, ok, tip in checks if not ok and tip]
    if pronouns > 3:
        tips.append("Avoid first-person pronouns (I, my) in bullet points.")

    if score >= 85:
        label = "Excellent"
    elif score >= 70:
        label = "Good"
    elif score >= 50:
        label = "Needs work"
    else:
        label = "Weak"
    return {
        "score": score,
        "label": label,
        "checks": [{"name": name, "weight": weight, "passed": ok} for name, weight, ok, _ in checks],
        "tips": tips,
        "stats": {
            "words": words,
            "bullets": len(lines),
            "action_verb_bullets": len(action_lines),
            "quantified_bullets": len(metric_lines),
        },
    }
