// ============ tabs ============
document.querySelectorAll('.tab').forEach(t => {
    t.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
        document.querySelectorAll('.view').forEach(x => x.classList.remove('active'));
        t.classList.add('active');
        document.getElementById('view-' + t.dataset.tab).classList.add('active');
        if (t.dataset.tab === 'admin') loadAdmin();
    });
});

function toast(msg, kind) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.className = 'toast show ' + (kind || '');
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.className = 'toast'; }, 2600);
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// ============ TRACKER ============
const grid = document.getElementById('hero-grid');
const statusBadge = document.getElementById('connection-status');
const statusLabel = statusBadge.querySelector('.status-label');
const heroCount = document.getElementById('hero-count');
const emptyState = document.getElementById('empty-state');
const heroes = new Map();

const ROLE_COLORS = {
    'Toughness': { accent: '#3b82f6', text: '#60a5fa' },
    'Brave': { accent: '#ef4444', text: '#f87171' },
    'Element': { accent: '#10b981', text: '#34d399' },
    'Mystic': { accent: '#8b5cf6', text: '#a78bfa' },
    'Swift': { accent: '#f59e0b', text: '#fbbf24' },
    'Shadow': { accent: '#a855f7', text: '#c084fc' },
};
const DEFAULT_COLOR = { accent: '#64748b', text: '#94a3b8' };

const STAT_GROUPS = [
    { label: 'Offense', keys: ['ATK', 'MATK', 'ASpd', 'Crit%', 'CritDmg', 'MCrit%', 'MCritDmg', 'DefPen', 'DefDen', 'SkillDmg', 'AtkDmg'] },
    { label: 'Defense', keys: ['Def', 'MDef', 'Shield', 'SShield', 'SAtkShld', 'SMAtkShld', 'DmgRef'] },
    { label: 'Utility', keys: ['MSpd', 'Drain', 'HealEff'] },
];

function connect() {
    const ws = new WebSocket(`ws://${window.location.host}/ws`);
    ws.onopen = () => { statusBadge.className = 'status-badge connected'; statusLabel.textContent = 'Connected'; };
    ws.onclose = () => { statusBadge.className = 'status-badge disconnected'; statusLabel.textContent = 'Reconnecting…'; setTimeout(connect, 3000); };
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'hero_update') updateHero(data);
    };
}

function getRoleColor(role) { return ROLE_COLORS[role] || DEFAULT_COLOR; }

function updateHero(data) {
    let card = heroes.get(data.heroId);
    if (!card) {
        card = createHeroCard(data);
        if (emptyState) emptyState.style.display = 'none';
        grid.appendChild(card.element);
        heroes.set(data.heroId, card);
        heroCount.textContent = `${heroes.size} hero${heroes.size !== 1 ? 'es' : ''}`;
    }
    updateStats(card, data);
    updateEffects(card, data);
}

function createHeroCard(data) {
    const el = document.createElement('div');
    el.className = 'hero-card';
    const colors = getRoleColor(data.role);
    const initial = (data.name || '?').charAt(0).toUpperCase();
    el.innerHTML = `
        <div class="card-header">
            <div class="hero-avatar" style="background: linear-gradient(135deg, ${colors.accent}, rgba(0,0,0,0.35))">
                <span class="avatar-initial">${escapeHtml(initial)}</span>
            </div>
            <div class="hero-meta">
                <div class="hero-name">${escapeHtml(data.name)}</div>
                <div class="hero-role" style="color:${colors.text}">${escapeHtml(data.role || 'Unknown')}</div>
            </div>
        </div>
        <div class="card-body">
            <div class="hp-section">
                <div class="hp-top"><span class="hp-label">Health</span><span class="hp-text">0</span></div>
                <div class="hp-bar-container"><div class="hp-bar" style="background: linear-gradient(90deg, ${colors.accent}, ${colors.text})"></div></div>
            </div>
            <div class="stats-wrap"></div>
            <div class="section-label">Effects</div>
            <div class="effects-section"><div class="effects-list"></div></div>
        </div>`;
    return {
        element: el, statElements: {}, maxHp: 0, heroId: data.heroId,
        statsWrap: el.querySelector('.stats-wrap'),
        hpBar: el.querySelector('.hp-bar'),
        hpText: el.querySelector('.hp-text'),
        effectsList: el.querySelector('.effects-list'),
        effectRows: new Map(), effectsEmpty: false, builtGroups: false,
    };
}

