"""End-to-end check of every service of a running Career Compass deployment.

Usage:
    python -m scripts.smoke_test                       # http://localhost:8000
    python -m scripts.smoke_test https://your-app.vercel.app

Uses only the standard library, so it runs anywhere. Exits with status 1 if any check fails.
"""

import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
TIMEOUT = 180  # AI calls can take a while


class Checker:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.results: list[tuple[str, bool, str, float]] = []

    def request(self, method: str, path: str, body=None, headers=None):
        data, hdrs = None, dict(headers or {})
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        elif isinstance(body, bytes):
            data = body
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
                return resp.status, raw, resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers.get("Content-Type", "")

    def json(self, method: str, path: str, body=None, headers=None):
        status, raw, _ = self.request(method, path, body, headers)
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, {"raw": raw[:200].decode("utf-8", "replace")}

    def check(self, name: str, fn):
        start = time.time()
        try:
            detail = fn() or ""
            ok = True
        except AssertionError as exc:
            ok, detail = False, str(exc) or "assertion failed"
        except Exception as exc:  # network errors and the like
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        self.results.append((name, ok, str(detail)[:110], time.time() - start))
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<34} {time.time() - start:5.1f}s  {str(detail)[:90]}", flush=True)
        return ok


def multipart(field: str, filename: str, content: bytes, content_type: str) -> tuple[bytes, dict]:
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def run(base: str) -> bool:
    c = Checker(base)
    ctx: dict = {}
    print(f"Checking {c.base}\n")

    def health():
        status, h = c.json("GET", "/api/health")
        assert status == 200, f"status {status}: {h}"
        assert h["status"] == "ok"
        ctx["ai"] = h["ai"]["provider"]
        return f"AI provider: {h['ai']['label']}" + (f" ({h['ai']['model']})" if h["ai"]["model"] else "") + \
            (f" - {h['ai']['note']}" if h["ai"].get("note") else "")

    def meta():
        status, m = c.json("GET", "/api/meta")
        assert status == 200, f"status {status}: {m}"
        assert len(m["skills"]) > 100 and len(m["careers"]) >= 20 and m["interests"]
        return f"{len(m['careers'])} careers, {len(m['skills'])} skills"

    def careers():
        status, cs = c.json("GET", "/api/careers")
        assert status == 200 and len(cs) >= 20
        status, one = c.json("GET", "/api/careers/data_scientist")
        assert status == 200 and one["core"], f"status {status}"
        assert c.json("GET", "/api/careers/does_not_exist")[0] == 404
        return "list, detail and 404"

    def upload(name, ctype):
        def fn():
            body, headers = multipart("file", name, (SAMPLES / name).read_bytes(), ctype)
            status, r = c.json("POST", "/api/resume/parse", body, headers)
            assert status == 200, f"status {status}: {r}"
            assert {"Python", "SQL"} <= set(r["skills"]), r.get("skills")
            assert r["quality"]["score"] > 0
            ctx["resume"] = r
            return f"{len(r['skills'])} skills, education {r['education']}, health {r['quality']['score']}/100"
        return fn

    def predict():
        status, r = c.json("POST", "/api/predict", {"skills": ctx["resume"]["skills"], "interests": ["data", "math"],
                                                    "experience_years": ctx["resume"]["experience_years"]})
        assert status == 200, f"status {status}: {r}"
        assert r["suited"] and len(r["all"]) >= 20
        ctx["top"] = r["suited"][0]["career_id"]
        return f"top match {r['suited'][0]['title']} ({r['suited'][0]['fit_score']}%)"

    def gap():
        status, g = c.json("POST", "/api/gap", {"career_id": "ml_engineer", "skills": ctx["resume"]["skills"]})
        assert status == 200, f"status {status}: {g}"
        assert g["roadmap"] and 0 <= g["readiness"] <= 100
        return f"readiness {g['readiness']}%, {len(g['missing_core'])} core gaps"

    def whatif():
        status, w = c.json("POST", "/api/whatif", {"career_id": "ml_engineer", "skills": ctx["resume"]["skills"],
                                                   "add_skills": ["Deep Learning", "TensorFlow"]})
        assert status == 200, f"status {status}: {w}"
        assert w["after"]["readiness"] >= w["before"]["readiness"]
        return f"readiness {w['before']['readiness']}% -> {w['after']['readiness']}%"

    def jobmatch():
        jd = (SAMPLES / "sample_job_description.txt").read_text(encoding="utf-8")
        status, j = c.json("POST", "/api/jobmatch", {"job_description": jd, "resume_text": ctx["resume"]["text"],
                                                     "skills": ctx["resume"]["skills"], "use_ai": True})
        assert status == 200, f"status {status}: {j}"
        assert 0 <= j["match_score"] <= 100 and j["likely_role"]
        if ctx.get("ai"):
            assert j["ai"] or j["ai_error"], "AI enabled but no AI result or error"
        ai = "AI tips: yes" if j["ai"] else f"AI tips: no ({j['ai_error'] or 'offline'})"
        return f"ATS {j['match_score']}%, role {j['likely_role']['title']}; {ai}"

    def interview():
        status, s = c.json("POST", "/api/interview/start", {
            "career_id": ctx.get("top", "data_scientist"), "num_questions": 4, "difficulty": "medium",
            "profile": {"skills": ctx["resume"]["skills"], "projects": ctx["resume"]["projects"],
                        "experience_years": ctx["resume"]["experience_years"], "resume_text": ctx["resume"]["text"]}})
        assert status == 200, f"start status {status}: {s}"
        sid, state = s["session_id"], s["state"]
        answer = ("In my internship I built a churn model with scikit-learn; I used cross validation and "
                  "regularization because the model was overfitting, which improved recall by 18%.")
        for _ in range(s["total"]):
            status, r = c.json("POST", f"/api/interview/{sid}/answer", {"answer": answer, "state": state})
            assert status == 200, f"answer status {status}: {r}"
            state = r["state"]
        assert r["done"]
        status, rep = c.json("POST", f"/api/interview/{sid}/report", {"state": state})
        assert status == 200 and rep["complete"], f"report status {status}: {rep}"
        notes = f"; notice: {s['notices'][0][:60]}" if s["notices"] else ""
        return f"mode {s['mode']}, {s['total']} questions, score {rep['overall_score']}/10{notes}"

    def ui():
        for path, marker in (("/", b"Career Compass"), ("/app.js", b"postJSON"), ("/styles.css", b"--primary")):
            status, raw, _ = c.request("GET", path)
            assert status == 200 and marker in raw, f"{path}: status {status}"
        status, raw, _ = c.request("GET", "/docs")
        assert status == 200, f"/docs status {status}"
        return "index, app.js, styles.css, /docs"

    def errors():
        assert c.json("POST", "/api/predict", {"skills": ["juggling"]})[0] == 400
        assert c.json("POST", "/api/jobmatch", {"job_description": "short"})[0] == 422
        body, headers = multipart("file", "bad.exe", b"MZ", "application/octet-stream")
        assert c.json("POST", "/api/resume/parse", body, headers)[0] == 422
        return "400/422 handled as JSON"

    if not c.check("Health", health):
        print("\nThe API is not responding; skipping the remaining checks.")
        return False
    c.check("Metadata", meta)
    c.check("Career catalogue", careers)
    resume_ok = c.check("Resume upload (TXT)", upload("sample_resume.txt", "text/plain"))
    resume_ok = c.check("Resume upload (PDF)", upload("sample_resume.pdf", "application/pdf")) or resume_ok
    if resume_ok:
        c.check("Career prediction", predict)
        c.check("Skill gap", gap)
        c.check("What-if simulator", whatif)
        c.check("Job match (ATS)", jobmatch)
        c.check("Mock interview (full)", interview)
    c.check("Web UI and API docs", ui)
    c.check("Input validation", errors)

    failed = [r for r in c.results if not r[1]]
    print(f"\n{len(c.results) - len(failed)}/{len(c.results)} checks passed")
    return not failed


if __name__ == "__main__":
    sys.exit(0 if run(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000") else 1)
