"use strict";

const state = {
  meta: null,
  profile: { skills: [], interests: [], experience_years: 0, education: "", projects: [], resume_text: "" },
  prediction: null,
  interview: null,
};

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? esc(u) : "#");
const titleCase = (s) => s.charAt(0).toUpperCase() + s.slice(1);

// ---------- persistence (per-browser convenience only) ----------
function saveProfile() {
  try { localStorage.setItem("career-profile", JSON.stringify(state.profile)); } catch (_) { /* storage unavailable */ }
}
function loadProfile() {
  try {
    const raw = localStorage.getItem("career-profile");
    if (raw) Object.assign(state.profile, JSON.parse(raw));
  } catch (_) { /* ignore */ }
}

// ---------- helpers ----------
async function api(path, options = {}) {
  const res = await fetch(path, options);
  let data = null;
  try { data = await res.json(); } catch (_) { /* non-JSON */ }
  if (!res.ok) {
    const detail = data && data.detail;
    const msg = Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : detail || `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return data;
}
const postJSON = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 3200);
}

async function withBusy(btn, label, fn) {
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span>${esc(label)}`;
  try { return await fn(); } finally { btn.disabled = false; btn.innerHTML = original; }
}

function ring(value, big = false, label = null) {
  const v = Math.max(0, Math.min(100, Math.round(value)));
  return `<div class="ring${big ? " big" : ""}" style="--v:${v}"><span>${label ?? v + "%"}</span></div>`;
}
function metric(name, value) {
  if (value === null || value === undefined) return "";
  return `<div class="metric"><span>${esc(name)}</span><div class="bar"><i style="width:${Math.min(100, value)}%"></i></div><b>${Math.round(value)}%</b></div>`;
}
const chips = (items, cls = "") => items.map((s) => `<span class="chip ${cls}">${esc(s)}</span>`).join("");

function show(view) {
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  document.querySelectorAll(".step").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// ---------- profile ----------
function renderSkills() {
  $("#skill-chips").innerHTML = state.profile.skills
    .map((s, i) => `<span class="chip">${esc(s)}<button aria-label="Remove ${esc(s)}" data-i="${i}">×</button></span>`)
    .join("");
}
function addSkill(raw) {
  const value = raw.trim();
  if (!value) return;
  const known = state.meta.skills.find((s) => s.toLowerCase() === value.toLowerCase());
  const name = known || value;
  if (!state.profile.skills.some((s) => s.toLowerCase() === name.toLowerCase())) state.profile.skills.push(name);
  renderSkills();
  saveProfile();
}
function renderInterests() {
  $("#interest-chips").innerHTML = state.meta.interests
    .map((i) => `<button type="button" class="chip ${state.profile.interests.includes(i) ? "on" : ""}" data-interest="${esc(i)}" aria-pressed="${state.profile.interests.includes(i)}">${esc(titleCase(i))}</button>`)
    .join("");
}

function applyResume(parsed) {
  const added = parsed.skills.filter((s) => !state.profile.skills.includes(s));
  state.profile.skills.push(...added);
  state.profile.projects = parsed.projects || [];
  state.profile.resume_text = parsed.text || "";
  if (parsed.experience_years) {
    state.profile.experience_years = parsed.experience_years;
    $("#experience").value = parsed.experience_years;
  }
  if (parsed.education) {
    state.profile.education = parsed.education;
    $("#education").value = parsed.education;
  }
  renderSkills();
  saveProfile();
  const box = $("#resume-summary");
  box.classList.remove("hidden");
  box.innerHTML = `<b>Resume analysed</b> (${parsed.word_count} words)
    <ul>
      <li>${parsed.skills.length} skills detected${added.length ? `, ${added.length} added to your profile` : ""}</li>
      <li>Education: ${esc(parsed.education || "not detected")}</li>
      <li>Experience: ${parsed.experience_years ? esc(parsed.experience_years) + " years" : "fresher / not detected"}</li>
      <li>Projects: ${parsed.projects.length ? esc(parsed.projects.join("; ")) : "none detected"}</li>
    </ul>`;
}

async function parseResume(formData, btn) {
  const run = async () => {
    try {
      applyResume(await api("/api/resume/parse", { method: "POST", body: formData }));
      toast("Resume analysed");
    } catch (e) {
      toast(e.message);
    }
  };
  if (btn) return withBusy(btn, "Analysing…", run);
  $("#dropzone").classList.add("drag");
  await run();
  $("#dropzone").classList.remove("drag");
}

// ---------- prediction ----------
async function predict() {
  const msg = $("#profile-msg");
  msg.textContent = "";
  msg.className = "msg";
  state.profile.experience_years = parseFloat($("#experience").value) || 0;
  state.profile.education = $("#education").value;
  saveProfile();
  if (!state.profile.skills.length && !state.profile.interests.length) {
    msg.textContent = "Add some skills (or upload a resume) first.";
    msg.className = "msg error";
    return;
  }
  await withBusy($("#predict-btn"), "Predicting…", async () => {
    try {
      state.prediction = await postJSON("/api/predict", {
        skills: state.profile.skills, interests: state.profile.interests,
        experience_years: state.profile.experience_years, education: state.profile.education || null, top_k: 6,
      });
      renderMatches();
      show("matches");
    } catch (e) {
      msg.textContent = e.message;
      msg.className = "msg error";
    }
  });
}

function renderMatches() {
  const p = state.prediction;
  const unknown = p.unrecognized_skills.length ? ` Not recognised (ignored): ${esc(p.unrecognized_skills.join(", "))}.` : "";
  $("#matches-lead").innerHTML = `Based on ${p.recognized_skills.length} recognised skills${p.interests.length ? " and " + p.interests.length + " interests" : ""} · experience level: <b>${esc(titleCase(p.level))}</b>.${unknown}`;
  $("#top-matches").innerHTML = p.suited.map((c, i) => `
    <article class="card match-card">
      <div class="match-head">
        ${ring(c.fit_score)}
        <div><div class="rank">#${i + 1} MATCH</div><h3>${esc(c.title)}</h3><small>${esc(c.domain)}</small></div>
      </div>
      <div class="metrics">
        ${metric("Skill match", c.skill_match)}
        ${metric("AI confidence", c.ml_confidence)}
        ${metric("Interest match", c.interest_match)}
      </div>
      ${c.reasons.length ? `<ul class="reasons">${c.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
      ${c.missing_core.length ? `<div><small class="hint">Top gaps</small><div class="chips">${chips(c.missing_core, "bad")}</div></div>` : ""}
      <div class="meta-line"><span>💰 ${esc(c.salary)}</span><span>📈 ${esc(c.outlook)} demand</span></div>
      <div class="card-actions">
        <button class="btn secondary small" data-gap="${esc(c.career_id)}">Skill gap</button>
        <button class="btn ghost small" data-interview="${esc(c.career_id)}">Practise interview</button>
      </div>
    </article>`).join("");
  $("#all-fields-card").hidden = false;
  $("#all-fields tbody").innerHTML = p.all.map((c) => `
    <tr data-gap="${esc(c.career_id)}">
      <td><b>${esc(c.title)}</b></td><td>${esc(c.domain)}</td>
      <td><span class="bar"><i style="width:${c.fit_score}%"></i></span>${Math.round(c.fit_score)}%</td>
      <td class="hide-sm">${Math.round(c.skill_match)}%</td>
      <td class="hide-sm">${esc(c.outlook)}</td><td class="hide-sm">${esc(c.salary)}</td>
    </tr>`).join("");
}

// ---------- gap ----------
async function runGap(careerId) {
  if (careerId) $("#gap-career").value = careerId;
  show("gap");
  const out = $("#gap-result");
  await withBusy($("#gap-btn"), "Analysing…", async () => {
    try {
      const g = await postJSON("/api/gap", { career_id: $("#gap-career").value, skills: state.profile.skills, experience_years: state.profile.experience_years });
      out.innerHTML = renderGap(g);
    } catch (e) {
      out.innerHTML = `<div class="card empty">${esc(e.message)}</div>`;
    }
  });
}

function renderGap(g) {
  const req = g.core_requirements.map((r) => `
    <li class="${r.status}">
      <span class="icon">${r.status === "have" ? "✓" : "✕"}</span>
      <span class="name">${esc(r.requirement)}${r.options.length > 1 ? `<br><small>any of: ${esc(r.options.join(", "))}</small>` : ""}</span>
      ${r.status === "have" ? `<span class="badge good">${esc(r.matched.join(", "))}</span>` : `<span class="badge ${r.priority.toLowerCase()}">${esc(r.priority)} priority</span>`}
    </li>`).join("");
  const missing = [...g.missing_core, ...g.missing_secondary.slice(0, 6)].map((m) => `
    <li class="missing">
      <span class="icon">+</span>
      <span class="name">${esc(m.recommended_skill)}${m.alternatives && m.alternatives.length ? `<br><small>or ${esc(m.alternatives.join(", "))}</small>` : ""}</span>
      <span class="badge ${m.kind === "core" ? m.priority.toLowerCase() : "nice"}">${esc(m.priority)}</span>
      <small>~${m.weeks} wk</small>
      <a href="${safeUrl(m.resource)}" target="_blank" rel="noopener">Learn</a>
    </li>`).join("");
  const roadmap = g.roadmap.map((p) => `
    <li><b>${esc(p.phase)}</b> <span class="when">· ~${p.weeks} weeks</span>
      <div>${esc(p.skills.join(", "))}</div>
      ${p.resources.length ? `<div>${p.resources.map((r) => `<a href="${safeUrl(r.url)}" target="_blank" rel="noopener">${esc(r.skill)}</a>`).join(" · ")}</div>` : ""}
    </li>`).join("");
  return `
    <div class="card gap-hero">
      ${ring(g.readiness, true)}
      <div class="info">
        <h2>${esc(g.title)} <span class="badge muted">${esc(g.domain)}</span></h2>
        <p><b>${esc(g.readiness_label)}</b> · ${g.missing_core.length} core gap${g.missing_core.length === 1 ? "" : "s"} · about <b>${g.estimated_weeks} weeks</b> to close the required gaps and build a portfolio (~${g.hours_per_week_assumed} h/week)</p>
        <div class="meta-line"><span>💰 ${esc(titleCase(g.level))}: ${esc(g.salary)}</span><span>📈 ${esc(g.outlook)} demand</span>${g.roadmap_url ? `<a href="${safeUrl(g.roadmap_url)}" target="_blank" rel="noopener">Full roadmap ↗</a>` : ""}</div>
      </div>
      <button class="btn primary" data-interview="${esc(g.career_id)}">Practise interview</button>
    </div>
    <div class="grid two">
      <div class="card"><h2>Core requirements</h2><ul class="req-list">${req}</ul></div>
      <div class="card"><h2>Skills to learn</h2>${missing ? `<ul class="req-list">${missing}</ul>` : `<p class="empty">No gaps. You meet every listed requirement 🎉</p>`}</div>
    </div>
    <div class="grid two">
      <div class="card"><h2>Learning roadmap</h2><ol class="timeline">${roadmap}</ol></div>
      <div class="card">
        <h2>Build your portfolio</h2><ul class="plain">${g.project_ideas.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>
        <h3 style="margin-top:1rem">Recommended certifications</h3><ul class="plain">${g.certifications.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>
        ${g.matched_skills.length ? `<h3 style="margin-top:1rem">You already have</h3><div class="chips">${chips(g.matched_skills, "good")}</div>` : ""}
        ${g.transferable_skills.length ? `<h3 style="margin-top:1rem">Other skills you bring</h3><div class="chips">${chips(g.transferable_skills, "plain")}</div>` : ""}
      </div>
    </div>`;
}

// ---------- interview ----------
function openInterview(careerId) {
  if (careerId) $("#iv-career").value = careerId;
  show("interview");
}

async function startInterview() {
  const msg = $("#iv-msg");
  msg.textContent = "";
  await withBusy($("#iv-start"), "Preparing questions…", async () => {
    try {
      const s = await postJSON("/api/interview/start", {
        career_id: $("#iv-career").value,
        difficulty: $("#iv-difficulty").value,
        num_questions: parseInt($("#iv-count").value, 10) || 6,
        profile: { skills: state.profile.skills, projects: state.profile.projects, experience_years: state.profile.experience_years, resume_text: state.profile.resume_text || null },
      });
      state.interview = s;
      $("#interview-setup").hidden = true;
      $("#interview-live").hidden = false;
      $("#interview-report").innerHTML = "";
      $("#iv-thread").innerHTML = `<div class="bubble"><b>${esc(s.title)} interview</b> · ${s.total} questions · ${s.mode === "claude" ? '<span class="badge ai">AI interviewer</span>' : '<span class="badge muted">Offline question bank</span>'}
        ${s.notices.map((n) => `<p class="hint">${esc(n)}</p>`).join("")}</div>`;
      askQuestion(s.question);
    } catch (e) {
      msg.textContent = e.message;
      msg.className = "msg error";
    }
  });
}

function askQuestion(q) {
  state.interview.current = q;
  $("#iv-progress").style.width = `${(q.index / q.total) * 100}%`;
  $("#iv-thread").insertAdjacentHTML("beforeend", `
    <div class="bubble q"><span class="tag">Question ${q.number} of ${q.total} · ${esc(q.category)}${q.skill ? " · " + esc(q.skill) : ""}</span><p>${esc(q.text)}</p></div>`);
  $("#iv-answer").value = "";
  $("#iv-words").textContent = "0 words";
  $("#iv-answer-box").hidden = false;
  $("#iv-answer").focus({ preventScroll: true });
  $("#iv-answer-box").scrollIntoView({ behavior: "smooth", block: "end" });
}

function feedbackHtml(ev) {
  const level = ev.score >= 7 ? "" : ev.score >= 4.5 ? "mid" : "low";
  return `<div class="bubble feedback ${level}">
    <span class="score">${ev.score}/10</span> <span class="hint">${ev.evaluator === "claude" ? "AI feedback" : "Automatic feedback"}</span>
    ${ev.strengths.length ? `<div><b>What went well</b><ul>${ev.strengths.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></div>` : ""}
    ${ev.improvements.length ? `<div><b>How to improve</b><ul>${ev.improvements.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></div>` : ""}
    ${ev.evaluator === "claude" && ev.missing_keywords.length ? `<div><b>Missed points</b><ul>${ev.missing_keywords.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></div>` : ""}
    ${ev.model_answer ? `<details><summary>See a strong answer</summary><p>${esc(ev.model_answer)}</p></details>` : ""}
  </div>`;
}

async function submitAnswer(skip = false) {
  const answer = skip ? "" : $("#iv-answer").value.trim();
  if (!skip && !answer) { toast("Type an answer or press Skip"); return; }
  const btn = $("#iv-submit");
  await withBusy(btn, "Evaluating…", async () => {
    try {
      const r = await postJSON(`/api/interview/${state.interview.session_id}/answer`, { answer });
      $("#iv-thread").insertAdjacentHTML("beforeend", `<div class="bubble a">${answer ? esc(answer) : "<i>(skipped)</i>"}</div>${feedbackHtml(r.evaluation)}`);
      if (r.done) finishInterview();
      else askQuestion(r.next_question);
    } catch (e) {
      toast(e.message);
    }
  });
}

async function finishInterview() {
  $("#iv-answer-box").hidden = true;
  $("#iv-progress").style.width = "100%";
  try {
    const rep = await api(`/api/interview/${state.interview.session_id}/report`);
    const cats = Object.entries(rep.category_scores).map(([k, v]) => metric(titleCase(k), v * 10)).join("");
    $("#interview-report").innerHTML = `
      <div class="card gap-hero">
        ${ring(rep.overall_percent, true, rep.overall_score + "/10")}
        <div class="info">
          <h2>${esc(rep.verdict)} · ${esc(rep.title)}</h2>
          <p>${esc(rep.advice)}</p>
          ${rep.strong_topics.length ? `<div><small class="hint">Strong topics</small><div class="chips">${chips(rep.strong_topics, "good")}</div></div>` : ""}
          ${rep.topics_to_improve.length ? `<div style="margin-top:.5rem"><small class="hint">Work on</small><div class="chips">${rep.resources.map((r) => `<a class="chip bad" href="${safeUrl(r.url)}" target="_blank" rel="noopener">${esc(r.skill)} ↗</a>`).join("")}</div></div>` : ""}
        </div>
      </div>
      <div class="grid two">
        <div class="card"><h2>Score by question type</h2><div class="metrics">${cats}</div></div>
        <div class="card"><h2>Next steps</h2>
          <div class="card-actions">
            <button class="btn secondary" data-gap="${esc(rep.career_id)}">View skill gap</button>
            <button class="btn primary" id="iv-again">New interview</button>
          </div>
        </div>
      </div>`;
    $("#interview-report").scrollIntoView({ behavior: "smooth" });
  } catch (e) {
    toast(e.message);
  }
}

// ---------- init ----------
function fillCareerSelects() {
  const opts = state.meta.careers.map((c) => `<option value="${esc(c.id)}">${esc(c.title)}</option>`).join("");
  $("#gap-career").innerHTML = opts;
  $("#iv-career").innerHTML = opts;
}

function bind() {
  document.querySelectorAll(".step").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));

  // Delegated buttons that jump to gap / interview for a career.
  document.body.addEventListener("click", (e) => {
    const gap = e.target.closest("[data-gap]");
    if (gap) { runGap(gap.dataset.gap); return; }
    const iv = e.target.closest("[data-interview]");
    if (iv) { openInterview(iv.dataset.interview); return; }
    if (e.target.id === "iv-again") {
      $("#interview-setup").hidden = false;
      $("#interview-live").hidden = true;
      $("#interview-report").innerHTML = "";
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  });

  $("#skill-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      e.target.value.split(",").forEach(addSkill);
      e.target.value = "";
    } else if (e.key === "Backspace" && !e.target.value && state.profile.skills.length) {
      state.profile.skills.pop();
      renderSkills();
      saveProfile();
    }
  });
  $("#skill-input").addEventListener("change", (e) => {
    // Selecting from the datalist fires change without Enter.
    if (state.meta.skills.includes(e.target.value)) { addSkill(e.target.value); e.target.value = ""; }
  });
  $("#skill-chips").addEventListener("click", (e) => {
    if (e.target.dataset.i !== undefined) {
      state.profile.skills.splice(Number(e.target.dataset.i), 1);
      renderSkills();
      saveProfile();
    }
  });
  $("#interest-chips").addEventListener("click", (e) => {
    const i = e.target.dataset.interest;
    if (!i) return;
    const list = state.profile.interests;
    list.includes(i) ? list.splice(list.indexOf(i), 1) : list.push(i);
    renderInterests();
    saveProfile();
  });

  const fileInput = $("#resume-file");
  const upload = (file) => {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    parseResume(fd);
  };
  fileInput.addEventListener("change", () => { upload(fileInput.files[0]); fileInput.value = ""; });
  const dz = $("#dropzone");
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", (e) => upload(e.dataTransfer.files[0]));
  $("#parse-text").addEventListener("click", () => {
    const text = $("#resume-text").value.trim();
    if (!text) { toast("Paste your resume text first"); return; }
    const fd = new FormData();
    fd.append("text", text);
    parseResume(fd, $("#parse-text"));
  });

  $("#predict-btn").addEventListener("click", predict);
  $("#gap-btn").addEventListener("click", () => runGap());
  $("#iv-start").addEventListener("click", startInterview);
  $("#iv-submit").addEventListener("click", () => submitAnswer(false));
  $("#iv-skip").addEventListener("click", () => submitAnswer(true));
  $("#iv-answer").addEventListener("input", (e) => {
    const n = e.target.value.trim() ? e.target.value.trim().split(/\s+/).length : 0;
    $("#iv-words").textContent = `${n} word${n === 1 ? "" : "s"}`;
  });
  $("#iv-answer").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) submitAnswer(false);
  });
}

async function init() {
  loadProfile();
  bind();
  try {
    const [meta, health] = await Promise.all([api("/api/meta"), api("/api/health")]);
    state.meta = meta;
    $("#skill-list").innerHTML = meta.skills.map((s) => `<option value="${esc(s)}">`).join("");
    fillCareerSelects();
    renderSkills();
    renderInterests();
    $("#experience").value = state.profile.experience_years || 0;
    $("#education").value = state.profile.education || "";
    const badge = $("#engine-badge");
    badge.textContent = health.interview_engine === "claude" ? "AI interviewer: on" : "Offline mode";
    badge.className = `badge ${health.interview_engine === "claude" ? "ai" : "muted"}`;
  } catch (e) {
    toast("Could not reach the server: " + e.message);
  }
}

init();
