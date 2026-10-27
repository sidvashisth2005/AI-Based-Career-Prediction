"""Career prediction: an ML classifier combined with explainable skill and interest matching.

The classifier is a multinomial logistic regression over a multi-hot vector of skills and
interests. It is trained on synthetic profiles sampled from the career knowledge base, so it
learns which combinations of skills are characteristic of each career (including skills that
the hand-written requirements do not list for that career).
"""

import logging
import random
from dataclasses import dataclass

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split

from . import knowledge
from .config import MODEL_DIR

log = logging.getLogger(__name__)

MODEL_PATH = MODEL_DIR / "career_model.joblib"
MODEL_VERSION = 1
GENERIC_SKILLS = ["Git", "Communication", "Problem Solving", "Excel", "Leadership", "Agile"]


def experience_level(years: float) -> str:
    if years < 1:
        return "fresher"
    if years < 5:
        return "mid"
    return "senior"


@dataclass
class Profile:
    skills: list[str]
    interests: list[str]
    experience_years: float = 0.0


def _feature_names() -> list[str]:
    return list(knowledge.skills()) + [f"interest:{i}" for i in knowledge.INTERESTS]


def _sample_profile(career: dict, all_skills: list[str], rng: random.Random) -> tuple[list[str], list[str]]:
    """Sample a plausible (skills, interests) profile for someone in ``career``."""
    skills = set()
    # Beginners know only part of the stack; this spread teaches the model partial profiles.
    strength = rng.uniform(0.35, 1.0)
    for req in career["core"]:
        p = {3: 0.9, 2: 0.75, 1: 0.6}[req["weight"]] * strength
        if rng.random() < p:
            options = knowledge.requirement_options(req)
            skills.add(rng.choice(options))
            if len(options) > 1 and rng.random() < 0.2:
                skills.add(rng.choice(options))
    for name in career.get("secondary", []):
        if rng.random() < 0.35 * strength:
            skills.add(name)
    for _ in range(rng.randint(0, 3)):  # unrelated skills picked up elsewhere
        skills.add(rng.choice(all_skills))
    for name in GENERIC_SKILLS:
        if rng.random() < 0.15:
            skills.add(name)
    interests = {i for i in career["interests"] if rng.random() < 0.7}
    if rng.random() < 0.4:
        interests.add(rng.choice(knowledge.INTERESTS))
    if rng.random() < 0.25:  # some users skip the interest question entirely
        interests = set()
    return sorted(skills), sorted(interests)


def generate_dataset(samples_per_career: int = 400, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    rng = random.Random(seed)
    features = _feature_names()
    index = {f: i for i, f in enumerate(features)}
    all_skills = list(knowledge.skills())
    rows, labels = [], []
    for career in knowledge.careers():
        for _ in range(samples_per_career):
            skills, interests = _sample_profile(career, all_skills, rng)
            vec = np.zeros(len(features), dtype=np.float32)
            for s in skills:
                vec[index[s]] = 1.0
            for i in interests:
                vec[index[f"interest:{i}"]] = 1.0
            rows.append(vec)
            labels.append(career["id"])
    return np.vstack(rows), np.array(labels)


def train(samples_per_career: int = 400, seed: int = 42, save: bool = True) -> dict:
    X, y = generate_dataset(samples_per_career, seed)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=seed, stratify=y)
    model = LogisticRegression(max_iter=3000, C=0.8)
    model.fit(X_train, y_train)
    accuracy = float(model.score(X_test, y_test))
    proba = model.predict_proba(X_test)
    top3 = np.argsort(proba, axis=1)[:, -3:]
    top3_accuracy = float(np.mean([y_test[i] in model.classes_[top3[i]] for i in range(len(y_test))]))
    bundle = {
        "model": model,
        "features": _feature_names(),
        "version": MODEL_VERSION,
        "metrics": {"accuracy": round(accuracy, 4), "top3_accuracy": round(top3_accuracy, 4), "samples": int(len(y))},
    }
    if save:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump(bundle, MODEL_PATH)
    return bundle


