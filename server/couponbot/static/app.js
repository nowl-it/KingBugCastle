/* KGC Coupon Bot dashboard - no build step, vanilla JS (repo house rule).
 *
 * Bilingual: every string comes from KGC_I18N (static/i18n.js, JSON in a const)
 * through t(). The language follows the browser on first visit, then whatever
 * the header button last set (localStorage). */
"use strict";

const $ = (id) => document.getElementById(id);
const LANG_KEY = "kgc_coupon_lang";
const DICTS = (typeof KGC_I18N !== "undefined") ? KGC_I18N : { vi: {}, en: {} };

let LANG = (() => {
  try {
    const saved = localStorage.getItem(LANG_KEY);
    if (saved === "vi" || saved === "en") return saved;
  } catch (_) { /* private mode */ }
  return (navigator.language || "").toLowerCase().startsWith("vi") ? "vi" : "en";
})();

function t(key, vars) {
  const dict = DICTS[LANG] && DICTS[LANG][key] !== undefined ? DICTS[LANG] : DICTS.vi || {};
  let s = dict[key] !== undefined ? dict[key] : key;
  if (vars) for (const k in vars) s = s.split("{" + k + "}").join(vars[k]);
  return s;
}

/* Server errors carry a machine `code` (web.py) so the English page is not left
   showing a Vietnamese sentence; `detail` is appended verbatim when present. */
function errText(data, fallback) {
  const code = data && data.code;
  if (code && DICTS[LANG] && DICTS[LANG][code] !== undefined) {
    return data.detail ? `${t(code)}: ${data.detail}` : t(code);
  }
  return (data && data.error) || fallback;
}

/* Everything rendered into innerHTML comes from user-supplied label/code text,
   so it all goes through esc() first - the page is public and unauthenticated. */
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const emoji = (s) => ({
  ok: "✅", used_or_invalid: "⛔", no_coupon: "❔", no_pid: "⛔",
  expired: "⌛", not_available: "⏳", limit_reached: "🚫", error: "❌",
}[s] || "⏳");

const stateName = (s) => (DICTS[LANG] && DICTS[LANG][`s_${s}`] !== undefined ? t(`s_${s}`) : s);

const codeStatus = (s) => (DICTS[LANG] && DICTS[LANG][`st_${s}`] !== undefined ? t(`st_${s}`) : s);

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...opts,
  });
  let data = {};
  try { data = await res.json(); } catch (_) { /* non-JSON */ }
  if (!res.ok) {
    const err = new Error(errText(data, `HTTP ${res.status}`));
    err.data = data;
    throw err;
  }
  return data;
}

function msg(el, text, cls) {
  el.textContent = text || "";
  // keep the `msg` base class: `.msg.err` / `.msg.ok` are what carry the colour
  el.className = "msg" + (cls ? ` ${cls}` : "");
  el.style.fontSize = "13px";
  el.style.marginTop = "8px";
  el.style.minHeight = "18px";
}

function whenText(ts) {
  if (!ts) return "–";
  return new Date(ts * 1000).toLocaleString(LANG === "vi" ? "vi-VN" : "en-GB", { hour12: false });
}

const when = (ts) => (ts ? esc(whenText(ts)) : '<span class="muted">–</span>');

function renderAccList(accs) {
  $("accCount").textContent = accs.length;
  if (!accs.length) {
    $("acclist").textContent = t("empty_acc");
    return;
  }
  let h = '<div class="scroll"><table><thead><tr><th>Player-ID</th>' +
          `<th>${t("th_note")}</th><th>${t("th_added")}</th>` +
          `<th>${t("th_last")}</th><th>${t("th_result")}</th></tr></thead><tbody>`;
  for (const a of accs) {
    const off = a.enabled ? "" : ` <span class="pill off">${t("off")}</span>`;
    h += `<tr><td class="code">${esc(a.uid)}${off}</td>` +
         `<td>${a.label ? esc(a.label) : '<span class="muted">–</span>'}</td>` +
         `<td>${when(a.added_at)}</td><td>${when(a.last_run_at)}</td>` +
         `<td>${a.last_result ? esc(stateName(a.last_result)) : '<span class="muted">–</span>'}</td></tr>`;
  }
  $("acclist").innerHTML = h + "</tbody></table></div>";
}

