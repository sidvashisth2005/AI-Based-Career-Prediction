"""Loads the career, skill and interview-question knowledge base."""

import json
from functools import lru_cache

from app.config import DATA_DIR

INTERESTS = [
    "coding", "data", "math", "design", "business", "communication", "security",
    "hardware", "research", "creativity", "infrastructure", "gaming", "finance",
    "writing", "management", "people",
]

DEFAULT_RESOURCE = "https://www.coursera.org/search?query={query}"


def _load(name: str):
    with open(DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def skills() -> dict:
    return _load("skills.json")


@lru_cache(maxsize=1)
def careers() -> list:
    return _load("careers.json")


@lru_cache(maxsize=1)
def careers_by_id() -> dict:
    return {c["id"]: c for c in careers()}


@lru_cache(maxsize=1)
def questions() -> dict:
    return _load("questions.json")


def get_career(career_id: str) -> dict | None:
    return careers_by_id().get(career_id)


def requirement_options(req: dict) -> list[str]:
    """A core requirement is either a single skill or an "any_of" group."""
    return req["any_of"] if "any_of" in req else [req["skill"]]


def requirement_label(req: dict) -> str:
    return req.get("label") or req.get("skill")


def career_skill_set(career: dict) -> set[str]:
    names = set(career.get("secondary", []))
    for req in career["core"]:
        names.update(requirement_options(req))
    return names


def skill_info(name: str) -> dict:
    info = skills().get(name, {})
    return {
        "name": name,
        "category": info.get("category", "Other"),
        "weeks": info.get("weeks", 3),
        "resource": info.get("resource") or DEFAULT_RESOURCE.format(query=name.replace(" ", "%20")),
        "concepts": info.get("concepts", []),
    }
