/* EchoBook single-page frontend. No build step, no framework. */
const view = document.getElementById("view");
let STATUS = { inference_enabled: false, storyteller: "Grandpa", book_title: "Grandpa's Kitchen" };
let pollTimer = null;

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function highlight(text, query) {
  const safe = esc(text);
  const terms = query.trim().split(/\s+/).filter(Boolean).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!terms.length) return safe;
  return safe.replace(new RegExp(`(${terms.map(esc).join("|")})`, "gi"), "<mark>$1</mark>");
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

function setNav(name) {
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.nav === name));
}

function fmtDuration(sec) {
  if (!sec && sec !== 0) return "";
  const m = Math.floor(sec / 60), s = Math.round(sec % 60);
  return m ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}

/* ---------- Book (grid + search) ---------- */
let searchDebounce;
async function renderBook() {
  setNav("book");
  const q = new URLSearchParams(location.hash.split("?")[1] || "").get("q") || "";
  view.innerHTML = `
    <section class="hero">
      <div>
        <h1>${esc(STATUS.book_title)}</h1>
        <p>Family recipes, recovered from ${esc(STATUS.storyteller)}'s voice memos.</p>
      </div>
      <label class="search">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <input id="q" type="search" placeholder="Search by dish or ingredient (e.g. ghee)" value="${esc(q)}" aria-label="Search recipes">
      </label>
    </section>
    <div id="results"></div>`;
  const input = document.getElementById("q");
  input.addEventListener("input", () => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => {
      history.replaceState(null, "", input.value ? `#/?q=${encodeURIComponent(input.value)}` : "#/");
      loadResults(input.value);
    }, 150);
  });
  if (q) { input.focus(); input.setSelectionRange(q.length, q.length); }
  loadResults(q);
}

async function loadResults(q) {
  const box = document.getElementById("results");
  if (!box) return;
  let items;
  try { items = await api(`/api/recipes?q=${encodeURIComponent(q)}`); }
  catch (e) { box.innerHTML = `<p class="err">Couldn't load recipes: ${esc(e.message)}</p>`; return; }
  if (!items.length) {
    box.innerHTML = q
      ? `<div class="empty"><h2>Nothing matches “${esc(q)}”</h2><p>Try another ingredient or dish name.</p></div>`
      : `<div class="empty"><h2>The book is empty</h2><p>${STATUS.inference_enabled
          ? `Add the first voice memo and EchoBook will write it up as a recipe.</p><p><a class="btn primary" href="#/add">Add a memo</a>`
          : "No recipes have been published yet."}</p></div>`;
    return;
  }
  const lowerTerms = q.toLowerCase().split(/\s+/).filter(Boolean);
  box.innerHTML = `<div class="grid">${items.map((e) => {
    const r = e.recipe;
    const matched = lowerTerms.length
      ? r.ingredients.filter((i) => lowerTerms.some((t) => i.item.toLowerCase().includes(t))).map((i) => i.item)
      : [];
    return `
      <a class="card" href="#/recipe/${encodeURIComponent(e.id)}">
        <h2>${highlight(r.title, q)}</h2>
        ${r.description ? `<p class="desc">${esc(r.description)}</p>` : ""}
        ${r.story_quote ? `<blockquote>“${esc(r.story_quote)}”</blockquote>` : ""}
        <div class="meta">
          ${matched.map((m) => `<span class="chip warm">${highlight(m, q)}</span>`).join("")}
          ${r.servings ? `<span class="chip">Serves ${esc(r.servings)}</span>` : ""}
          <span class="chip">${r.ingredients.length} ingredients</span>
          ${r.tags.slice(0, 2).map((t) => `<span class="chip">${highlight(t, q)}</span>`).join("")}
        </div>
      </a>`;
  }).join("")}</div>`;
}

