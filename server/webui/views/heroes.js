import { ref, watch, computed } from 'vue';
import { api, run } from '../api.js';
import { store } from '../store.js';
import { PlayerBar } from './_shared.js';

const ROLE_TAG = {
  Toughness: 'accent', Brave: 'warn', Element: 'ok', Mystic: 'accent', Swift: 'warn', Shadow: 'accent',
};

export default {
  components: { PlayerBar },
  setup() {
    const owned = ref([]);
    const missing = ref([]);
    const q = ref('');
    const showMissing = ref(false);
    const grantLevel = ref(30);

    const load = async () => {
      if (!store.selectedId) return;
      const d = await api('/player/' + encodeURIComponent(store.selectedId) + '/heroes').catch(() => null);
      if (d) { owned.value = d.owned; missing.value = d.missing; }
    };
    watch(() => store.selectedId, load, { immediate: true });

    const filtered = computed(() => {
      const needle = q.value.trim().toLowerCase();
      const list = showMissing.value ? missing.value : owned.value;
      if (!needle) return list;
      return list.filter((h) => h.name.toLowerCase().includes(needle) || String(h.unitId).includes(needle));
    });

    const saveHero = async (h) => {
      const ok = await run(api(`/player/${encodeURIComponent(store.selectedId)}/heroes/${h.unitId}`,
        { method: 'PATCH', body: { level: +h.level, soul: +h.soul, potentialTier: +h.potentialTier } }),
        `${h.name} saved`);
      if (ok) store.loadPlayers();
    };

    const grant = async (h) => {
      const ok = await run(api(`/player/${encodeURIComponent(store.selectedId)}/heroes/${h.unitId}`,
        { method: 'POST' }), `${h.name} granted`);
      if (ok) { await load(); store.loadPlayers(); }
    };

    const remove = async (h) => {
      if (!confirm(`Remove ${h.name} from this save?`)) return;
      const ok = await run(api(`/player/${encodeURIComponent(store.selectedId)}/heroes/${h.unitId}`,
        { method: 'DELETE' }), `${h.name} removed`);
      if (ok) { await load(); store.loadPlayers(); }
    };

    const grantAll = async () => {
      const ok = await run(api(`/player/${encodeURIComponent(store.selectedId)}/heroes-grant-all`,
        { method: 'POST', body: { level: +grantLevel.value } }), 'All heroes granted');
      if (ok) { await load(); store.loadPlayers(); }
    };

    return { store, owned, missing, q, showMissing, filtered, grantLevel,
             saveHero, grant, remove, grantAll, ROLE_TAG };
  },
  template: `
    <div class="panel">
      <PlayerBar />
      <div class="toolbar" v-if="store.selectedId">
        <input class="input grow" v-model="q" placeholder="Search hero by name or id...">
        <button class="btn sm" :class="{ primary: !showMissing }" @click="showMissing = false">
          Owned ({{ owned.length }})
        </button>
        <button class="btn sm" :class="{ primary: showMissing }" @click="showMissing = true">
          Missing ({{ missing.length }})
        </button>
        <span style="flex:1"></span>
        <input class="input" style="width:74px" type="number" v-model="grantLevel" title="Level for granted heroes">
        <button class="btn" @click="grantAll">Grant all</button>
      </div>

      <div class="table-wrap" v-if="store.selectedId">
        <table>
          <thead>
            <tr>
              <th>Hero</th><th>Role</th><th class="num">ID</th>
              <template v-if="!showMissing">
                <th class="num">Level</th><th class="num">Soul</th><th class="num">Potential</th><th class="num">Skins</th>
              </template>
              <th class="num">Action</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="h in filtered" :key="h.unitId">
              <td><strong>{{ h.name }}</strong></td>
              <td><span class="tag" :class="ROLE_TAG[h.role] || ''">{{ h.role }}</span></td>
              <td class="num">{{ h.unitId }}</td>
              <template v-if="!showMissing">
                <td class="num"><input class="input cell-input" type="number" v-model="h.level"></td>
                <td class="num"><input class="input cell-input" type="number" v-model="h.soul"></td>
                <td class="num"><input class="input cell-input" type="number" v-model="h.potentialTier"></td>
                <td class="num">{{ h.skins }}</td>
              </template>
              <td class="num">
                <template v-if="showMissing">
                  <button class="btn sm primary" @click="grant(h)">Grant</button>
                </template>
                <template v-else>
                  <button class="btn sm" @click="saveHero(h)">Save</button>
                  <button class="btn sm danger" style="margin-left:5px" @click="remove(h)">×</button>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="!filtered.length" class="empty">Nothing matches "{{ q }}".</div>
      </div>
    </div>
  `,
};
