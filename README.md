# AI-Based Career Prediction

A web app that reads your resume and helps you choose and prepare for a career. It has four parts:

1. **Career prediction.** Ranks 24 career fields by how well they suit your skills, interests and experience.
2. **Available and suited fields.** Shows your top matches with the reasons behind each one, plus a table of every field with its fit score, demand outlook and indicative salary.
3. **Skill gap for a specific field.** Pick any field to see which required skills you have and which you lack, a readiness score, a phased learning roadmap with free resources, project ideas and certifications.
4. **Mock interview.** Questions are based on the field you pick and your resume. They check skills you claim, probe required skills you lack, ask about your own projects, and include an on-the-job scenario and a behavioral question. Each answer is scored with feedback and a model answer, and you get a final report.

It runs fully offline. If you add an Anthropic API key, Claude writes personalised interview questions from your resume and grades answers against a rubric.

## Quick start

```bash
git clone https://github.com/sidvashisth2005/AI-Based-Career-Prediction.git
cd AI-Based-Career-Prediction
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000. To try it quickly, upload `samples/sample_resume.txt`.

The ML model trains automatically the first time the app starts (it takes a few seconds). To retrain it by hand, run `python -m scripts.train_model`.

### Optional: AI interviewer with Claude

```bash
cp .env.example .env
# then set ANTHROPIC_API_KEY=... in .env
```

The header badge shows **AI interviewer: on** when this is active. If a Claude call fails, the app falls back to the offline engine for that step, so an interview never breaks halfway through.

### Docker

```bash
docker build -t career-ai .
docker run -p 8000:8000 --env-file .env career-ai
```

## How it works

```
Resume (PDF/DOCX/TXT) ──► resume_parser ──► skills, education, experience, projects
                                │
Manual skills + interests ──────┤
                                ▼
                     ┌──────────────────────┐
                     │ predictor            │  ML model (logistic regression)
                     │  fit = skill match   │  + weighted skill coverage
                     │      + ML confidence │  + interest overlap
                     │      + interests     │
                     └──────────┬───────────┘
                                ▼
          gap_analyzer (per field) ──► readiness, missing skills, roadmap
                                ▼
          interview engine ──► questions (Claude or question bank) ──► scoring ──► report
```

| Component | File | Details |
|---|---|---|
| Knowledge base | `app/data/careers.json`, `skills.json`, `questions.json` | 24 careers with weighted core requirements (including "any of" groups such as *a backend language*), 121 skills with aliases, learning time and resources, and about 130 interview questions with key points and model answers |
| Skill extraction | `app/skill_extractor.py` | Alias matching with token boundaries, so `JavaScript` does not count as `Java`, `TF-IDF` does not count as `TensorFlow`, and `R&D` does not count as `R` |
| Resume parsing | `app/resume_parser.py` | Reads PDFs with pdfplumber (pypdf as a fallback), DOCX with python-docx; detects sections, education level, years of experience and project titles |
| Prediction model | `app/predictor.py` | Multinomial logistic regression over a multi-hot vector of skills and interests, trained on 9,600 synthetic profiles sampled from the knowledge base. Holdout accuracy is about 93% top-1 and 98% top-3 |
| Fit score | `app/predictor.py` | 55% weighted skill coverage + 25% ML confidence + 20% interest match. Without interests it is 65% / 35%. Each match shows its reasons |
| Gap analysis | `app/gap_analyzer.py` | Ranks missing skills by priority, recommends the quickest option for "any of" requirements, and builds a phased roadmap with time estimates |
| Interview | `app/interview/` | `offline.py` plans questions and scores answers by key-point coverage, depth and structure (STAR for behavioral). `llm.py` uses Claude with JSON-schema structured outputs. `engine.py` handles sessions and the report |
| Web UI | `frontend/` | Plain HTML, CSS and JS with no build step. Supports light and dark mode and works on phones |

### Training data

The model is trained on synthetic profiles because there is no public dataset that links skills to careers in this taxonomy. If you collect real, anonymised data from users (skills, interests and the career they chose), you can replace `generate_dataset()` in `app/predictor.py` with it and retrain. The knowledge base is plain JSON, so you can add careers or skills without touching code. A test checks that every skill a career references exists.

## API

Interactive docs are at http://localhost:8000/docs.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Status, interview engine, model metrics |
| GET | `/api/meta` | Skill list, interests and careers (for forms) |
| GET | `/api/careers`, `/api/careers/{id}` | Career catalogue |
| POST | `/api/resume/parse` | multipart `file` (PDF/DOCX/TXT) or form `text` → parsed profile |
| POST | `/api/predict` | `{skills, interests, experience_years}` → suited fields and all fields |
| POST | `/api/gap` | `{career_id, skills, experience_years}` → gap report and roadmap |
| POST | `/api/interview/start` | `{career_id, profile, num_questions, difficulty}` → first question |
| POST | `/api/interview/{id}/answer` | `{answer}` → evaluation and next question |
| GET | `/api/interview/{id}/report` | Final interview report |

Example:

```bash
curl -s localhost:8000/api/predict -H 'Content-Type: application/json' \
  -d '{"skills":["python","sql","machine learning","pandas"],"interests":["data"]}'
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests cover the knowledge base, skill extraction and its false-positive cases, resume parsing, prediction quality, gap analysis, the interview flow, all API endpoints, and the Claude integration (against a mocked HTTP transport, so no key or network is needed).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | not set | Turns on the Claude interviewer |
| `LLM_MODE` | `auto` | `auto`, `on` or `off` |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Model used for questions and grading |
| `CLAUDE_EFFORT` | `medium` | `low`, `medium` or `high` |
| `MAX_UPLOAD_MB` | `5` | Resume upload limit |
| `SESSION_TTL_MINUTES` | `120` | How long interview sessions are kept |

## Limitations

- Salary ranges (INR LPA) and demand outlook are indicative and hand-curated. They are not live market data.
- Scanned (image-only) PDFs are not supported because there is no OCR. Use a text-based PDF, a DOCX file, or paste the text.
- Interview sessions are stored in memory. Run a single worker, or move sessions to Redis for multi-worker deployments.
- Without Claude, answers are scored by key-point coverage and structure. This is useful for practice but it cannot judge correctness the way a human or an LLM can.

## Project structure

```
app/
  main.py              FastAPI app and routes
  config.py            Environment settings
  knowledge.py         Loads the JSON knowledge base
  skill_extractor.py   Skill detection and normalisation
  resume_parser.py     PDF/DOCX/TXT → profile
  predictor.py         ML model and fit scoring
  gap_analyzer.py      Skill gap and roadmap
  interview/           offline.py, llm.py, engine.py
  data/                careers.json, skills.json, questions.json
frontend/              index.html, styles.css, app.js
scripts/train_model.py
samples/sample_resume.txt
tests/
```
