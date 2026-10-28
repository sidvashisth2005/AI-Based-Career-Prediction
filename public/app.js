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

// ---------- interviewer voice ----------
// Speech: Gemini's natural voices when the server has a key, otherwise the most natural voice the
// browser offers, spoken sentence by sentence at a relaxed pace.
const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
const voice = {
  rec: null, listening: false, mode: null, speechFailed: loadJSON("speech-service-broken", false), fallbackPending: false,
  recorder: null, stream: null, chunks: [], autoStop: null,
  timer: null, started: 0, audio: null, token: 0, browserVoices: [], warnedNatural: false,
};
const SAMPLE_LINE = "Hi, I'll be your interviewer today. Take your time with each answer, there's no rush.";

// Short spoken transitions, like a real interviewer uses between questions.
function leadIn(q) {
  const pick = (options) => options[(q.index * 7 + q.total) % options.length];
  if (q.index === 0) return "Hi, thanks for making the time today. Let's start with a little about you.";
  if (q.index === q.total - 1) return pick(["Okay, last one.", "Great, we're nearly done. One final question.", "Alright, final question, and this one's more about how you work."]);
  if (q.category === "project") return pick(["I'd love to hear about something you've built.", "Let's talk about your projects for a bit."]);
  if (q.category === "scenario") return pick(["Let me give you a situation you might run into on the job.", "Here's a scenario for you."]);
  if (q.category === "behavioral") return pick(["Let's switch gears a little.", "Now something about how you work with people."]);
  return pick(["Thanks. Next one.", "Okay, good. Moving on.", "Alright, let's get a bit more technical.", "Got it, thank you.",
    q.skill ? `Let's talk about ${q.skill} for a moment.` : "Okay, next question."]);
}

function rankBrowserVoice(v) {
  const name = `${v.name} ${v.voiceURI}`;
  let score = 0;
  if (/natural|neural/i.test(name)) score += 60;          // Edge "Online (Natural)" voices
  if (/premium|enhanced|siri/i.test(name)) score += 45;   // Apple's higher-quality voices
  if (/^Google/i.test(v.name)) score += 35;               // Chrome's network voices
  if (/online/i.test(name)) score += 10;
  if (/^en-IN/i.test(v.lang)) score += 8;
  else if (/^en-(GB|US|AU)/i.test(v.lang)) score += 5;
  if (/compact|espeak|robot|novelty|whisper|zarvox|bad news|bells|trinoids|albert/i.test(name)) score -= 80;
  return score;
}

function loadBrowserVoices() {
  if (!("speechSynthesis" in window)) return [];
  voice.browserVoices = window.speechSynthesis.getVoices()
    .filter((v) => /^en(-|_|$)/i.test(v.lang))
    .sort((a, b) => rankBrowserVoice(b) - rankBrowserVoice(a));
  return voice.browserVoices;
}

function chosenBrowserVoice() {
  const value = $("#iv-voice").value || "";
  if (value.startsWith("browser:")) {
    const found = voice.browserVoices.find((v) => v.voiceURI === value.slice(8));
    if (found) return found;
  }
  return voice.browserVoices[0] || null;
}

function stopSpeaking() {
  voice.token++;
  if (voice.audio) { voice.audio.pause(); voice.audio = null; }
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

function speakWithBrowser(text) {
  if (!("speechSynthesis" in window)) return;
  const v = chosenBrowserVoice();
  // One utterance per sentence gives natural pauses and avoids Chrome cutting off long speech.
  for (const sentence of text.match(/[^.!?]+[.!?]*/g) || [text]) {
    const u = new SpeechSynthesisUtterance(sentence.trim());
    if (v) { u.voice = v; u.lang = v.lang; } else { u.lang = "en-IN"; }
    u.rate = 0.95;
    u.pitch = 1;
    window.speechSynthesis.speak(u);
  }
}

async function speak(text, force = false) {
  stopSpeaking();
  if (!force && !$("#iv-tts").checked) return;
  const token = voice.token;
  const choice = $("#iv-voice").value || "";
  if (state.ai.speech && !choice.startsWith("browser")) {
    try {
      const res = await fetch("/api/speak", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, voice: choice }) });
      if (!res.ok) throw new Error(((await res.json().catch(() => ({}))).detail) || `HTTP ${res.status}`);
      const url = URL.createObjectURL(await res.blob());
      if (token !== voice.token) { URL.revokeObjectURL(url); return; }   // a newer question started
      const audio = new Audio(url);
      audio.onended = () => URL.revokeObjectURL(url);
      voice.audio = audio;
      await audio.play();
      return;
    } catch (e) {
      if (token !== voice.token) return;
      if (!voice.warnedNatural) { toast("Natural voice unavailable, using the browser voice instead."); voice.warnedNatural = true; }
      console.warn("Natural voice failed:", e);
    }
  }
  speakWithBrowser(text);
}

