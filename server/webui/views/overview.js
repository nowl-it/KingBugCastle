import { ref, onMounted, computed } from 'vue';
import { api, fmt } from '../api.js';
import { store } from '../store.js';

export default {
  setup() {
    const sys = ref(null);
    const load = async () => {
      const r = await api('/server/system').catch(() => null);
      sys.value = r && r.ok ? r.data : null;
    };
    onMounted(load);

    const totals = computed(() => {
      const acc = (k) => store.players.reduce((n, p) => n + ((p.counts || {})[k] || 0), 0);
      return { cards: acc('cards'), accessories: acc('accessories'), posts: acc('posts'), items: acc('items') };
    });

    return { store, sys, fmt, totals, load };
  },
  template: `
    <div class="grid" style="gap:16px">
      <div class="grid stats">
        <div class="stat-card">
          <div class="val">{{ store.status ? store.status.version : '—' }}</div>
          <div class="lbl">Server version</div>
        </div>
        <div class="stat-card">
          <div class="val small">{{ store.status ? store.status.patchFolder : '—' }}</div>
          <div class="lbl">Patch folder</div>
        </div>
        <div class="stat-card">
          <div class="val">{{ store.players.length }}</div>
          <div class="lbl">Player saves</div>
        </div>
        <div class="stat-card">
          <div class="val">{{ sys ? sys.uptimeStr : '—' }}</div>
          <div class="lbl">Game server uptime</div>
        </div>
        <div class="stat-card">
          <div class="val">{{ store.status ? store.status.trackerClients : 0 }}</div>
          <div class="lbl">Tracker clients</div>
        </div>
      </div>

      <div class="grid cols-2">
        <div class="panel">
          <div class="panel-head"><h2>Environment</h2></div>
          <div class="panel-body">
            <table v-if="store.status">
              <tr><td>Auth mode</td><td class="num">
                <span class="tag" :class="store.status.authMode === 'token' ? 'ok' : 'warn'">
                  {{ store.status.authMode }}</span></td></tr>
              <tr><td>Multiplayer</td><td class="num">
                <span class="tag" :class="store.status.multiplayer ? 'accent' : ''">
                  {{ store.status.multiplayer ? 'on' : 'off' }}</span></td></tr>
              <tr><td>Active save</td><td class="num">{{ store.status.activePlayer || '—' }}</td></tr>
              <tr><td>Game server</td><td class="num">
                <span class="tag" :class="sys ? 'ok' : 'warn'">{{ sys ? 'reachable' : 'unreachable' }}</span>
              </td></tr>
              <tr><td>ADB serial</td><td class="num">{{ store.status.adbSerial }}</td></tr>
            </table>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2>Loaded master data</h2>
            <span class="sub">from xml_live/ - same source the client gets</span>
          </div>
          <div class="panel-body">
            <div class="grid stats" v-if="store.status">
              <div class="stat-card"><div class="val">{{ fmt.num(store.status.gamedata.heroes) }}</div><div class="lbl">Heroes</div></div>
              <div class="stat-card"><div class="val">{{ fmt.num(store.status.gamedata.items) }}</div><div class="lbl">Items</div></div>
              <div class="stat-card"><div class="val">{{ fmt.num(store.status.gamedata.skills) }}</div><div class="lbl">Skills</div></div>
              <div class="stat-card"><div class="val">{{ fmt.num(store.status.gamedata.buffs) }}</div><div class="lbl">Buffs</div></div>
              <div class="stat-card"><div class="val">{{ fmt.num(store.status.gamedata.strings) }}</div><div class="lbl">Strings</div></div>
            </div>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head">
          <h2>Across all saves</h2>
          <button class="btn ghost sm" @click="store.refresh(); load()">Refresh</button>
        </div>
        <div class="panel-body">
          <div class="grid stats">
            <div class="stat-card"><div class="val">{{ fmt.num(totals.cards) }}</div><div class="lbl">Heroes owned</div></div>
            <div class="stat-card"><div class="val">{{ fmt.num(totals.accessories) }}</div><div class="lbl">Accessories</div></div>
            <div class="stat-card"><div class="val">{{ fmt.num(totals.items) }}</div><div class="lbl">Item stacks</div></div>
            <div class="stat-card"><div class="val">{{ fmt.num(totals.posts) }}</div><div class="lbl">Mail in inboxes</div></div>
          </div>
        </div>
      </div>
    </div>
  `,
};
