# AI-Based Career Prediction

A web app that reads your resume and helps you choose and prepare for a career.

**Core features**

1. **Career prediction.** Ranks 24 career fields by how well they suit your skills, interests and experience.
2. **Available and suited fields.** Shows your top matches with the reasons behind each one, plus a table of every field with its fit score, demand outlook and indicative salary.
3. **Skill gap for a specific field.** Pick any field to see which required skills you have and which you lack, a readiness score, a phased learning roadmap with free resources, project ideas and certifications.
4. **Mock interview.** Questions are based on the field you pick and your resume. They check skills you claim, probe required skills you lack, ask about your own projects, and include an on-the-job scenario and a behavioral question. Each answer is scored with feedback and a model answer, and you get a final report.

**Extra features**

5. **Job description match (ATS check).** Paste any job posting to get an ATS-style match score, the skills and keywords from the job that your resume is missing, warnings about experience or degree requirements, and a guess at which career the job belongs to. With an AI key you also get a tailored resume summary and rewritten bullet points.
6. **Resume health score.** Every uploaded resume is scored out of 100 on ATS and recruiter best practices: contact details, sections, action verbs, quantified impact, length and weak phrases. Each failed check comes with a specific tip.
7. **"What if I learn…?" simulator.** On the skill-gap page, tick the skills you plan to learn and instantly see how your readiness, your rank for that career and your top career matches would change, and how long it would take.
8. **Voice interview mode.** Answer by speaking (🎤, in Chrome or Edge) and optionally have questions read aloud. A timer shows how long each answer takes.
9. **Progress tracking and PDF export.** Your interview scores are saved in your browser and shown as a trend. Gap reports, job-match reports and interview reports can be saved as PDF.

It runs fully offline. If you add a **Gemini API key** (or an Anthropic key), the AI writes personalised interview questions from your resume, grades answers against a rubric and tailors your resume to job descriptions.

## Quick start

```bash
git clone https://github.com/sidvashisth2005/AI-Based-Career-Prediction.git
cd AI-Based-Career-Prediction
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000. To try it quickly, upload `samples/sample_resume.pdf` (or `.txt`), and on the Job match step paste `samples/sample_job_description.txt`.

The trained model ships in `models/career_model.npz`. If you change the careers or skills in `app/data/`, the app retrains it automatically (about 2 seconds), or you can run `python -m scripts.train_model` and commit the new file.

### Turn on the AI interviewer with Gemini

1. Get a free API key from Google AI Studio: https://aistudio.google.com/apikey
2. Copy the example settings file:
   ```bash
   cp .env.example .env        # Windows: copy .env.example .env
   ```
3. Open `.env` and replace the placeholder on this line with your key:
   ```
   GEMINI_API_KEY=paste-your-gemini-api-key-here
   ```
4. Restart the app. The header badge changes from **Offline mode** to **AI: Gemini**.

The default model is `gemini-flash-latest`, which always points to Google's newest Flash model. To pin a specific model, set `GEMINI_MODEL` in `.env`. Claude is also supported: set `ANTHROPIC_API_KEY`, and use `LLM_PROVIDER=claude` if both keys are present (Gemini is preferred by default).

If an AI call fails (wrong key, no internet, quota exceeded), the app falls back to the offline engine for that step and shows the reason, so an interview never breaks halfway through. `.env` is in `.gitignore`, so your key is never committed.

### Deploy on Vercel

The app is ready for Vercel. `pyproject.toml` tells Vercel the entrypoint (`app.main:app`), and the web UI in `public/` is served from Vercel's CDN.

1. Push the repo to GitHub and import it at https://vercel.com/new. Leave the framework preset on auto-detect (FastAPI), with no build command.
2. Before deploying, open **Settings → Environment Variables** and add `GEMINI_API_KEY` with your key. Vercel does not read your local `.env` file.
3. Deploy. Open `https://<your-app>.vercel.app/api/health`: it should return `"status": "ok"`, and `"ai": {"provider": "gemini", ...}` if the key is set.

Notes for serverless hosting, already handled in the code:

- The disk is read-only, so the app never needs to write. It uses the shipped model, and if it has to retrain it keeps the model in memory or saves it under `/tmp`. (Writing the model file to disk is what caused the earlier `500 FUNCTION_INVOCATION_FAILED`.)
- Requests can reach different instances, so the browser keeps the interview state and sends it with each answer.
- Vercel rejects request bodies over 4.5 MB, so resume uploads are limited to 4 MB.
- scikit-learn and scipy are not used, which keeps the function bundle small and cold starts fast. The model runs in NumPy.

