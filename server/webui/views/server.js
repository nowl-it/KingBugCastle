// Read-only window onto the game server (:8080), proxied through this origin so the
// UI needs one host and one token. Mutating endpoints (restart, config save) are
// deliberately not proxied - they live on the game server.
import { ref, onMounted, onUnmounted, computed } from 'vue';
import { api, fmt } from '../api.js';
import { store } from '../store.js';

export default {
  setup() {
    const section = ref('system');
    const data = ref(null);
    const error = ref(null);
    const auto = ref(true);
    const q = ref('');
    let timer = null;

    const SECTIONS = [
      ['system', 'System'], ['logs', 'Logs'], ['routes', 'Routes'],
      ['cdn', 'CDN bundles'], ['config', 'Config'],
    ];

    const load = async () => {
      const r = await api('/server/' + section.value).catch((e) => ({ ok: false, error: e.message }));
      if (r.ok) { data.value = r.data; error.value = null; } else { data.value = null; error.value = r.error || 'unreachable'; }
    };

    const pick = (s) => { section.value = s; load(); };

    onMounted(() => {
      load();
      timer = setInterval(() => { if (auto.value) load(); }, 5000);
    });
    onUnmounted(() => clearInterval(timer));

    const logLines = computed(() => {
      if (section.value !== 'logs' || !Array.isArray(data.value)) return '';
      const needle = q.value.trim().toLowerCase();
      return data.value
        .filter((l) => !needle || String(l).toLowerCase().includes(needle))
        .join('\n');
    });

    const routes = computed(() => {
      if (section.value !== 'routes' || !data.value) return [];
      const needle = q.value.trim().toLowerCase();
      return (data.value.routes || []).filter((r) => !needle || r.path.toLowerCase().includes(needle));
    });

    const cdnFiles = computed(() => (section.value === 'cdn' && data.value ? data.value.files || [] : []));

    return { store, SECTIONS, section, pick, data, error, auto, q, load, logLines, routes, cdnFiles, fmt };
  },
  template: `
    <div class="panel">
      <div class="toolbar">
        <button v-for="[id, label] in SECTIONS" :key="id" class="btn sm"
                :class="{ primary: section === id }" @click="pick(id)">{{ label }}</button>
        <span style="flex:1"></span>
        <input v-if="section === 'logs' || section === 'routes'" class="input" style="width:200px"
               v-model="q" placeholder="Filter...">
        <label class="pill" style="cursor:pointer">
          <input type="checkbox" v-model="auto" style="margin:0"> auto-refresh
        </label>
        <button class="btn sm" @click="load">Refresh</button>
      </div>

      <div v-if="error" class="empty">
        <span class="icon">🔌</span>
        Game server unreachable ({{ store.status ? store.status.serverUrl : '' }})<br>
        <span style="font-size:12px">{{ error }}</span>
      </div>

      <template v-else-if="data">
        <div v-if="section === 'system'" class="panel-body">
          <div class="grid stats">
            <div class="stat-card"><div class="val small">{{ data.version }}</div><div class="lbl">Version</div></div>
            <div class="stat-card"><div class="val small">{{ data.patchFolder }}</div><div class="lbl">Patch folder</div></div>
            <div class="stat-card"><div class="val small">{{ data.uptimeStr }}</div><div class="lbl">Uptime</div></div>
            <div class="stat-card"><div class="val">{{ data.routeCount }}</div><div class="lbl">Routes</div></div>
            <div class="stat-card"><div class="val">{{ data.overrideCount }}</div><div class="lbl">Overrides</div></div>
            <div class="stat-card"><div class="val">{{ data.cdmFiles }}</div><div class="lbl">CDN files</div></div>
            <div class="stat-card"><div class="val">{{ data.playerCount }}</div><div class="lbl">Players</div></div>
            <div class="stat-card"><div class="val">{{ data.logLines }}</div><div class="lbl">Log lines</div></div>
          </div>
          <span class="hint">Started {{ data.startTime }}</span>
        </div>

        <pre v-else-if="section === 'logs'" class="logs">{{ logLines || 'No matching log lines.' }}</pre>

        <div v-else-if="section === 'routes'" class="table-wrap">
          <table>
            <thead><tr><th>Path</th><th>Model</th><th class="num">Overridden</th></tr></thead>
            <tbody>
              <tr v-for="r in routes" :key="r.path">
                <td><code>{{ r.path }}</code></td>
                <td style="color:var(--text-dim)">{{ r.model }}</td>
                <td class="num"><span class="tag" :class="r.overridden ? 'ok' : ''">
                  {{ r.overridden ? 'yes' : '—' }}</span></td>
              </tr>
            </tbody>
          </table>
          <div class="hint" style="padding:10px 14px">{{ routes.length }} of {{ data.total }} routes</div>
        </div>

        <div v-else-if="section === 'cdn'" class="table-wrap">
          <table>
            <thead><tr><th>Bundle</th><th class="num">Size</th></tr></thead>
            <tbody>
              <tr v-for="f in cdnFiles" :key="f.name">
                <td><code>{{ f.name }}</code></td>
                <td class="num">{{ fmt.num(f.size) }} B</td>
              </tr>
            </tbody>
          </table>
        </div>

        <pre v-else class="logs">{{ JSON.stringify(data, null, 2) }}</pre>
      </template>
    </div>
  `,
};