/* ---------- Single recipe ---------- */
function recipeHTML(e, { forPrint = false } = {}) {
  const r = e.recipe;
  const who = esc(STATUS.storyteller);
  return `
  <article class="recipe ${forPrint ? "print-recipe" : ""}">
    <header class="recipe-head">
      <h1>${esc(r.title)}</h1>
      ${r.description ? `<p class="desc">${esc(r.description)}</p>` : ""}
      <div class="facts">
        ${r.servings ? `<span>Serves <b>${esc(r.servings)}</b></span>` : ""}
        ${r.total_time ? `<span>Time <b>${esc(r.total_time)}</b></span>` : ""}
        <span><b>${r.ingredients.length}</b> ingredients · <b>${r.steps.length}</b> steps</span>
      </div>
    </header>

    ${r.story_quote || e.audio_file ? `
    <section class="voice">
      <div class="voice-label">In ${who}'s words</div>
      ${r.story_quote ? `<blockquote>${esc(r.story_quote)}</blockquote>` : ""}
      ${!forPrint && e.audio_file ? `<audio controls preload="metadata" src="/audio/${encodeURIComponent(e.audio_file)}"></audio>` : ""}
    </section>` : ""}

    <div class="cols">
      <section>
        <h2>Ingredients</h2>
        <ul class="ingredients">
          ${r.ingredients.map((i, n) => `
            <li data-i="${n}"><input type="checkbox" aria-label="Got it">
              <span class="ing-text">${i.quantity ? `<span class="qty">${esc(i.quantity)}</span> ` : ""}${esc(i.item)}${i.note ? ` <span class="note">(${esc(i.note)})</span>` : ""}</span>
            </li>`).join("")}
        </ul>
      </section>
      <section>
        <h2>Steps</h2>
        <ol class="steps">${r.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>
        ${r.tips.length ? `<div class="tips"><h3>${who}'s tips</h3><ul>${r.tips.map((t) => `<li>${esc(t)}</li>`).join("")}</ul></div>` : ""}
      </section>
    </div>

    ${!forPrint ? `
    <details class="transcript">
      <summary>Original voice memo transcript${e.duration ? ` (${fmtDuration(e.duration)})` : ""}</summary>
      <p>${esc(e.transcript)}</p>
      <div class="provenance">Source: ${esc(e.source_name)} · ${esc(e.asr_model || "")} → ${esc(e.llm_model || "")} · processed on-device</div>
    </details>` : ""}
  </article>`;
}

async function renderRecipe(id) {
  setNav("book");
  let e;
  try { e = await api(`/api/recipes/${encodeURIComponent(id)}`); }
  catch (err) { view.innerHTML = `<div class="empty"><h2>Recipe not found</h2><p><a href="#/">Back to the book</a></p></div>`; return; }
  document.title = `${e.recipe.title} · EchoBook`;
  view.innerHTML = `
    <div class="actions">
      <a class="btn" href="#/">← All recipes</a>
      <span style="display:flex;gap:8px;flex-wrap:wrap">
        <a class="btn" href="/api/recipes/${encodeURIComponent(id)}/markdown">Download Markdown</a>
        <button class="btn" onclick="window.print()">Print / PDF</button>
        ${STATUS.inference_enabled ? `<a class="btn" href="#/recipe/${encodeURIComponent(id)}/edit">Review &amp; edit</a>
          <button class="btn danger" id="del">Delete</button>` : ""}
      </span>
    </div>
    ${recipeHTML(e)}`;
  view.querySelectorAll(".ingredients li").forEach((li) => {
    const box = li.querySelector("input");
    li.addEventListener("click", (ev) => { if (ev.target !== box) box.checked = !box.checked; li.classList.toggle("got", box.checked); });
  });
  const del = document.getElementById("del");
  if (del) del.onclick = async () => {
    if (!confirm(`Delete “${e.recipe.title}” from the book?`)) return;
    await api(`/api/recipes/${encodeURIComponent(id)}`, { method: "DELETE" });
    location.hash = "#/";
  };
}

/* ---------- Review & edit ---------- */
async function renderEdit(id) {
  setNav("book");
  if (!STATUS.inference_enabled) { location.hash = `#/recipe/${encodeURIComponent(id)}`; return; }
  const e = await api(`/api/recipes/${encodeURIComponent(id)}`);
  const r = e.recipe;
  const lines = (a) => esc(a.join("\n"));
  view.innerHTML = `
    <div class="actions"><a class="btn" href="#/recipe/${encodeURIComponent(id)}">← Cancel</a></div>
    <form class="recipe edit" id="edit-form">
      <h1>Review &amp; edit</h1>
      <p class="desc">The model can mishear. Listen to the recording and fix anything before sharing the book.</p>
      ${e.audio_file ? `<audio controls preload="metadata" src="/audio/${encodeURIComponent(e.audio_file)}" style="width:100%"></audio>` : ""}
      <label>Title <input name="title" value="${esc(r.title)}" required></label>
      <label>Description <input name="description" value="${esc(r.description)}"></label>
      <div class="row">
        <label>Serves <input name="servings" value="${esc(r.servings)}"></label>
        <label>Time <input name="total_time" value="${esc(r.total_time)}"></label>
        <label>Tags <small>(comma-separated)</small><input name="tags" value="${esc(r.tags.join(", "))}"></label>
      </div>
      <label>Ingredients <small>one per line: quantity | ingredient | note</small>
        <textarea name="ingredients" rows="${Math.max(6, r.ingredients.length + 1)}">${esc(r.ingredients.map((i) => [i.quantity, i.item, i.note].join(" | ").replace(/( \| )+$/, "")).join("\n"))}</textarea></label>
      <label>Steps <small>one per line</small>
        <textarea name="steps" rows="${Math.max(6, r.steps.length + 1)}">${lines(r.steps)}</textarea></label>
      <label>${esc(STATUS.storyteller)}'s tips <small>one per line</small>
        <textarea name="tips" rows="3">${lines(r.tips)}</textarea></label>
      <label>In ${esc(STATUS.storyteller)}'s words
        <textarea name="story_quote" rows="3">${esc(r.story_quote)}</textarea></label>
      <details class="transcript"><summary>Transcript for reference</summary><p>${esc(e.transcript)}</p></details>
      <p id="edit-err" class="err"></p>
      <button class="btn primary" type="submit">Save recipe</button>
    </form>`;
  document.getElementById("edit-form").onsubmit = async (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    const split = (k) => String(f.get(k) || "").split("\n").map((x) => x.trim()).filter(Boolean);
    const body = {
      title: f.get("title"), description: f.get("description"), servings: f.get("servings"),
      total_time: f.get("total_time"), story_quote: f.get("story_quote"),
      tags: String(f.get("tags") || "").split(","),
      steps: split("steps"), tips: split("tips"),
      ingredients: split("ingredients").map((l) => {
        const parts = l.split("|").map((x) => x.trim());
        return parts.length === 1 ? { quantity: "", item: parts[0], note: "" }
          : { quantity: parts[0], item: parts[1] || "", note: parts.slice(2).join(" | ") };
      }),
    };
    try {
      await api(`/api/recipes/${encodeURIComponent(id)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      location.hash = `#/recipe/${encodeURIComponent(id)}`;
    } catch (err) { document.getElementById("edit-err").textContent = err.message; }
  };
}

/* ---------- Add a memo ---------- */
const STAGES = [
  { key: "uploading", label: "Saving the recording", sub: "Stored on this computer only" },
  { key: "transcribing", label: "Listening", sub: "Speech-to-text with faster-whisper, running locally" },
  { key: "structuring", label: "Writing the recipe", sub: "Local open-weight LLM via Ollama turns rambling into steps" },
  { key: "saving", label: "Adding to the book", sub: "Saved to SQLite" },
];

async function renderAdd() {
  setNav("add");
  if (!STATUS.inference_enabled) {
    view.innerHTML = `
      <div class="empty add-wrap">
        <h2>Adding recipes happens at home</h2>
        <p>This public copy of EchoBook is read-only. New voice memos are transcribed and structured on the family's own
        computer with open-weight models, so recordings never leave it. Finished recipes are then published here.</p>
        <p><a class="btn primary" href="#/">Browse the recipes</a></p>
      </div>`;
    return;
  }
  const o = STATUS.ollama || {};
  const warn = !o.running
    ? `<p class="err">⚠ Ollama isn't running. Start it with <code>ollama serve</code>.</p>`
    : !o.ok ? `<p class="err">⚠ Model <code>${esc(o.model)}</code> isn't pulled yet. Run <code>ollama pull ${esc(o.model)}</code>.</p>` : "";
  view.innerHTML = `
    <div class="add-wrap">
      <h1>Add a voice memo</h1>
      <p style="color:var(--ink-soft);margin-top:0">Drop in an old recording of someone describing a recipe. EchoBook listens, then writes it up as a recipe card. Everything runs on this machine.</p>
      ${warn}
      <label class="drop" id="drop">
        <input type="file" id="file" accept="audio/*,.m4a,.opus,.webm" hidden>
        <h2>Drop a recording here</h2>
        <p>or click to choose a file · mp3, m4a, wav, ogg, webm…</p>
      </label>
      <div id="samples-box"></div>
      <div id="progress"></div>
    </div>`;

  const drop = document.getElementById("drop"), file = document.getElementById("file");
  file.onchange = () => file.files[0] && startUpload(file.files[0]);
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => e.dataTransfer.files[0] && startUpload(e.dataTransfer.files[0]));

  try {
    const samples = await api("/api/samples");
    if (samples.length) {
      document.getElementById("samples-box").innerHTML = `
        <div class="or">or try one of the sample memos</div>
        <div class="samples">${samples.map((s) => `
          <div class="sample">
            <span class="name">${esc(s.name.replace(/^\d+_/, "").replace(/\.\w+$/, "").replace(/_/g, " "))}</span>
            <audio controls preload="none" src="/samples/${encodeURIComponent(s.name)}"></audio>
            <button class="btn primary" data-sample="${esc(s.name)}">Turn into recipe</button>
          </div>`).join("")}</div>`;
      document.querySelectorAll("[data-sample]").forEach((b) => b.onclick = () => startSample(b.dataset.sample));
    }
  } catch {}

  const active = sessionStorage.getItem("echobook-job");
  if (active) watchJob(active);
}