function fillVoiceOptions() {
  const select = $("#iv-voice");
  const saved = loadJSON("voice", "");
  const opts = [];
  if (state.ai.speech) {
    for (const [name, style] of Object.entries(state.ai.voices || {})) opts.push([name, `${name} (${style.toLowerCase()})`]);
    opts.push(["browser", "Browser voice"]);
  } else {
    opts.push(["browser", "Best available"]);
    for (const v of loadBrowserVoices().slice(0, 8)) opts.push([`browser:${v.voiceURI}`, `${v.name.replace(/^Microsoft /, "")} (${v.lang})`]);
  }
  select.innerHTML = opts.map(([value, label]) => `<option value="${esc(value)}">${esc(label)}</option>`).join("");
  const fallback = state.ai.speech ? (state.ai.default_voice || opts[0][0]) : "browser";
  select.value = opts.some(([value]) => value === saved) ? saved : fallback;
}

// ---------- dictation ----------
// The browser's speech service where it works (Chrome, Edge); otherwise record the answer and have
// the server transcribe it (needs a Gemini key). Brave, Opera, Vivaldi and Firefox use the fallback.
function setMicUi(on, label) {
  const btn = $("#iv-mic");
  btn.classList.toggle("recording", on);
  btn.querySelector("span").textContent = label || (on ? "Stop" : "Dictate");
}

function micAvailable() {
  return Boolean((SpeechRec && !voice.speechFailed) || (state.ai.transcription && navigator.mediaDevices && window.MediaRecorder));
}

function toggleMic() {
  if (voice.listening) { stopDictation(); return; }
  stopSpeaking();
  if (SpeechRec && !voice.speechFailed) startBrowserDictation();
  else if (state.ai.transcription) startRecording();
  else toast("Dictation isn't available in this browser. Use Chrome or Edge, or ask the site owner to add a Gemini API key.");
}

function browserSpeechFailed(reason) {
  // Remember it for this browser, so next time Dictate goes straight to recording.
  voice.speechFailed = true;
  saveJSON("speech-service-broken", true);
  if (state.ai.transcription) return true;
  toast(`Your browser's speech service isn't available (${reason}). Try Chrome or Edge, or type your answer.`);
  return false;
}

function startBrowserDictation() {
  const rec = new SpeechRec();
  let started = false;
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
  rec.onstart = () => { started = true; };
  rec.onerror = (e) => {
    if (e.error === "no-speech" || e.error === "aborted") return;
    if (e.error === "not-allowed") { toast("Microphone access is blocked. Allow it from the icon in the address bar."); return; }
    // "network" and friends: the browser has no working speech service (common in Brave and Opera).
    if (browserSpeechFailed(e.error)) voice.fallbackPending = true;
  };
  rec.onend = () => {
    voice.listening = false;
    setMicUi(false);
    if (voice.fallbackPending) {
      voice.fallbackPending = false;
      toast("Recording instead: speak your answer, then press Stop and it will be transcribed.");
      startRecording();
    }
  };
  voice.rec = rec;
  voice.mode = "browser";
  rec.start();
  voice.listening = true;
  setMicUi(true, "Stop dictation");
  // Some browsers accept start() but never begin listening and report nothing; don't wait forever.
  setTimeout(() => {
    if (started || voice.rec !== rec || !voice.listening) return;
    rec.onend = null;
    try { rec.abort(); } catch (_) { /* already stopped */ }
    voice.listening = false;
    setMicUi(false);
    if (browserSpeechFailed("no response")) {
      toast("Recording instead: speak your answer, then press Stop and it will be transcribed.");
      startRecording();
    }
  }, 4000);
}

