"use strict";

const state = {
  meta: null,
  profile: { skills: [], interests: [], experience_years: 0, education: "", projects: [], resume_text: "" },
  prediction: null,
  interview: null,
  ai: { provider: null, label: "Offline" },
  gap: null,
};
const PROVIDER_LABEL = { gemini: "Gemini", claude: "Claude" };

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? esc(u) : "#");
const titleCase = (s) => s.charAt(0).toUpperCase() + s.slice(1);

// ---------- persistence (per-browser convenience only) ----------
function saveProfile() {
  try { localStorage.setItem("career-profile", JSON.stringify(state.profile)); } catch (_) { /* storage unavailable */ }
}
function loadJSON(key, fallback) {
  try { const raw = localStorage.getItem(key); return raw ? JSON.parse(raw) : fallback; } catch (_) { return fallback; }
}
function saveJSON(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* storage unavailable */ }
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

// A score tile: the number is the headline, a thin meter underneath shows it against 100.
function ring(value, big = false, label = null, caption = null) {
  const v = Math.max(0, Math.min(100, Math.round(value)));
  const shown = label ?? `${v}<small>%</small>`;
  return `<div class="score${big ? " big" : ""}">
    ${caption ? `<div class="score-label">${esc(caption)}</div>` : ""}
    <div class="score-value">${shown}</div>
    <div class="meter" role="meter" aria-valuenow="${v}" aria-valuemin="0" aria-valuemax="100"><i style="width:${v}%"></i></div>
  </div>`;
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
    </ul>
    ${parsed.quality ? qualityHtml(parsed.quality) : ""}`;
}

function qualityHtml(q) {
  const cls = q.score >= 70 ? "good" : q.score >= 50 ? "medium" : "high";
  return `<div class="quality">
    <div class="row between"><b>Resume health</b><span class="badge ${cls}">${q.score}/100 · ${esc(q.label)}</span></div>
    <div class="checks">${q.checks.map((c) => `<span class="chip ${c.passed ? "good" : "bad"}">${c.passed ? "✓" : "✕"} ${esc(c.name)}</span>`).join("")}</div>
    ${q.tips.length ? `<ul class="plain tips">${q.tips.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
  </div>`;
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
        <div><div class="rank">Match ${i + 1}</div><h3>${esc(c.title)}</h3><small>${esc(c.domain)}</small></div>
        ${ring(c.fit_score, false, null, "Fit")}
      </div>
      <div class="metrics">
        ${metric("Skill match", c.skill_match)}
        ${metric("Model confidence", c.ml_confidence)}
        ${metric("Interest match", c.interest_match)}
      </div>
      ${c.reasons.length ? `<ul class="reasons">${c.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
      ${c.missing_core.length ? `<div><small class="hint">Top gaps</small><div class="chips">${chips(c.missing_core, "bad")}</div></div>` : ""}
      <div class="meta-line"><span>Salary <b>${esc(c.salary)}</b></span><span>Demand <b>${esc(c.outlook)}</b></span></div>
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
      state.gap = g;
      out.innerHTML = renderGap(g);
      runWhatIf();
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
      ${ring(g.readiness, true, null, "Readiness")}
      <div class="info">
        <h2>${esc(g.title)} <span class="badge muted">${esc(g.domain)}</span></h2>
        <p><b>${esc(g.readiness_label)}</b> · ${g.missing_core.length} core gap${g.missing_core.length === 1 ? "" : "s"} · about <b>${g.estimated_weeks} weeks</b> to close the required gaps and build a portfolio (~${g.hours_per_week_assumed} h/week)</p>
        <div class="meta-line"><span>Salary (${esc(g.level)}) <b>${esc(g.salary)}</b></span><span>Demand <b>${esc(g.outlook)}</b></span>${g.roadmap_url ? `<a href="${safeUrl(g.roadmap_url)}" target="_blank" rel="noopener">Full roadmap</a>` : ""}</div>
      </div>
      <div class="hero-actions no-print">
        <button class="btn primary" data-interview="${esc(g.career_id)}">Practise interview</button>
        <button class="btn ghost small" data-print>Save as PDF</button>
      </div>
    </div>
    ${whatIfHtml(g)}
    <div class="grid two">
      <div class="card"><h2>Core requirements</h2><ul class="req-list">${req}</ul></div>
      <div class="card"><h2>Skills to learn</h2>${missing ? `<ul class="req-list">${missing}</ul>` : `<p class="empty">No gaps: you meet every listed requirement for this role.</p>`}</div>
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

// ---------- what-if simulator ----------
function whatIfHtml(g) {
  const options = [...g.missing_core.map((m) => m.recommended_skill), ...g.missing_secondary.map((m) => m.recommended_skill)];
  if (!options.length) return "";
  return `<div class="card whatif no-print">
    <h2>What if I learn…?</h2>
    <p class="hint">Tick the skills you plan to learn to see how your readiness and career ranking would change.</p>
    <div class="chips toggles" id="whatif-options">${options.map((s, i) => `<button type="button" class="chip${i < 2 ? " on" : ""}" data-whatif="${esc(s)}" aria-pressed="${i < 2}">${esc(s)}</button>`).join("")}</div>
    <div id="whatif-result" class="whatif-result"></div>
  </div>`;
}

async function runWhatIf() {
  const box = $("#whatif-result");
  if (!box || !state.gap) return;
  const add = [...document.querySelectorAll("#whatif-options .chip.on")].map((b) => b.dataset.whatif);
  if (!add.length) { box.innerHTML = `<p class="hint">Select at least one skill.</p>`; return; }
  box.innerHTML = `<p class="hint"><span class="spinner"></span>Simulating…</p>`;
  try {
    const r = await postJSON("/api/whatif", {
      career_id: state.gap.career_id, skills: state.profile.skills, add_skills: add,
      interests: state.profile.interests, experience_years: state.profile.experience_years,
    });
    const b = r.before, a = r.after;
    const delta = (x, y, suffix = "%") => {
      const d = Math.round((y - x) * 10) / 10;
      return d > 0 ? `<span class="up">+${d}${suffix}</span>` : d < 0 ? `<span class="down">${d}${suffix}</span>` : `<span class="hint">no change</span>`;
    };
    box.innerHTML = `
      <div class="compare">
        <div><small class="hint">Readiness</small><div class="big">${Math.round(b.readiness)}% → <b>${Math.round(a.readiness)}%</b></div>${delta(b.readiness, a.readiness)}</div>
        <div><small class="hint">Rank for this career</small><div class="big">#${b.rank} → <b>#${a.rank}</b></div>${a.rank < b.rank ? `<span class="up">up ${b.rank - a.rank}</span>` : `<span class="hint">same</span>`}</div>
        <div><small class="hint">Time to learn these</small><div class="big"><b>~${r.learning_weeks} wk</b></div><span class="hint">at ~10 h/week</span></div>
        <div><small class="hint">Status</small><div class="big"><b>${esc(a.readiness_label)}</b></div><span class="hint">was ${esc(b.readiness_label)}</span></div>
      </div>
      <p class="hint">Your top careers after learning ${esc(r.added_skills.join(", "))}: ${a.top.map((t) => `<b>${esc(t.title)}</b> (${Math.round(t.fit_score)}%)`).join(" · ")}</p>
      ${a.missing_core.length ? `<p class="hint">Still missing for this role: ${esc(a.missing_core.join(", "))}</p>` : `<p class="up">You would meet every core requirement for this role.</p>`}`;
  } catch (e) {
    box.innerHTML = `<p class="msg error">${esc(e.message)}</p>`;
  }
}

// ---------- voice + timer ----------
const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
const voice = { rec: null, listening: false, timer: null, started: 0 };

function speak(text) {
  if (!$("#iv-tts").checked || !("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "en-IN";
  u.rate = 1;
  window.speechSynthesis.speak(u);
}

function stopListening() {
  if (voice.rec && voice.listening) voice.rec.stop();
}

function toggleMic() {
  if (!SpeechRec) return;
  if (voice.listening) { stopListening(); return; }
  const rec = new SpeechRec();
  rec.lang = "en-IN";
  rec.continuous = true;
  rec.interimResults = true;
  const box = $("#iv-answer");
  const base = box.value ? box.value.trimEnd() + " " : "";
  rec.onresult = (e) => {
    let text = "";
    for (let i = 0; i < e.results.length; i++) text += e.results[i][0].transcript;
    box.value = base + text.trim();
    box.dispatchEvent(new Event("input"));
  };
  rec.onend = () => { voice.listening = false; $("#iv-mic").classList.remove("recording"); $("#iv-mic span").textContent = "Dictate"; };
  rec.onerror = (e) => { if (e.error !== "no-speech" && e.error !== "aborted") toast("Microphone: " + e.error); };
  voice.rec = rec;
  window.speechSynthesis && window.speechSynthesis.cancel();
  rec.start();
  voice.listening = true;
  $("#iv-mic").classList.add("recording");
  $("#iv-mic span").textContent = "Stop dictation";
}

function startTimer() {
  clearInterval(voice.timer);
  voice.started = Date.now();
  const el = $("#iv-timer");
  const tick = () => {
    const sec = Math.floor((Date.now() - voice.started) / 1000);
    el.textContent = `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
    el.classList.toggle("over", sec > 180);
  };
  tick();
  voice.timer = setInterval(tick, 1000);
}
const elapsedSeconds = () => Math.round((Date.now() - voice.started) / 1000);

// ---------- interview history ----------
function renderHistory() {
  const hist = loadJSON("interview-history", []);
  const box = $("#iv-history");
  if (!hist.length) { box.innerHTML = ""; return; }
  const recent = hist.slice(-6);
  const first = hist[0].score, last = hist[hist.length - 1].score;
  const trend = hist.length > 1 ? (last >= first ? `<span class="up">+${(last - first).toFixed(1)}</span> since your first interview` : `<span class="down">${(last - first).toFixed(1)}</span> since your first interview`) : "";
  box.innerHTML = `<div class="history">
    <div class="row between"><b>Your progress</b><small class="hint">${hist.length} interview${hist.length === 1 ? "" : "s"} ${trend}</small></div>
    <div class="spark">${recent.map((h) => `<div class="spark-bar" style="--h:${h.score * 10}%" title="${esc(h.title)} · ${h.score}/10"><span>${h.score}</span></div>`).join("")}</div>
    <ul class="plain hint">${recent.slice().reverse().slice(0, 3).map((h) => `<li>${esc(h.date)} · ${esc(h.title)} (${esc(h.difficulty)}) · <b>${h.score}/10</b> ${esc(h.verdict)}</li>`).join("")}</ul>
    <button class="btn ghost small" id="iv-clear-history">Clear history</button>
  </div>`;
}

function recordHistory(rep) {
  const hist = loadJSON("interview-history", []);
  hist.push({ date: new Date().toLocaleDateString(), title: rep.title, score: rep.overall_score, verdict: rep.verdict, difficulty: rep.difficulty, mode: rep.mode });
  saveJSON("interview-history", hist.slice(-20));
}

// ---------- job match ----------
async function runJobMatch() {
  const jd = $("#jd-text").value.trim();
  const out = $("#jd-result");
  if (jd.length < 30) { toast("Paste the full job description first"); return; }
  if (!state.profile.resume_text && !state.profile.skills.length) { toast("Upload your resume on the Profile step first"); show("profile"); return; }
  const useAi = !!state.ai.provider && $("#jd-ai").checked;
  await withBusy($("#jd-btn"), useAi ? "Analysing with AI…" : "Analysing…", async () => {
    try {
      const r = await postJSON("/api/jobmatch", {
        job_description: jd, resume_text: state.profile.resume_text || null, skills: state.profile.skills,
        experience_years: state.profile.experience_years, use_ai: useAi,
      });
      out.innerHTML = renderJobMatch(r);
    } catch (e) {
      out.innerHTML = `<div class="card empty">${esc(e.message)}</div>`;
    }
  });
}

function renderJobMatch(r) {
  const ai = r.ai;
  return `
    <div class="card gap-hero">
      ${ring(r.match_score, true, null, "ATS match")}
      <div class="info">
        <h2>${esc(r.label)}</h2>
        <p>Skills ${r.skill_score}% · keywords ${r.keyword_score}%${r.likely_role ? ` · this job looks like a <b>${esc(r.likely_role.title)}</b> role` : ""}</p>
        ${r.flags.map((f) => `<p class="msg error"><b>Note:</b> ${esc(f)}</p>`).join("")}
      </div>
      <div class="hero-actions no-print">
        ${r.likely_role ? `<button class="btn primary" data-interview="${esc(r.likely_role.career_id)}">Practise this interview</button>
        <button class="btn secondary small" data-gap="${esc(r.likely_role.career_id)}">Skill gap</button>` : ""}
        <button class="btn ghost small" data-print>Save as PDF</button>
      </div>
    </div>
    <div class="grid two">
      <div class="card">
        <h2>Skills the job asks for</h2>
        ${r.matched_skills.length ? `<small class="hint">On your resume</small><div class="chips">${chips(r.matched_skills, "good")}</div>` : ""}
        ${r.missing_skills.length ? `<small class="hint" style="display:block;margin-top:.75rem">Missing from your resume</small><div class="chips">${r.resources.map((x) => `<a class="chip bad" href="${safeUrl(x.url)}" target="_blank" rel="noopener" title="Learning resource">${esc(x.skill)}</a>`).join("")}${chips(r.missing_skills.slice(6), "bad")}</div>` : `<p class="up">Your resume covers every skill in this job description.</p>`}
        <h3 style="margin-top:1rem">Keywords</h3>
        <div class="chips">${chips(r.matched_keywords, "good")}${chips(r.missing_keywords, "plain")}</div>
        <p class="hint">Green keywords appear on your resume; grey ones are frequent in the job post but missing.</p>
      </div>
      <div class="card">
        <h2>How to improve</h2>
        <ul class="plain">${r.suggestions.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>
        ${r.quality ? qualityHtml(r.quality) : ""}
      </div>
    </div>
    ${ai ? `<div class="card ai-card">
      <h2>Tailoring suggestions <span class="badge ai">${esc(PROVIDER_LABEL[ai.provider] || "AI")}</span></h2>
      <p>${esc(ai.fit_summary)}</p>
      ${ai.tailored_summary ? `<h3>Suggested resume summary</h3><blockquote id="jd-summary">${esc(ai.tailored_summary)}</blockquote><button class="btn ghost small no-print" data-copy="#jd-summary">Copy</button>` : ""}
      ${ai.bullet_rewrites.length ? `<h3 style="margin-top:1rem">Stronger bullet points</h3>${ai.bullet_rewrites.map((b) => `<div class="rewrite"><div class="before">${esc(b.original)}</div><div class="after">${esc(b.improved)}</div></div>`).join("")}` : ""}
      ${ai.tips.length ? `<h3 style="margin-top:1rem">Tips</h3><ul class="plain">${ai.tips.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
    </div>` : r.ai_error ? `<div class="card"><p class="msg error">AI suggestions unavailable: ${esc(r.ai_error)}</p></div>` : ""}`;
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
      state.interview.times = [];
      $("#iv-thread").innerHTML = `<div class="bubble"><b>${esc(s.title)} interview</b> · ${s.total} questions · ${s.mode !== "offline" ? `<span class="badge ai">Interviewer: ${esc(PROVIDER_LABEL[s.mode] || s.mode)}</span>` : '<span class="badge muted">Question bank</span>'}
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
  startTimer();
  speak(q.text);
  $("#iv-answer").focus({ preventScroll: true });
  $("#iv-answer-box").scrollIntoView({ behavior: "smooth", block: "end" });
}

function feedbackHtml(ev) {
  const level = ev.score >= 7 ? "" : ev.score >= 4.5 ? "mid" : "low";
  return `<div class="bubble feedback ${level}">
    <span class="score-line">${ev.score} / 10</span> <span class="hint">${ev.evaluator && ev.evaluator !== "offline" ? `Feedback by ${esc(PROVIDER_LABEL[ev.evaluator] || ev.evaluator)}` : "Rubric feedback"}</span>
    ${ev.seconds !== undefined ? `<span class="hint">· answered in ${Math.floor(ev.seconds / 60)}:${String(ev.seconds % 60).padStart(2, "0")}</span>` : ""}
    ${ev.strengths.length ? `<div><b>What went well</b><ul>${ev.strengths.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></div>` : ""}
    ${ev.improvements.length ? `<div><b>How to improve</b><ul>${ev.improvements.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></div>` : ""}
    ${ev.evaluator !== "offline" && ev.missing_keywords.length ? `<div><b>Missed points</b><ul>${ev.missing_keywords.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></div>` : ""}
    ${ev.model_answer ? `<details><summary>See a strong answer</summary><p>${esc(ev.model_answer)}</p></details>` : ""}
  </div>`;
}

async function submitAnswer(skip = false) {
  const answer = skip ? "" : $("#iv-answer").value.trim();
  if (!skip && !answer) { toast("Type an answer or press Skip"); return; }
  stopListening();
  const btn = $("#iv-submit");
  if (btn.disabled) return;
  const seconds = elapsedSeconds();
  await withBusy(btn, "Evaluating…", async () => {
    try {
      // Send the interview state along so any server instance can continue it (needed on Vercel).
      const r = await postJSON(`/api/interview/${state.interview.session_id}/answer`, { answer, state: state.interview.state });
      state.interview.state = r.state;
      r.evaluation.seconds = seconds;
      state.interview.times.push(seconds);
      $("#iv-thread").insertAdjacentHTML("beforeend", `<div class="bubble a">${answer ? esc(answer) : "<i>(skipped)</i>"}</div>${feedbackHtml(r.evaluation)}`);
      if (r.done) finishInterview();
      else askQuestion(r.next_question);
    } catch (e) {
      toast(e.message);
    }
  });
}

async function finishInterview() {
  clearInterval(voice.timer);
  $("#iv-answer-box").hidden = true;
  $("#iv-progress").style.width = "100%";
  try {
    const rep = await postJSON(`/api/interview/${state.interview.session_id}/report`, { state: state.interview.state });
    recordHistory(rep);
    renderHistory();
    const times = state.interview.times;
    const avgTime = times.length ? Math.round(times.reduce((a, b) => a + b, 0) / times.length) : 0;
    const cats = Object.entries(rep.category_scores).map(([k, v]) => metric(titleCase(k), v * 10)).join("");
    $("#interview-report").innerHTML = `
      <div class="card gap-hero">
        ${ring(rep.overall_percent, true, `${rep.overall_score}<small>/10</small>`, "Overall")}
        <div class="info">
          <h2>${esc(rep.verdict)} · ${esc(rep.title)}</h2>
          <p>${esc(rep.advice)}</p>
          <p class="hint">Average answer time ${Math.floor(avgTime / 60)}:${String(avgTime % 60).padStart(2, "0")} (aim for 1-3 minutes per answer)</p>
          ${rep.strong_topics.length ? `<div><small class="hint">Strong topics</small><div class="chips">${chips(rep.strong_topics, "good")}</div></div>` : ""}
          ${rep.topics_to_improve.length ? `<div style="margin-top:.5rem"><small class="hint">Work on</small><div class="chips">${rep.resources.map((r) => `<a class="chip bad" href="${safeUrl(r.url)}" target="_blank" rel="noopener">${esc(r.skill)}</a>`).join("")}</div></div>` : ""}
        </div>
      </div>
      <div class="grid two">
        <div class="card"><h2>Score by question type</h2><div class="metrics">${cats}</div></div>
        <div class="card"><h2>Next steps</h2>
          <div class="card-actions">
            <button class="btn secondary" data-gap="${esc(rep.career_id)}">View skill gap</button>
            <button class="btn primary" id="iv-again">New interview</button>
            <button class="btn ghost" data-print>Save as PDF</button>
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
    if (e.target.closest("[data-print]")) { window.print(); return; }
    const copy = e.target.closest("[data-copy]");
    if (copy) {
      const text = $(copy.dataset.copy).textContent;
      navigator.clipboard ? navigator.clipboard.writeText(text).then(() => toast("Copied"), () => toast("Copy failed")) : toast("Copy not supported");
      return;
    }
    const wi = e.target.closest("[data-whatif]");
    if (wi) {
      wi.classList.toggle("on");
      wi.setAttribute("aria-pressed", wi.classList.contains("on"));
      clearTimeout(runWhatIf._t);
      runWhatIf._t = setTimeout(runWhatIf, 250);
      return;
    }
    if (e.target.id === "iv-clear-history") { saveJSON("interview-history", []); renderHistory(); return; }
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
  $("#iv-mic").addEventListener("click", toggleMic);
  $("#jd-btn").addEventListener("click", runJobMatch);
  $("#iv-tts").checked = loadJSON("tts", false);
  $("#iv-tts").addEventListener("change", (e) => saveJSON("tts", e.target.checked));
  if (SpeechRec) {
    $("#iv-mic").hidden = false;
    $("#iv-voice-hint").textContent = "Use Dictate to answer out loud, as you would in a real interview.";
  } else {
    $("#iv-voice-hint").textContent = "Voice answers need Chrome or Edge.";
  }
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
    state.ai = health.ai;
    const badge = $("#engine-badge");
    badge.textContent = health.ai.provider ? `${health.ai.label} connected` : "Offline mode";
    badge.title = health.ai.provider ? `Interviewer and resume tailoring use ${health.ai.model}` : (health.ai.note || "Add GEMINI_API_KEY to .env to enable the AI interviewer");
    badge.className = `badge ${health.ai.provider ? "ai" : "muted"}`;
    $("#jd-ai-wrap").hidden = !health.ai.provider;
    $("#jd-source").textContent = health.ai.provider ? "" : "Add a Gemini API key to get tailoring suggestions.";
    renderHistory();
  } catch (e) {
    toast("Could not reach the server: " + e.message);
  }
}

init();
