"""Career prediction: an ML classifier combined with explainable skill and interest matching.

The classifier is a multinomial logistic (softmax) regression over a multi-hot vector of skills
and interests, implemented in NumPy so the app stays small enough for serverless hosts. It is
trained on synthetic profiles sampled from the career knowledge base, so it learns which
combinations of skills are characteristic of each career (including skills that the
hand-written requirements do not list for that career).

The trained weights ship in ``models/career_model.npz``. If that file is missing or out of date
with the knowledge base, the model is retrained in memory (about a second) and saved wherever
the filesystem allows; a read-only filesystem is fine.
"""

import json
import logging
import random
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app import knowledge
from app.config import MODEL_DIR

log = logging.getLogger(__name__)

MODEL_FILE = "career_model.npz"
MODEL_PATH = MODEL_DIR / MODEL_FILE
MODEL_VERSION = 2
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


def _class_names() -> list[str]:
    return [c["id"] for c in knowledge.careers()]


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
    """Return (X multi-hot features, y class indices into _class_names())."""
    rng = random.Random(seed)
    features = _feature_names()
    index = {f: i for i, f in enumerate(features)}
    all_skills = list(knowledge.skills())
    rows, labels = [], []
    for label, career in enumerate(knowledge.careers()):
        for _ in range(samples_per_career):
            skills, interests = _sample_profile(career, all_skills, rng)
            vec = np.zeros(len(features), dtype=np.float32)
            for s in skills:
                vec[index[s]] = 1.0
            for i in interests:
                vec[index[f"interest:{i}"]] = 1.0
            rows.append(vec)
            labels.append(label)
    return np.vstack(rows), np.array(labels, dtype=np.int64)


def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def fit_softmax(X: np.ndarray, y: np.ndarray, n_classes: int, l2: float = 1e-3,
                steps: int = 400, lr: float = 0.05, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Full-batch multinomial logistic regression with L2 regularisation, optimised with Adam."""
    rng = np.random.default_rng(seed)
    n, d = X.shape
    W = rng.normal(0, 0.01, (d, n_classes)).astype(np.float64)
    b = np.zeros(n_classes)
    Y = np.eye(n_classes)[y]
    m = [np.zeros_like(W), np.zeros_like(b)]
    v = [np.zeros_like(W), np.zeros_like(b)]
    beta1, beta2, eps = 0.9, 0.999, 1e-8
    for t in range(1, steps + 1):
        P = _softmax(X @ W + b)
        G = (P - Y) / n
        grads = [X.T @ G + l2 * W, G.sum(axis=0)]
        for i, (param, g) in enumerate(zip((W, b), grads)):
            m[i] = beta1 * m[i] + (1 - beta1) * g
            v[i] = beta2 * v[i] + (1 - beta2) * g * g
            param -= lr * (m[i] / (1 - beta1 ** t)) / (np.sqrt(v[i] / (1 - beta2 ** t)) + eps)
    return W, b


def train(samples_per_career: int = 400, seed: int = 42, save: bool = True) -> dict:
    X, y = generate_dataset(samples_per_career, seed)
    order = np.random.default_rng(seed).permutation(len(y))
    split = int(len(y) * 0.8)
    tr, te = order[:split], order[split:]
    classes = _class_names()
    W, b = fit_softmax(X[tr], y[tr], len(classes), seed=seed)

    proba = _softmax(X[te] @ W + b)
    accuracy = float(np.mean(proba.argmax(axis=1) == y[te]))
    top3 = np.argsort(proba, axis=1)[:, -3:]
    top3_accuracy = float(np.mean([y[te][i] in top3[i] for i in range(len(te))]))
    bundle = {
        "W": W.astype(np.float32),
        "b": b.astype(np.float32),
        "features": _feature_names(),
        "classes": classes,
        "version": MODEL_VERSION,
        "metrics": {"accuracy": round(accuracy, 4), "top3_accuracy": round(top3_accuracy, 4), "samples": int(len(y))},
    }
    if save:
        save_bundle(bundle)
    return bundle


def save_bundle(bundle: dict, path: Path | None = None) -> Path | None:
    """Save the model; fall back to the temp dir on read-only filesystems (e.g. serverless)."""
    targets = [path] if path else [MODEL_PATH, Path(tempfile.gettempdir()) / MODEL_FILE]
    for target in targets:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "wb") as f:
                np.savez_compressed(
                    f, W=bundle["W"], b=bundle["b"],
                    features=np.array(bundle["features"]), classes=np.array(bundle["classes"]),
                    meta=np.array(json.dumps({"version": bundle["version"], "metrics": bundle["metrics"]})),
                )
            return target
        except OSError as exc:
            log.info("Could not save model to %s (%s)", target, exc)
    return None


def load_bundle(path: Path) -> dict:
    with np.load(path, allow_pickle=False) as data:
        meta = json.loads(str(data["meta"]))
        return {
            "W": data["W"], "b": data["b"],
            "features": [str(f) for f in data["features"]],
            "classes": [str(c) for c in data["classes"]],
            "version": meta["version"], "metrics": meta["metrics"],
        }


class CareerPredictor:
    def __init__(self, bundle: dict):
        self.W: np.ndarray = bundle["W"]
        self.b: np.ndarray = bundle["b"]
        self.features: list[str] = bundle["features"]
        self.classes: list[str] = bundle["classes"]
        self.metrics: dict = bundle.get("metrics", {})
        self._index = {f: i for i, f in enumerate(self.features)}

    @classmethod
    def load_or_train(cls) -> "CareerPredictor":
        """Load the saved model; retrain if it is missing or out of date with the knowledge base."""
        for path in (MODEL_PATH, Path(tempfile.gettempdir()) / MODEL_FILE):
            if not path.exists():
                continue
            try:
                bundle = load_bundle(path)
            except Exception as exc:  # corrupt or old-format file
                log.warning("Could not load model from %s (%s)", path, exc)
                continue
            if bundle["version"] == MODEL_VERSION and bundle["features"] == _feature_names() \
                    and bundle["classes"] == _class_names():
                return cls(bundle)
            log.info("Saved model at %s is out of date with the knowledge base", path)
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
        proba = _softmax(self._vector(profile) @ self.W + self.b)[0]
        return dict(zip(self.classes, proba.tolist()))

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