function setBusy(busy) {
  document.querySelectorAll("[data-sample], #file").forEach((el) => el.disabled = busy);
  const drop = document.getElementById("drop");
  if (drop) drop.style.pointerEvents = busy ? "none" : "";
}

function renderProgress(job, local = {}) {
  const box = document.getElementById("progress");
  if (!box) return;
  const order = ["uploading", "queued", "transcribing", "structuring", "saving", "done"];
  const cur = job.stage === "queued" ? "transcribing" : job.stage;
  const curIdx = order.indexOf(cur);
  const elapsed = job.started_at ? Math.round(Date.now() / 1000 - job.started_at) : 0;
  box.innerHTML = `
    <section class="progress" aria-live="polite">
      <h2>${esc(job.source_name || local.name || "Recording")}</h2>
      <ol class="stages">
        ${STAGES.map((s) => {
          const idx = order.indexOf(s.key);
          let cls = "", sub = s.sub, extra = "";
          if (job.stage === "error" && (s.key === (job.failed_stage || "transcribing"))) { cls = "error"; sub = `<span class="err">${esc(job.error)}</span>`; }
          else if (job.stage === "done" || idx < curIdx) cls = "done";
          else if (idx === curIdx) {
            cls = "active";
            if (s.key === "uploading" && local.pct != null) extra = `<div class="bar"><span style="width:${Math.round(local.pct * 100)}%"></span></div>`;
            if (s.key === "transcribing") {
              if (job.stage === "queued") sub = "Waiting for the previous memo to finish…";
              extra = job.progress != null
                ? `<div class="bar"><span style="width:${Math.round(job.progress * 100)}%"></span></div>`
                : `<div class="bar indet"><span></span></div>`;
              if (job.progress === 0) sub += " · loading the Whisper model…";
            }
            if (s.key === "structuring") {
              sub += job.tokens ? ` · ${job.tokens} token${job.tokens === 1 ? "" : "s"} written` : " · reading the transcript…";
              extra = `<div class="bar indet"><span></span></div>`;
            }
          }
          if (s.key === "transcribing" && job.transcript) extra += `<div class="live-transcript">“${esc(job.transcript)}”</div>`;
          return `<li class="stage ${cls}"><span class="dot">${cls === "done" ? "✓" : cls === "error" ? "!" : ""}</span>
            <div><div class="label">${s.label}</div><div class="sub">${sub}</div>${extra}</div></li>`;
        }).join("")}
      </ol>
      ${job.stage !== "done" && job.stage !== "error" && elapsed ? `<div class="sub" style="color:var(--ink-soft);font-size:.85rem">Elapsed ${fmtDuration(elapsed)}</div>` : ""}
      ${job.stage === "done" ? `<p><a class="btn primary" href="#/recipe/${encodeURIComponent(job.recipe_id)}">Open the recipe →</a>
        <span style="color:var(--ink-soft);font-size:.9rem;margin-left:8px">Done in ${fmtDuration(job.finished_at - job.started_at)}</span></p>
        <div id="preview"></div>` : ""}
    </section>`;
}