function updateStats(card, data) {
    const stats = data.stats || {};
    if (!card.builtGroups) {
        STAT_GROUPS.forEach(group => {
            const present = group.keys.filter(k => k in stats);
            if (!present.length) return;
            const label = document.createElement('div');
            label.className = 'section-label';
            label.textContent = group.label;
            const gridEl = document.createElement('div');
            gridEl.className = 'stats-grid';
            present.forEach(key => {
                const div = document.createElement('div');
                div.className = 'stat-item';
                div.innerHTML = `<span class="stat-label">${escapeHtml(key)}</span><span class="stat-value">${formatValue(key, stats[key])}</span>`;
                gridEl.appendChild(div);
                card.statElements[key] = { valueEl: div.querySelector('.stat-value'), container: div, current: stats[key] };
            });
            card.statsWrap.appendChild(label);
            card.statsWrap.appendChild(gridEl);
        });
        card.builtGroups = true;
    }
    Object.entries(stats).forEach(([key, value]) => {
        if (key === 'HP' && value > card.maxHp) card.maxHp = value;
        const sd = card.statElements[key];
        if (sd && sd.current !== value) {
            sd.valueEl.textContent = formatValue(key, value);
            sd.current = value;
            sd.container.classList.remove('flash');
            void sd.container.offsetWidth;
            sd.container.classList.add('flash');
        }
    });
    const hp = stats['HP'] || 0;
    if (hp > card.maxHp) card.maxHp = hp;
    card.hpText.textContent = Math.round(hp).toLocaleString();
    const pct = card.maxHp > 0 ? Math.max(0, Math.min(100, (hp / card.maxHp) * 100)) : 0;
    card.hpBar.style.width = `${pct}%`;
}

function updateEffects(card, data) {
    const effects = data.effects || [];
    const agg = new Map();
    effects.forEach(e => {
        const k = `${e.kind}|${e.name}`;
        const cur = agg.get(k) || { key: k, name: e.name, kind: e.kind, desc: e.desc, count: 0, time: null, total: null };
        cur.count++;
        if (!cur.desc && e.desc) cur.desc = e.desc;
        if (e.total && (!cur.total || e.total > cur.total)) { cur.total = e.total; cur.time = e.time; }
        agg.set(k, cur);
    });
    if (!agg.size) {
        if (!card.effectsEmpty) {
            card.effectRows.forEach(r => r.row.remove());
            card.effectRows.clear();
            card.effectsList.innerHTML = '<span class="effects-none">No active effects</span>';
            card.effectsEmpty = true;
        }
        return;
    }
    if (card.effectsEmpty) { card.effectsList.innerHTML = ''; card.effectsEmpty = false; }
    for (const [k, r] of card.effectRows) {
        if (!agg.has(k)) { r.row.remove(); card.effectRows.delete(k); }
    }
    for (const [k, e] of agg) {
        let r = card.effectRows.get(k);
        if (!r) { r = createEffectRow(e); card.effectsList.appendChild(r.row); card.effectRows.set(k, r); }
        updateEffectRow(r, e);
    }
}

function createEffectRow(e) {
    const row = document.createElement('div');
    row.className = `effect-row ${e.kind}`;
    row.innerHTML = `
        <div class="eff-head">
            <span class="eff-dot"></span>
            <span class="eff-name" title="${escapeHtml(e.name)}">${escapeHtml(e.name)}</span>
            <span class="chip-count" style="display:none"></span>
            <span class="eff-kind">${escapeHtml(e.kind)}</span>
            <div class="eff-dur" style="display:none"><div class="eff-dur-bar"></div></div>
            <span class="eff-dur-text" style="display:none"></span>
        </div>
        ${e.desc ? `<div class="eff-desc">${escapeHtml(e.desc)}</div>` : ''}`;
    return { row, count: row.querySelector('.chip-count'), dur: row.querySelector('.eff-dur'),
        durBar: row.querySelector('.eff-dur-bar'), durText: row.querySelector('.eff-dur-text'),
        lastCount: -1, lastPct: -1, lastText: '' };
}