function renderCodeList(codes) {
  $("codeCount").textContent = codes.length;
  if (!codes.length) {
    $("codelist").textContent = t("empty_codes");
    return;
  }
  let h = '<div class="scroll"><table><thead><tr><th>Code</th>' +
          `<th>${t("th_status")}</th><th>${t("th_source")}</th>` +
          `<th>${t("th_seen")}</th></tr></thead><tbody>`;
  for (const c of codes) {
    const src = String(c.source || "");
    const srcLabel = src.startsWith("discord:") ? "discord" : (src || "–");
    const quote = c.source_text ? ` title="${esc(c.source_text.slice(0, 400))}"` : "";
    h += `<tr><td class="code"${quote}>${esc(c.code)}</td>` +
         `<td><span class="pill">${esc(codeStatus(c.status))}</span></td>` +
         `<td class="muted">${esc(srcLabel)}</td><td>${when(c.first_seen_at)}</td></tr>`;
  }
  $("codelist").innerHTML = h + "</tbody></table></div>";
}

function renderMatrix(accs, codes, mx) {
  if (!accs.length || !codes.length) {
    $("grid").textContent = t("empty_matrix");
    return;
  }
  let h = '<div class="scroll"><table><thead><tr><th>Player-ID</th>';
  for (const c of codes) h += `<th class="code">${esc(c.code)}</th>`;
  h += "</tr></thead><tbody>";

  for (const a of accs) {
    h += `<tr><td class="code">${esc(a.uid)}</td>`;
    for (const c of codes) {
      const st = (mx[a.uid] || {})[c.code];
      h += st
        ? `<td><span class="st" data-s="${st === "ok" ? "ok" : (st === "error" ? "wait" : "bad")}"` +
          ` title="${esc(stateName(st))}">${emoji(st)}</span></td>`
        : '<td><span class="muted">–</span></td>';
    }
    h += "</tr>";
  }
  $("grid").innerHTML = h + "</tbody></table></div>";
}

let lastData = null;

function render(data) {
  lastData = data;
  $("mode").textContent = data.discord_mode === "poll" ? t("mode_poll") : t("mode_manual");
  $("rate").textContent = data.rate_remaining ?? "–";
  $("lastrun").textContent = data.last_run && data.last_run.finished_at
    ? whenText(data.last_run.finished_at) : t("never");
  $("run").disabled = !!data.running;
  $("run").textContent = data.running ? t("running") : t("run_btn");

  const accs = data.accounts || [];
  const codes = data.codes || [];
  renderAccList(accs);
  renderCodeList(codes);
  renderMatrix(accs, codes, data.matrix || {});
}

function applyLang() {
  document.documentElement.lang = LANG;
  for (const el of document.querySelectorAll("[data-i18n]")) el.textContent = t(el.dataset.i18n);
  for (const el of document.querySelectorAll("[data-i18n-html]")) el.innerHTML = t(el.dataset.i18nHtml);
  for (const el of document.querySelectorAll("[data-i18n-ph]")) el.placeholder = t(el.dataset.i18nPh);
  $("lang").textContent = LANG === "vi" ? "EN" : "VI";
  if (lastData) render(lastData);   // tables carry translated headers too
}

async function refresh() {
  try {
    render(await api("/api/state"));
  } catch (e) {
    $("grid").textContent = t("grid_error", { err: e.message });
  }
}

$("acctForm").onsubmit = async (e) => {
  e.preventDefault();
  const out = $("acctMsg");
  try {
    msg(out, t("checking_id"));
    const r = await api("/api/accounts", {
      method: "POST",
      body: JSON.stringify({ uid: $("uid").value, label: $("label").value }),
    });
    msg(out, t("added_ok", { uid: r.uid }), "ok");
    $("uid").value = ""; $("label").value = "";
    refresh();
  } catch (err) { msg(out, `✗ ${err.message}`, "err"); }
};

$("codeForm").onsubmit = async (e) => {
  e.preventDefault();
  const out = $("codeMsg");
  try {
    const r = await api("/api/codes", { method: "POST", body: JSON.stringify({ code: $("code").value }) });
    msg(out, r.new ? t("code_added", { code: r.code }) : t("code_exists", { code: r.code }), "ok");
    $("code").value = "";
    refresh();
  } catch (err) { msg(out, `✗ ${err.message}`, "err"); }
};

$("run").onclick = async () => {
  try {
    await api("/api/run", { method: "POST" });
    $("run").disabled = true; $("run").textContent = t("running");
    setTimeout(refresh, 1500);
  } catch (e) { alert(e.message); }
};

$("lang").onclick = () => {
  LANG = LANG === "vi" ? "en" : "vi";
  try { localStorage.setItem(LANG_KEY, LANG); } catch (_) { /* private mode */ }
  applyLang();
};

applyLang();
refresh();
setInterval(refresh, 15000);