async function startRecording() {
  if (!navigator.mediaDevices || !window.MediaRecorder) { toast("Recording isn't supported in this browser."); return; }
  try {
    voice.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (_) {
    toast("Microphone access is blocked. Allow it from the icon in the address bar.");
    return;
  }
  const type = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find((t) => MediaRecorder.isTypeSupported(t));
  voice.recorder = new MediaRecorder(voice.stream, type ? { mimeType: type } : undefined);
  voice.chunks = [];
  voice.recorder.ondataavailable = (e) => { if (e.data.size) voice.chunks.push(e.data); };
  voice.recorder.onstop = finishRecording;
  voice.recorder.start();
  voice.mode = "record";
  voice.listening = true;
  setMicUi(true, "Stop recording");
  voice.autoStop = setTimeout(stopDictation, 5 * 60 * 1000);
}

function stopDictation() {
  clearTimeout(voice.autoStop);
  if (!voice.listening) return;
  if (voice.mode === "browser" && voice.rec) voice.rec.stop();
  if (voice.mode === "record" && voice.recorder && voice.recorder.state !== "inactive") voice.recorder.stop();
}

async function finishRecording() {
  voice.listening = false;
  if (voice.stream) voice.stream.getTracks().forEach((t) => t.stop());
  const btn = $("#iv-mic");
  btn.disabled = true;
  setMicUi(false, "Transcribing…");
  try {
    const pcm = await toMono16k(new Blob(voice.chunks, { type: voice.recorder.mimeType }));
    const parts = [];
    const step = 16000 * 50; // 50-second pieces stay well under the upload limit
    for (let i = 0; i < pcm.length; i += step) {
      const fd = new FormData();
      fd.append("file", new Blob([encodeWav(pcm.subarray(i, i + step), 16000)], { type: "audio/wav" }), "answer.wav");
      const r = await api("/api/transcribe", { method: "POST", body: fd });
      if (r.text) parts.push(r.text);
    }
    if (parts.length) {
      const box = $("#iv-answer");
      box.value = (box.value ? box.value.trimEnd() + " " : "") + parts.join(" ");
      box.dispatchEvent(new Event("input"));
    } else {
      toast("No speech was detected. Try again a little closer to the microphone.");
    }
  } catch (e) {
    toast("Transcription failed: " + e.message);
  } finally {
    btn.disabled = false;
    setMicUi(false);
  }
}

async function toMono16k(blob) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  const ctx = new Ctx();
  const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
  ctx.close();
  const off = new OfflineAudioContext(1, Math.max(1, Math.ceil(decoded.duration * 16000)), 16000);
  const src = off.createBufferSource();
  src.buffer = decoded;
  src.connect(off.destination);
  src.start();
  return (await off.startRendering()).getChannelData(0);
}

function encodeWav(samples, rate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset, str) => { for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i)); };
  text(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); text(8, "WAVE");
  text(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, "data"); view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const v = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true);
  }
  return buffer;
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
    <div class="bubble q"><span class="tag">Question ${q.number} of ${q.total} · ${esc(q.category)}${q.skill ? " · " + esc(q.skill) : ""}</span><p class="lead-in">${esc(leadIn(q))}</p><p>${esc(q.text)}</p></div>`);
  $("#iv-answer").value = "";
  $("#iv-words").textContent = "0 words";
  $("#iv-answer-box").hidden = false;
  startTimer();
  speak(`${leadIn(q)} ${q.text}`);
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
  if (voice.listening && voice.mode === "record") { toast("Press Stop recording first so your answer can be transcribed."); return; }
  if (!skip && !answer) { toast("Type an answer or press Skip"); return; }
  stopDictation();
  stopSpeaking();
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
  $("#iv-voice").addEventListener("change", (e) => saveJSON("voice", e.target.value));
  $("#iv-voice-preview").addEventListener("click", () => speak(SAMPLE_LINE, true));
  if ("speechSynthesis" in window) {
    window.speechSynthesis.onvoiceschanged = () => { if (state.meta && !state.ai.speech) fillVoiceOptions(); };
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
    fillVoiceOptions();
    $("#iv-mic").hidden = !micAvailable();
    $("#iv-voice-hint").textContent = micAvailable()
      ? "Use Dictate to answer out loud, as you would in a real interview."
      : "Spoken answers need Chrome or Edge (or a Gemini key on the server).";
    renderHistory();
  } catch (e) {
    toast("Could not reach the server: " + e.message);
  }
}

init();
