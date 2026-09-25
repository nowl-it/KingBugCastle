/* KGC Coupon Bot dashboard - no build step, vanilla JS (repo house rule). */
"use strict";

const $ = (id) => document.getElementById(id);
const emoji = (s) => ({
  ok: "✅", used_or_invalid: "⛔", no_coupon: "❔", no_pid: "⛔",
  expired: "⌛", not_available: "⏳", limit_reached: "🚫", error: "❌",
}[s] || "⏳");

const stateName = (s) => ({
  ok: "đã nhận", used_or_invalid: "đã dùng / sai", no_coupon: "code không tồn tại",
  no_pid: "ID sai", expired: "hết hạn", not_available: "chưa mở",
  limit_reached: "hết lượt", error: "lỗi",
}[s] || s);

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...opts,
  });
  let data = {};
  try { data = await res.json(); } catch (_) { /* non-JSON */ }
  if (res.status === 401) { showLogin(); throw new Error(data.error || "login required"); }
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function showLogin() { $("login").hidden = false; }
function hideLogin() { $("login").hidden = true; $("logout").hidden = false; }

function msg(el, text, cls) {
  el.textContent = text || "";
  el.className = cls || "";
  el.style.fontSize = "13px";
  el.style.marginTop = "8px";
  el.style.minHeight = "18px";
}

function when(ts) {
  if (!ts) return "–";
  const d = new Date(ts * 1000);
  return d.toLocaleString("vi-VN", { hour12: false });
}

function render(data) {
  $("mode").textContent = data.discord_mode === "poll" ? "poll" : "thủ công";
  $("rate").textContent = data.rate_remaining ?? "–";
  $("lastrun").textContent = data.last_run && data.last_run.finished_at
    ? when(data.last_run.finished_at) : "chưa chạy";
  $("run").disabled = !!data.running;
  $("run").textContent = data.running ? "Đang chạy…" : "Chạy ngay";

  const codes = (data.codes || []).slice(0, 12);
  const accs = (data.accounts || []).filter((a) => a.enabled);
  const disabled = (data.accounts || []).filter((a) => !a.enabled);
  const mx = data.matrix || {};

  if (!accs.length && !codes.length) {
    $("grid").innerHTML = "Chưa có Player-ID lẫn code nào.";
    return;
  }

  let html = "<table><thead><tr><th>Player-ID</th>";
  for (const c of codes) html += `<th class="code">${c.code}<br><span class="pill">${c.status}</span></th>`;
  html += "<th></th></tr></thead><tbody>";

  for (const a of accs) {
    html += `<tr><td>${a.uid}${a.label ? ` <span class="muted">(${a.label})</span>` : ""}`;
    for (const c of codes) {
      const st = (mx[a.uid] || {})[c.code];
      html += st
        ? `<td><span class="st" data-s="${st === "ok" ? "ok" : (st === "error" ? "wait" : "bad")}"
             title="${stateName(st)}">${emoji(st)}</span></td>`
        : `<td><span class="muted">–</span></td>`;
    }
    html += `<td><button class="link" data-del="${a.uid}">tắt</button></td></tr>`;
  }
  html += "</tbody></table>";

  if (disabled.length) {
    html += `<div class="muted" style="margin-top:8px">Đã tắt: ${
      disabled.map((a) => `${a.uid} <button class="link" data-on="${a.uid}">bật lại</button>`).join(", ")
    }</div>`;
  }
  if (!codes.length) html += '<div class="muted" style="margin-top:8px">Chưa có code nào.</div>';
  $("grid").innerHTML = html;

  for (const btn of document.querySelectorAll("[data-del]"))
    btn.onclick = async () => { await api(`/api/accounts/${btn.dataset.del}`, { method: "DELETE" }); refresh(); };
  for (const btn of document.querySelectorAll("[data-on]"))
    btn.onclick = async () => { await api(`/api/accounts/${btn.dataset.on}/enable`, { method: "POST" }); refresh(); };
}

async function refresh() {
  try {
    hideLogin();
    render(await api("/api/state"));
  } catch (e) {
    if (!$("login").hidden) return;
    $("grid").textContent = `Lỗi: ${e.message}`;
  }
}

$("acctForm").onsubmit = async (e) => {
  e.preventDefault();
  const out = $("acctMsg");
  try {
    msg(out, "Đang kiểm tra ID…");
    const r = await api("/api/accounts", {
      method: "POST",
      body: JSON.stringify({ uid: $("uid").value, label: $("label").value }),
    });
    msg(out, `✓ ${r.uid} hợp lệ, đã lưu.`, "ok");
    $("uid").value = ""; $("label").value = "";
    refresh();
  } catch (err) { msg(out, `✗ ${err.message}`, "err"); }
};

$("codeForm").onsubmit = async (e) => {
  e.preventDefault();
  const out = $("codeMsg");
  try {
    const r = await api("/api/codes", { method: "POST", body: JSON.stringify({ code: $("code").value }) });
    msg(out, r.new ? `✓ Đã thêm ${r.code}.` : `${r.code} đã có sẵn.`, "ok");
    $("code").value = "";
    refresh();
  } catch (err) { msg(out, `✗ ${err.message}`, "err"); }
};

$("run").onclick = async () => {
  try {
    await api("/api/run", { method: "POST" });
    $("run").disabled = true; $("run").textContent = "Đang chạy…";
    setTimeout(refresh, 1500);
  } catch (e) { alert(e.message); }
};

$("loginForm").onsubmit = async (e) => {
  e.preventDefault();
  try {
    await api("/api/login", { method: "POST", body: JSON.stringify({ password: $("pw").value }) });
    $("pw").value = "";
    hideLogin(); refresh();
  } catch (err) { $("loginMsg").textContent = err.message; }
};

$("logout").onclick = async () => { await api("/api/logout", { method: "POST" }); location.reload(); };

refresh();
setInterval(refresh, 15000);