function startUpload(f) {
  setBusy(true);
  const form = new FormData();
  form.append("file", f);
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/process/upload");
  xhr.upload.onprogress = (e) => e.lengthComputable && renderProgress({ stage: "uploading" }, { name: f.name, pct: e.loaded / e.total });
  xhr.onload = () => {
    let body = {};
    try { body = JSON.parse(xhr.responseText); } catch {}
    if (xhr.status >= 300) { renderProgress({ stage: "error", failed_stage: "uploading", error: body.detail || xhr.statusText }, { name: f.name }); setBusy(false); return; }
    watchJob(body.id);
  };
  xhr.onerror = () => { renderProgress({ stage: "error", failed_stage: "uploading", error: "Upload failed" }, { name: f.name }); setBusy(false); };
  renderProgress({ stage: "uploading" }, { name: f.name, pct: 0 });
  xhr.send(form);
}

async function startSample(name) {
  setBusy(true);
  try {
    const job = await api("/api/process/sample", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
    watchJob(job.id);
  } catch (e) {
    renderProgress({ stage: "error", failed_stage: "uploading", error: e.message }, { name });
    setBusy(false);
  }
}

function watchJob(id) {
  sessionStorage.setItem("echobook-job", id);
  clearInterval(pollTimer);
  let lastStage = "transcribing";
  const tick = async () => {
    let job;
    try { job = await api(`/api/jobs/${id}`); }
    catch { clearInterval(pollTimer); sessionStorage.removeItem("echobook-job"); setBusy(false); return; }
    if (job.stage !== "error") lastStage = job.stage === "queued" ? "transcribing" : job.stage;
    else job.failed_stage = lastStage;
    if (!document.getElementById("progress")) { clearInterval(pollTimer); return; } // navigated away; resume later
    setBusy(!["done", "error"].includes(job.stage));
    renderProgress(job);
    if (job.stage === "done" || job.stage === "error") {
      clearInterval(pollTimer);
      sessionStorage.removeItem("echobook-job");
      if (job.stage === "done") {
        const e = await api(`/api/recipes/${encodeURIComponent(job.recipe_id)}`);
        const prev = document.getElementById("preview");
        if (prev) prev.innerHTML = recipeHTML(e);
      }
    }
  };
  tick();
  pollTimer = setInterval(tick, 1000);
}

/* ---------- Printable book ---------- */
async function renderPrint() {
  setNav("print");
  const items = (await api("/api/recipes")).sort((a, b) => a.recipe.title.localeCompare(b.recipe.title));
  view.innerHTML = `
    <div class="print-intro no-print actions">
      <span style="color:var(--ink-soft)">The whole book, laid out for printing. Use <b>Print → Save as PDF</b>.</span>
      <span style="display:flex;gap:8px;flex-wrap:wrap">
        <a class="btn" href="/api/export/markdown">Download Markdown</a>
        <button class="btn primary" onclick="window.print()">Print / Save as PDF</button>
      </span>
    </div>
    <article class="recipe">
      <div class="book-cover">
        <h1>${esc(STATUS.book_title)}</h1>
        <p>${items.length} family recipes, in ${esc(STATUS.storyteller)}'s own words.</p>
        <p style="font-size:.85rem">Transcribed from voice memos with EchoBook · ${new Date().toLocaleDateString()}</p>
      </div>
      <div class="toc"><h2>Contents</h2><ol>${items.map((e) => `<li>${esc(e.recipe.title)}</li>`).join("")}</ol></div>
    </article>
    ${items.map((e) => recipeHTML(e, { forPrint: true })).join("")}`;
}

/* ---------- Router ---------- */
async function route() {
  clearInterval(pollTimer);
  document.title = "EchoBook";
  const hash = location.hash.replace(/^#/, "") || "/";
  const path = hash.split("?")[0];
  if (path.startsWith("/recipe/") && path.endsWith("/edit")) await renderEdit(decodeURIComponent(path.slice(8, -5)));
  else if (path.startsWith("/recipe/")) await renderRecipe(decodeURIComponent(path.slice(8)));
  else if (path === "/add") await renderAdd();
  else if (path === "/print") await renderPrint();
  else await renderBook();
  view.focus({ preventScroll: true });
  if (!path.startsWith("/?") && path !== "/") window.scrollTo(0, 0);
}

(async function init() {
  try { STATUS = await api("/api/status"); } catch {}
  document.getElementById("footer-models").textContent =
    `Transcribed with faster-whisper (${STATUS.whisper_model || "open-weight Whisper"}) · structured with ${STATUS.llm_model || "a local open-weight LLM"} via Ollama`;
  if (!STATUS.inference_enabled) {
    const b = document.getElementById("mode-banner");
    b.innerHTML = `<strong>Read-only family copy.</strong> Recordings were transcribed and structured offline on the family's own computer with open-weight models. Audio and processing never touched the cloud.`;
    b.hidden = false;
  }
  window.addEventListener("hashchange", route);
  route();
})();