If a deployment still fails, open the deployment in Vercel, go to **Logs** and look for the Python traceback.

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
| Prediction model | `app/predictor.py` | Multinomial logistic (softmax) regression in NumPy over a multi-hot vector of skills and interests, trained on 9,600 synthetic profiles sampled from the knowledge base. Holdout accuracy is about 93% top-1 and 99% top-3 |
| Fit score | `app/predictor.py` | 55% weighted skill coverage + 25% ML confidence + 20% interest match. Without interests it is 65% / 35%. Each match shows its reasons |
| Gap analysis | `app/gap_analyzer.py` | Ranks missing skills by priority, recommends the quickest option for "any of" requirements, and builds a phased roadmap with time estimates |
| Interview | `app/interview/` | `offline.py` plans questions and scores answers by key-point coverage, depth and structure (STAR for behavioral), capping off-topic answers. `llm.py` calls Gemini or Claude with JSON-schema structured outputs. `engine.py` handles sessions and the report |
| Job match | `app/job_match.py` | Compares job skills and repeated job keywords with the resume (70% / 30%), flags experience and degree gaps, and runs the career model on the job's skills to name the role |
| Resume health | `app/resume_quality.py` | Ten weighted checks for ATS-friendliness and recruiter best practices |
| Web UI | `public/` | Plain HTML, CSS and JS with no build step. Supports light and dark mode and works on phones |

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
| POST | `/api/jobmatch` | `{job_description, resume_text, skills, use_ai}` → ATS match, gaps and AI tailoring |
| POST | `/api/whatif` | `{career_id, skills, add_skills}` → readiness and ranking before and after learning |

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

The tests cover the knowledge base, skill extraction and its false-positive cases, resume parsing (TXT, DOCX and a real PDF), prediction quality, gap analysis, the interview flow and scoring, resume health, job matching, the what-if simulator, all API endpoints, and both AI integrations. The Gemini and Claude tests run against mocked HTTP transports, so no key or network is needed.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | placeholder | Turns on the AI interviewer and resume tailoring with Gemini |
| `GEMINI_MODEL` | `gemini-flash-latest` | Gemini model |
| `ANTHROPIC_API_KEY` | placeholder | Alternative provider: Claude |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Claude model |
| `CLAUDE_EFFORT` | `medium` | `low`, `medium` or `high` |
| `LLM_PROVIDER` | `auto` | `auto` (Gemini, then Claude, then offline), `gemini`, `claude` or `off` |
| `LLM_TIMEOUT_SECONDS` | `120` | Timeout for each AI call |
| `MAX_UPLOAD_MB` | `4` | Resume upload limit (keep it under 4.5 on Vercel) |
| `SESSION_TTL_MINUTES` | `120` | How long interview sessions are kept |

## Limitations

- Salary ranges (INR LPA) and demand outlook are indicative and hand-curated. They are not live market data.
- Scanned (image-only) PDFs are not supported because there is no OCR. Use a text-based PDF, a DOCX file, or paste the text.
- Interview state is kept in the browser and sent with each answer, which is what lets it run on serverless hosts. A user could edit their own interview state, but that only affects their own practice scores.
- Without an AI key, answers are scored by key-point coverage and structure. This is useful for practice but it cannot judge correctness the way a human or an LLM can.
- Voice answers use the browser's built-in speech recognition, which works in Chrome and Edge but not Firefox. In Chrome the audio is processed by Google's speech service.
- The job-match score is an approximation of how ATS software ranks resumes; real ATS products differ from each other.

## Project structure

```
app/
  main.py              FastAPI app and routes
  config.py            Environment settings
  knowledge.py         Loads the JSON knowledge base
  skill_extractor.py   Skill detection and normalisation
  resume_parser.py     PDF/DOCX/TXT → profile
  resume_quality.py    Resume health score
  job_match.py         Job description match (ATS check)
  predictor.py         ML model and fit scoring
  gap_analyzer.py      Skill gap and roadmap
  interview/           offline.py, llm.py, engine.py
  data/                careers.json, skills.json, questions.json
public/                index.html, styles.css, app.js (served by Vercel's CDN or by FastAPI)
models/                career_model.npz (trained weights, about 15 KB)
scripts/train_model.py
pyproject.toml         dependencies and the Vercel entrypoint
samples/             sample resume (PDF + TXT) and job description
tests/
```