class CareerPredictor:
    def __init__(self, bundle: dict):
        self.model: LogisticRegression = bundle["model"]
        self.features: list[str] = bundle["features"]
        self.metrics: dict = bundle.get("metrics", {})
        self._index = {f: i for i, f in enumerate(self.features)}

    @classmethod
    def load_or_train(cls) -> "CareerPredictor":
        """Load the saved model; retrain if it is missing or out of date with the knowledge base."""
        if MODEL_PATH.exists():
            try:
                bundle = joblib.load(MODEL_PATH)
                if bundle.get("version") == MODEL_VERSION and bundle.get("features") == _feature_names() \
                        and set(bundle["model"].classes_) == set(knowledge.careers_by_id()):
                    return cls(bundle)
            except Exception as exc:  # corrupt file or incompatible sklearn version
                log.warning("Could not load saved model (%s); retraining", exc)
        log.info("Training career model")
        return cls(train())

    def _vector(self, profile: Profile) -> np.ndarray:
        vec = np.zeros((1, len(self.features)), dtype=np.float32)
        for s in profile.skills:
            if s in self._index:
                vec[0, self._index[s]] = 1.0
        for i in profile.interests:
            key = f"interest:{i}"
            if key in self._index:
                vec[0, self._index[key]] = 1.0
        return vec

    def probabilities(self, profile: Profile) -> dict[str, float]:
        proba = self.model.predict_proba(self._vector(profile))[0]
        return dict(zip(self.model.classes_, proba.tolist()))

    def predict(self, profile: Profile, top_k: int = 5) -> dict:
        user_skills = set(profile.skills)
        user_interests = set(profile.interests)
        proba = self.probabilities(profile)
        max_p = max(proba.values()) or 1.0
        level = experience_level(profile.experience_years)

        results = []
        for career in knowledge.careers():
            skill_score, matched, missing = skill_match(career, user_skills)
            ml_rel = proba[career["id"]] / max_p
            if user_interests:
                interest_score = len(user_interests & set(career["interests"])) / len(career["interests"])
                fit = 0.55 * skill_score + 0.25 * ml_rel + 0.20 * interest_score
            else:
                interest_score = None
                fit = 0.65 * skill_score + 0.35 * ml_rel
            results.append({
                "career_id": career["id"],
                "title": career["title"],
                "domain": career["domain"],
                "description": career["description"],
                "fit_score": round(100 * fit, 1),
                "skill_match": round(100 * skill_score, 1),
                "ml_confidence": round(100 * proba[career["id"]], 1),
                "interest_match": None if interest_score is None else round(100 * interest_score, 1),
                "matched_skills": matched,
                "missing_core": missing[:5],
                "salary": career["salary"][level],
                "outlook": career["outlook"],
                "reasons": _reasons(career, matched, user_interests, proba[career["id"]] / max_p),
            })
        results.sort(key=lambda r: r["fit_score"], reverse=True)
        return {"level": level, "suited": results[:top_k], "all": results}


def skill_match(career: dict, user_skills: set[str]) -> tuple[float, list[str], list[str]]:
    """Weighted coverage of core requirements (80%) and secondary skills (20%).

    Returns (score in 0..1, matched skill names, missing core requirement labels by importance).
    """
    total = covered = 0.0
    matched, missing = [], []
    for req in sorted(career["core"], key=lambda r: -r["weight"]):
        total += req["weight"]
        hits = [s for s in knowledge.requirement_options(req) if s in user_skills]
        if hits:
            covered += req["weight"]
            matched.extend(h for h in hits if h not in matched)
        else:
            missing.append(knowledge.requirement_label(req))
    secondary = career.get("secondary", [])
    sec_hits = [s for s in secondary if s in user_skills]
    matched.extend(s for s in sec_hits if s not in matched)
    core_score = covered / total if total else 0.0
    # Knowing about a third of the "nice to have" list already counts as full secondary credit.
    sec_score = min(1.0, len(sec_hits) / max(1.0, len(secondary) / 3)) if secondary else 0.0
    return 0.8 * core_score + 0.2 * sec_score, matched, missing


def _reasons(career: dict, matched: list[str], interests: set[str], ml_rel: float) -> list[str]:
    reasons = []
    if matched:
        reasons.append("You already have " + ", ".join(matched[:4]) + (" and more" if len(matched) > 4 else ""))
    shared = sorted(interests & set(career["interests"]))
    if shared:
        reasons.append("Matches your interest in " + ", ".join(shared))
    if ml_rel >= 0.6:
        reasons.append("Your overall skill mix closely resembles people in this role")
    if career["outlook"] in ("High", "Very High"):
        reasons.append(f"{career['outlook']} job market demand")
    return reasons