function updateEffectRow(r, e) {
    if (e.count !== r.lastCount) {
        if (e.count > 1) { r.count.textContent = `×${e.count}`; r.count.style.display = ''; }
        else r.count.style.display = 'none';
        r.lastCount = e.count;
    }
    if (e.total) {
        const pct = Math.max(0, Math.min(100, (e.time / e.total) * 100));
        const txt = `${e.time.toFixed(1)}/${e.total.toFixed(1)}s`;
        if (pct !== r.lastPct) { r.durBar.style.width = `${pct}%`; r.dur.style.display = ''; r.lastPct = pct; }
        if (txt !== r.lastText) { r.durText.textContent = txt; r.durText.style.display = ''; r.lastText = txt; }
    } else if (r.lastPct !== -1) {
        r.dur.style.display = 'none'; r.durText.style.display = 'none'; r.lastPct = -1;
    }
}

function formatValue(key, value) {
    if (typeof value !== 'number') return value;
    const pctKeys = ['Crit%', 'CritDmg', 'MCrit%', 'MCritDmg', 'DefPen', 'DefDen', 'SkillDmg', 'AtkDmg', 'Drain', 'HealEff', 'DmgRef'];
    if (pctKeys.includes(key)) return (Math.round(value * 10) / 10) + '%';
    return value % 1 === 0 ? value.toLocaleString() : value.toFixed(1);
}

connect();

// ============ ADMIN ============
let selectedPlayer = null;
let CATALOG = null;        // {Item:[{id,name,sub}], Unit:[...], ...}
let GRANTABLE = [];        // reward types that actually mutate player state
const CURRENCY_TYPES = ['', 'Gold', 'Cash', 'Heart'];

async function api(path, opts) {
    const res = await fetch('/api' + path, opts);
    if (!res.ok) {
        let msg = res.statusText;
        try { msg = (await res.json()).detail || msg; } catch {}
        throw new Error(msg);
    }
    return res.json();
}

async function loadAdmin() {
    try {
        const s = await api('/status');
        document.getElementById('st-version').textContent = s.version;
        document.getElementById('st-patch').textContent = s.patchFolder;
        document.getElementById('st-players').textContent = s.players;
        document.getElementById('st-heroes').textContent = s.heroesLoaded;
    } catch (e) { toast('Status: ' + e.message, 'err'); }
    if (!CATALOG) {
        try { const c = await api('/catalog'); CATALOG = c.catalog; GRANTABLE = c.grantable || []; }
        catch (e) { console.warn('catalog load failed', e); }
    }
    loadPlayers();
}

async function loadPlayers() {
    const list = document.getElementById('player-list');
    try {
        const players = await api('/players');
        list.innerHTML = '';
        if (!players.length) { list.innerHTML = '<div class="posts-none" style="padding:12px">No player saves found.</div>'; return; }
        players.forEach(p => {
            const el = document.createElement('button');
            el.className = 'player-item' + (p.id === selectedPlayer ? ' active' : '');
            el.innerHTML = `
                <div class="pi-name"><span>${escapeHtml(p.name || p.id)}</span><span class="pi-id">${escapeHtml(p.id)}</span></div>
                <div class="pi-meta">G ${Number(p.gold||0).toLocaleString()} · C ${Number(p.cash||0).toLocaleString()} · ♥ ${p.heart||0} · Lv ${p.level||0} · ✉ ${p.postCount||0}</div>`;
            el.addEventListener('click', () => selectPlayer(p.id));
            list.appendChild(el);
        });
    } catch (e) { list.innerHTML = `<div class="posts-none" style="padding:12px">Error: ${escapeHtml(e.message)}</div>`; }
}

async function selectPlayer(pid) {
    selectedPlayer = pid;
    document.querySelectorAll('.player-item').forEach(el => el.classList.remove('active'));
    try {
        const d = await api('/player/' + encodeURIComponent(pid));
        renderEditor(d.summary, d.posts);
        loadPlayers();
    } catch (e) { toast(e.message, 'err'); }
}

