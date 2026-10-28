"""Finds known skills in free text (resumes, answers) using the alias taxonomy."""

import re
from functools import lru_cache

from app import knowledge

# Characters that, when adjacent to an alias, mean we are inside a longer token
# (e.g. "c" inside "c++" or "java" inside "javascript").
_LEFT = r"(?<![a-z0-9+#.])"
_RIGHT = r"(?![a-z0-9+#])"
# Case-sensitive aliases (prefixed with "=" in skills.json) are short and ambiguous,
# such as "C", "R" or "Go", so they use stricter boundaries.
_LEFT_STRICT = r"(?<![A-Za-z0-9+#.\-/&])"
_RIGHT_STRICT = r"(?![A-Za-z0-9+#\-&'.])"


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[str, re.Pattern]]:
    compiled = []
    for name, info in knowledge.skills().items():
        loose, strict = [name.lower()], []
        for alias in info.get("aliases", []):
            if alias.startswith("="):
                strict.append(alias[1:])
            else:
                loose.append(alias.lower())
        # Longest aliases first so "react native" wins over "react" in alternation.
        if name in strict:
            loose.remove(name.lower())
        loose = sorted(set(loose), key=len, reverse=True)
        if loose:
            compiled.append((name, re.compile(_LEFT + "(?:" + "|".join(map(re.escape, loose)) + ")" + _RIGHT)))
        if strict:
            pattern = _LEFT_STRICT + "(?:" + "|".join(map(re.escape, strict)) + ")" + _RIGHT_STRICT
            compiled.append((name, re.compile(pattern)))
    return compiled


@lru_cache(maxsize=1)
def _lookup() -> dict[str, str]:
    table = {}
    for name, info in knowledge.skills().items():
        table[name.lower()] = name
        for alias in info.get("aliases", []):
            table[alias.lstrip("=").lower()] = name
    return table


def extract_skills(text: str) -> list[str]:
    """Return canonical skill names found in ``text``, most frequently mentioned first."""
    if not text:
        return []
    lowered = text.lower()
    counts: dict[str, int] = {}
    first_pos: dict[str, int] = {}
    for name, pattern in _patterns():
        haystack = text if pattern.pattern.startswith(_LEFT_STRICT) else lowered
        matches = list(pattern.finditer(haystack))
        if matches:
            counts[name] = counts.get(name, 0) + len(matches)
            first_pos[name] = min(first_pos.get(name, len(text)), matches[0].start())
    return sorted(counts, key=lambda n: (-counts[n], first_pos[n]))


def normalize_skill(raw: str) -> str | None:
    """Map a user-typed skill ("reactjs", "ML") to its canonical name, if known."""
    key = raw.strip().lower()
    if not key:
        return None
    if key in _lookup():
        return _lookup()[key]
    found = extract_skills(raw)
    return found[0] if found else None


def normalize_skills(raw_skills: list[str]) -> tuple[list[str], list[str]]:
    """Split user-provided skills into (recognised canonical names, unrecognised inputs)."""
    known, unknown = [], []
    for raw in raw_skills:
        name = normalize_skill(raw)
        if name:
            if name not in known:
                known.append(name)
        elif raw.strip() and raw.strip() not in unknown:
            unknown.append(raw.strip())
    return known, unknown
