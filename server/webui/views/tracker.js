// Live in-battle hero stats. The native XIGNCODE stub logs GameUnit stats to logcat,
// dashboard.py parses them and broadcasts over /ws.
import { ref, reactive, onMounted, onUnmounted, computed } from 'vue';
import { auth } from '../api.js';

const ROLE_COLORS = {
  Toughness: '#3b82f6', Brave: '#ef4444', Element: '#10b981',
  Mystic: '#8b5cf6', Swift: '#f59e0b', Shadow: '#a855f7',
};
const DEFAULT_COLOR = '#64748b';

const STAT_GROUPS = [
  { label: 'Offense', keys: ['ATK', 'MATK', 'ASpd', 'Crit%', 'CritDmg', 'MCrit%', 'MCritDmg', 'DefPen', 'DefDen', 'SkillDmg', 'AtkDmg'] },
  { label: 'Defense', keys: ['Def', 'MDef', 'Shield', 'SShield', 'SAtkShld', 'SMAtkShld', 'DmgRef'] },
  { label: 'Utility', keys: ['MSpd', 'Drain', 'HealEff'] },
];
const PCT_KEYS = new Set(['Crit%', 'CritDmg', 'MCrit%', 'MCritDmg', 'DefPen', 'DefDen',
  'SkillDmg', 'AtkDmg', 'Drain', 'HealEff', 'DmgRef']);

export default {
  setup() {
    const heroes = reactive(new Map());
    const connected = ref(false);
    let ws = null;
    let retry = null;

    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const qs = auth.token ? '?admin_token=' + encodeURIComponent(auth.token) : '';
      ws = new WebSocket(`${proto}//${location.host}/ws${qs}`);
      ws.onopen = () => { connected.value = true; };
      ws.onclose = () => {
        connected.value = false;
        retry = setTimeout(connect, 3000);      // device or server restart - keep trying
      };
      ws.onmessage = (ev) => {
        const d = JSON.parse(ev.data);
        if (d.type !== 'hero_update') return;
        const prev = heroes.get(d.heroId);
        const hp = (d.stats || {}).HP || 0;
        heroes.set(d.heroId, {
          ...d,
          maxHp: Math.max(hp, prev ? prev.maxHp : 0),
          effects: aggregate(d.effects || []),
        });
      };
    };

    const aggregate = (effects) => {
      const by = new Map();
      effects.forEach((e) => {
        const k = `${e.kind}|${e.name}`;
        const cur = by.get(k) || { ...e, count: 0 };
        cur.count++;
        if (!cur.desc && e.desc) cur.desc = e.desc;
        if (e.total && (!cur.total || e.total > cur.total)) { cur.total = e.total; cur.time = e.time; }
        by.set(k, cur);
      });
      return [...by.values()];
    };

    onMounted(connect);
    onUnmounted(() => { clearTimeout(retry); if (ws) { ws.onclose = null; ws.close(); } });

    const list = computed(() => [...heroes.values()]);
    const color = (role) => ROLE_COLORS[role] || DEFAULT_COLOR;

    const groupsFor = (h) => STAT_GROUPS
      .map((g) => ({ label: g.label, keys: g.keys.filter((k) => k in (h.stats || {})) }))
      .filter((g) => g.keys.length);

    const fmtStat = (k, v) => {
      if (typeof v !== 'number') return v;
      if (PCT_KEYS.has(k)) return (Math.round(v * 10) / 10) + '%';
      return v % 1 === 0 ? v.toLocaleString() : v.toFixed(1);
    };

    const hpPct = (h) => (h.maxHp > 0 ? Math.max(0, Math.min(100, ((h.stats.HP || 0) / h.maxHp) * 100)) : 0);
    const clear = () => heroes.clear();

    return { list, connected, color, groupsFor, fmtStat, hpPct, clear };
  },
  template: `
    <div>
      <div class="toolbar panel" style="margin-bottom:14px;border-radius:12px">
        <span class="pill" :class="connected ? 'ok' : 'err'">
          <span class="dot"></span>{{ connected ? 'listening' : 'reconnecting...' }}
        </span>
        <span class="pill">{{ list.length }} hero<span v-if="list.length !== 1">es</span></span>
        <span style="flex:1"></span>
        <button class="btn sm" @click="clear" :disabled="!list.length">Clear</button>
      </div>

      <div class="hero-grid" v-if="list.length">
        <div v-for="h in list" :key="h.heroId" class="hero-card">
          <div class="hc-head">
            <div class="avatar" :style="{ background: 'linear-gradient(135deg,' + color(h.role) + ',rgba(0,0,0,.35))' }">
              {{ (h.name || '?').charAt(0).toUpperCase() }}
            </div>
            <div>
              <div style="font-weight:650">{{ h.name }}</div>
              <div style="font-size:11.5px" :style="{ color: color(h.role) }">{{ h.role }}</div>
            </div>
          </div>
          <div class="hc-body">
            <div style="display:flex;justify-content:space-between;font-size:11.5px;color:var(--text-faint)">
              <span>Health</span>
              <span style="font-family:var(--mono);color:var(--text)">
                {{ Math.round(h.stats.HP || 0).toLocaleString() }}
              </span>
            </div>
            <div class="hp-bar-bg">
              <div class="hp-bar" :style="{ width: hpPct(h) + '%', background: color(h.role) }"></div>
            </div>

            <template v-for="g in groupsFor(h)" :key="g.label">
              <div class="sub-head" style="margin:12px 0 6px">{{ g.label }}</div>
              <div class="stats-grid">
                <div v-for="k in g.keys" :key="k" class="stat-item">
                  <div class="k">{{ k }}</div>
                  <div class="v">{{ fmtStat(k, h.stats[k]) }}</div>
                </div>
              </div>
            </template>

            <div class="sub-head" style="margin:12px 0 6px">Effects</div>
            <div v-if="!h.effects.length" style="font-size:11.5px;color:var(--text-faint)">No active effects</div>
            <div v-for="e in h.effects" :key="e.kind + e.name" class="eff-row" :class="e.kind">
              <div class="eff-head">
                <span class="eff-name">{{ e.name }}</span>
                <span class="tag" v-if="e.count > 1">×{{ e.count }}</span>
                <span class="tag" v-if="e.total">{{ e.time.toFixed(1) }}/{{ e.total.toFixed(1) }}s</span>
              </div>
              <div class="eff-desc" v-if="e.desc">{{ e.desc }}</div>
            </div>
          </div>
        </div>
      </div>

      <div v-else class="panel"><div class="empty">
        <span class="icon">⚔</span>
        Waiting for battle data - enter a battle on the device to populate hero cards.
      </div></div>
    </div>
  `,
};