function renderEditor(s, posts) {
    document.getElementById('editor-title').textContent = `${s.name || s.id}`;
    const body = document.getElementById('editor-body');
    body.innerHTML = `
        <div class="sub-head">Identity &amp; Currencies</div>
        <div class="field-grid">
            <div class="field"><label>Name</label><input class="input" id="f-name" value="${escapeHtml(s.name || '')}"></div>
            <div class="field"><label>Castle Name</label><input class="input" id="f-castleName" value="${escapeHtml(s.castleName || '')}"></div>
            <div class="field"><label>Gold</label><input class="input" id="f-gold" type="number" value="${s.gold || 0}"></div>
            <div class="field"><label>Cash</label><input class="input" id="f-cash" type="number" value="${s.cash || 0}"></div>
            <div class="field"><label>Heart</label><input class="input" id="f-heart" type="number" value="${s.heart || 0}"></div>
            <div class="field"><label>Level</label><input class="input" id="f-level" type="number" value="${s.level || 0}"></div>
        </div>
        <div class="btn-row"><button class="btn primary" id="btn-save">Save changes</button></div>

        <div class="divider"></div>

        <div class="sub-head">Send Mail</div>
        <div class="field-grid">
            <div class="field full">
                <label>Title <span class="counter" id="c-title">0/80</span></label>
                <input class="input" id="m-title" maxlength="80" placeholder="Plain text - do NOT type @raw: (server adds it)">
            </div>
            <div class="field full">
                <label>Body <span class="counter" id="c-text">0/300</span></label>
                <textarea class="textarea" id="m-text" maxlength="300" placeholder="Message body..."></textarea>
                <span class="hint" id="m-emoji-hint" style="display:none"></span>
            </div>
            <div class="field"><label>Reward Type</label>
                <select class="select" id="m-rewardType">
                    <option value="">None</option>
                    <optgroup label="Currency"><option>Gold</option><option>Cash</option><option>Heart</option></optgroup>
                    <optgroup label="Grantable"><option>Item</option><option>Unit</option><option>UnitSoul</option><option>Card</option></optgroup>
                    <optgroup label="Display only (gift as Item box)"><option>Artifact</option><option>Treasure</option><option>Accessory</option></optgroup>
                </select>
            </div>
            <div class="field"><label>Reward Amount</label><input class="input" id="m-rewardAmount" type="number" min="0" value="0"></div>
            <div class="field full" id="m-id-field" style="display:none">
                <label>Reward Item <span class="counter" id="m-id-note"></span></label>
                <input class="input" id="m-rewardId" list="m-id-list" placeholder="Search by name or id...">
                <datalist id="m-id-list"></datalist>
            </div>
            <div class="field"><label>Expires (days)</label><input class="input" id="m-days" type="number" min="1" max="365" value="30"></div>
        </div>
        <span class="hint">Server auto-wraps title/body with <code>@raw:</code> so text renders verbatim (no Localizer). Leading spaces &amp; a typed <code>@raw:</code> are stripped.</span>
        <div class="btn-row"><button class="btn primary" id="btn-mail">Send mail</button></div>

        <div class="divider"></div>

        <div class="sub-head">Inbox (${posts.length})</div>
        <div class="posts-list" id="posts-list"></div>`;

    document.getElementById('btn-save').addEventListener('click', savePlayer);
    document.getElementById('btn-mail').addEventListener('click', sendMail);
    wireMailForm();
    renderPosts(posts);
}

// live char counters + a soft warning for post-Unicode-6.0 emoji (>= U+1F900, e.g.
// 🤑) that the game's bundled emoji font lacks a glyph for - the text still delivers
// intact, only that codepoint renders blank. Common emoji (👑💰🔥, <= 6.0) are fine.
function wireMailForm() {
    const t = document.getElementById('m-title');
    const b = document.getElementById('m-text');
    const ct = document.getElementById('c-title');
    const cb = document.getElementById('c-text');
    const hint = document.getElementById('m-emoji-hint');
    const upd = () => {
        ct.textContent = `${t.value.length}/80`;
        cb.textContent = `${b.value.length}/300`;
        const newEmoji = [...(t.value + b.value)].some(c => c.codePointAt(0) >= 0x1F900);
        hint.style.display = newEmoji ? '' : 'none';
        if (newEmoji) hint.textContent = '⚠ Emoji đời mới (Unicode 8.0+) có thể không hiển thị - font game cũ. Dùng emoji phổ biến 😀👍❤️🔥👑💰.';
    };
    t.addEventListener('input', upd);
    b.addEventListener('input', upd);
    upd();

    // reward type -> show/hide the id picker + fill the datalist from the catalog
    const rt = document.getElementById('m-rewardType');
    const idField = document.getElementById('m-id-field');
    const idList = document.getElementById('m-id-list');
    const idNote = document.getElementById('m-id-note');
    const onType = () => {
        const type = rt.value;
        const needsId = !CURRENCY_TYPES.includes(type);
        idField.style.display = needsId ? '' : 'none';
        if (!needsId) return;
        const list = (CATALOG && CATALOG[type]) || [];
        idList.innerHTML = list.map(e =>
            `<option value="${e.id} — ${escapeHtml(e.name)}${e.sub ? ' [' + escapeHtml(e.sub) + ']' : ''}"></option>`).join('');
        const grant = GRANTABLE.includes(type);
        idNote.textContent = `${list.length} items · ${grant ? 'granted to inventory' : 'display only - gift as Item box'}`;
        idNote.style.color = grant ? 'var(--text-faint)' : 'var(--warn)';
    };
    rt.addEventListener('change', onType);
    onType();
}

