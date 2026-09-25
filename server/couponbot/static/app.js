/* KGC Coupon Bot dashboard - no build step, vanilla JS (repo house rule). */
"use strict";

const $ = (id) => document.getElementById(id);

/* Everything rendered into innerHTML comes from user-supplied label/code text,
   so it all goes through esc() first - the page is public and unauthenticated. */
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const emoji = (s) => ({
  ok: "✅", used_or_invalid: "⛔", no_coupon: "❔", no_pid: "⛔",
  expired: "⌛", not_available: "⏳", limit_reached: "🚫", error: "❌",
}[s] || "⏳");

const stateName = (s) => ({
  ok: "đã nhận", used_or_invalid: "đã dùng / sai", no_coupon: "code không tồn tại",
  no_pid: "ID sai", expired: "hết hạn", not_available: "chưa mở",
  limit_reached: "hết lượt", error: "lỗi",
}[s] || s);

const codeStatus = (s) => ({
  new: "mới", invalid: "không tồn tại", expired: "hết hạn", used: "đã dùng",
}[s] || s);

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...opts,
  });
  let data = {};
  try { data = await res.json(); } catch (_) { /* non-JSON */ }
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function msg(el, text, cls) {
  el.textContent = text || "";
  el.className = cls || "";
  el.style.fontSize = "13px";
  el.style.marginTop = "8px";
  el.style.minHeight = "18px";
}

function whenText(ts) {
  if (!ts) return "–";
  return new Date(ts * 1000).toLocaleString("vi-VN", { hour12: false });
}

const when = (ts) => (ts ? esc(whenText(ts)) : '<span class="muted">–</span>');

function renderAccList(accs) {
  $("accCount").textContent = accs.length;
  if (!accs.length) {
    $("acclist").innerHTML = "Chưa có Player-ID nào.";
    return;
  }
  let h = '<div class="scroll"><table><thead><tr><th>Player-ID</th><th>Ghi chú</th>' +
          '<th>Thêm lúc</th><th>Thử cuối</th><th>Kết quả</th></tr></thead><tbody>';
  for (const a of accs) {
    const off = a.enabled ? "" : ' <span class="pill off">đã tắt</span>';
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
    $("codelist").innerHTML = "Chưa có code nào.";
    return;
  }
  let h = '<div class="scroll"><table><thead><tr><th>Code</th><th>Trạng thái</th>' +
          '<th>Nguồn</th><th>Phát hiện lúc</th></tr></thead><tbody>';
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
    $("grid").innerHTML = "Cần ít nhất 1 Player-ID và 1 code để thấy ma trận.";
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

function render(data) {
  $("mode").textContent = data.discord_mode === "poll" ? "poll" : "thủ công";
  $("rate").textContent = data.rate_remaining ?? "–";
  $("lastrun").textContent = data.last_run && data.last_run.finished_at
    ? whenText(data.last_run.finished_at) : "chưa chạy";
  $("run").disabled = !!data.running;
  $("run").textContent = data.running ? "Đang chạy…" : "Chạy ngay";

  const accs = data.accounts || [];
  const codes = data.codes || [];
  renderAccList(accs);
  renderCodeList(codes);
  renderMatrix(accs, codes, data.matrix || {});
}

async function refresh() {
  try {
    render(await api("/api/state"));
  } catch (e) {
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

refresh();
setInterval(refresh, 15000);