function renderPosts(posts) {
    const wrap = document.getElementById('posts-list');
    if (!posts.length) { wrap.innerHTML = '<div class="posts-none">No mail in this inbox.</div>'; return; }
    wrap.innerHTML = '';
    posts.forEach(p => {
        const el = document.createElement('div');
        el.className = 'post-item';
        const reward = p.rewardType ? `${p.rewardType} ×${Number(p.rewardAmount || 0).toLocaleString()}` : '';
        el.innerHTML = `
            <div class="post-top">
                <span class="post-title">${escapeHtml(p.title || '(no title)')}</span>
                <button class="btn danger ghost" data-id="${p.id}">Delete</button>
            </div>
            ${p.text ? `<div class="post-text">${escapeHtml(p.text)}</div>` : ''}
            ${reward ? `<div class="post-reward">${escapeHtml(reward)} · until ${escapeHtml((p.untilAt || '').slice(0, 10))}</div>` : ''}`;
        el.querySelector('button').addEventListener('click', () => deleteMail(p.id));
        wrap.appendChild(el);
    });
}

async function savePlayer() {
    if (!selectedPlayer) return;
    const patch = {
        name: document.getElementById('f-name').value,
        castleName: document.getElementById('f-castleName').value,
        gold: +document.getElementById('f-gold').value,
        cash: +document.getElementById('f-cash').value,
        heart: +document.getElementById('f-heart').value,
        level: +document.getElementById('f-level').value,
    };
    try {
        await api('/player/' + encodeURIComponent(selectedPlayer), {
            method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch),
        });
        toast('Saved', 'ok');
        loadPlayers();
    } catch (e) { toast(e.message, 'err'); }
}

async function sendMail() {
    if (!selectedPlayer) return;
    // trim + strip any user-typed @raw: (server adds it; a manual one or leading space
    // double-prefixes and shows the literal '@raw:' in-game). Backend re-validates too.
    const title = document.getElementById('m-title').value.trim().replace(/^(@raw:\s*)+/i, '');
    const text = document.getElementById('m-text').value.trim().replace(/^(@raw:\s*)+/i, '');
    if (!title && !text) { toast('Cần nhập tiêu đề hoặc nội dung', 'err'); return; }
    const days = +document.getElementById('m-days').value;
    const amt = +document.getElementById('m-rewardAmount').value;
    if (!Number.isFinite(days) || days < 1) { toast('Số ngày hết hạn phải >= 1', 'err'); return; }
    if (!Number.isFinite(amt) || amt < 0) { toast('Reward amount không hợp lệ', 'err'); return; }
    const rewardType = document.getElementById('m-rewardType').value;
    let rewardId = 0;
    if (!CURRENCY_TYPES.includes(rewardType)) {
        // datalist value is "123 — Name [sub]"; take the leading integer
        rewardId = parseInt(document.getElementById('m-rewardId').value, 10);
        if (!Number.isInteger(rewardId)) { toast('Chọn reward item (id)', 'err'); return; }
    }
    const body = { title, text, rewardType, rewardId, rewardAmount: amt, days };
    try {
        const d = await api('/player/' + encodeURIComponent(selectedPlayer) + '/mail', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
        });
        toast('Mail sent', 'ok');
        document.getElementById('m-title').value = '';
        document.getElementById('m-text').value = '';
        renderPosts(d.posts);
        loadPlayers();
    } catch (e) { toast(e.message, 'err'); }
}

async function deleteMail(id) {
    if (!selectedPlayer) return;
    try {
        const d = await api('/player/' + encodeURIComponent(selectedPlayer) + '/mail/' + id, { method: 'DELETE' });
        toast('Mail deleted', 'ok');
        renderPosts(d.posts);
        loadPlayers();
    } catch (e) { toast(e.message, 'err'); }
}

document.getElementById('btn-refresh').addEventListener('click', loadAdmin);
