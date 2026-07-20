import { ref, watch, computed } from 'vue';
import { api } from '../api.js';
import { store } from '../store.js';
import { PlayerBar } from './_shared.js';

export default {
  components: { PlayerBar },
  setup() {
    const accs = ref([]);
    const scoreRange = ref([]);
    const grades = ref([]);
    const synergyFilter = ref('');
    const groupBySet = ref(true);

    const load = async () => {
      if (!store.selectedId) return;
      const d = await api('/player/' + encodeURIComponent(store.selectedId) + '/accessories').catch(() => null);
      if (d) { accs.value = d.accessories; scoreRange.value = d.scoreRange; grades.value = d.grades; }
    };
    watch(() => store.selectedId, load, { immediate: true });

    const sets = computed(() => {
      const seen = new Map();
      accs.value.forEach((a) => seen.set(a.synergy, a.synergyName));
      return [...seen.entries()].sort((a, b) => a[0] - b[0]);
    });

    const filtered = computed(() => (synergyFilter.value === ''
      ? accs.value
      : accs.value.filter((a) => String(a.synergy) === String(synergyFilter.value))));

    const groups = computed(() => {
      if (!groupBySet.value) return [{ name: 'All accessories', items: filtered.value }];
      const by = new Map();
      filtered.value.forEach((a) => {
        if (!by.has(a.synergyName)) by.set(a.synergyName, []);
        by.get(a.synergyName).push(a);
      });
      return [...by.entries()].map(([name, items]) => ({ name, items }));
    });

    // The client hides the badge entirely at/above the last threshold, and both
    // sub-stats draw from one upgrade pool - so a total above it means the item could
    // not have been rolled in game. Worth flagging rather than rendering as normal.
    const poolCeiling = computed(() => (scoreRange.value.length
      ? scoreRange.value[scoreRange.value.length - 1] + 4 : null));

    const suspicious = (a) => poolCeiling.value !== null && a.scoreTotal > poolCeiling.value;

    return { store, accs, filtered, groups, sets, synergyFilter, groupBySet, scoreRange, grades, suspicious };
  },
  template: `
    <div class="panel">
      <PlayerBar />
      <div class="toolbar" v-if="store.selectedId">
        <select class="select" style="width:auto;min-width:170px" v-model="synergyFilter">
          <option value="">All sets ({{ accs.length }})</option>
          <option v-for="[id, name] in sets" :key="id" :value="id">{{ name }}</option>
        </select>
        <label class="pill" style="cursor:pointer">
          <input type="checkbox" v-model="groupBySet" style="margin:0"> group by set
        </label>
        <span style="flex:1"></span>
        <span class="pill">grade scale: {{ scoreRange.join(' / ') }}</span>
      </div>

      <div class="panel-body" v-if="store.selectedId">
        <div v-for="g in groups" :key="g.name" style="margin-bottom:20px">
          <div class="sub-head">{{ g.name }} <span class="counter">· {{ g.items.length }} pieces</span></div>
          <div class="grid cols-3">
            <div v-for="a in g.items" :key="a.id" class="stat-card">
              <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
                <strong>{{ a.typeName }}</strong>
                <span class="tag" :class="a.rarity === 3 ? 'accent' : ''">{{ a.rarityName }} · Lv{{ a.level }}</span>
              </div>
              <div style="margin-top:8px;font-size:12px;color:var(--text-dim)">
                Main: <strong style="color:var(--text)">{{ a.mainStatLabel }}</strong>
              </div>
              <div style="margin-top:7px;display:flex;flex-direction:column;gap:4px">
                <div v-for="(s, i) in a.subStats" :key="i"
                     style="display:flex;align-items:center;gap:7px;font-size:12px">
                  <span class="grade" :class="s.grade ? 'grade-' + s.grade : 'grade-none'">
                    {{ s.grade || '—' }}
                  </span>
                  <span style="flex:1">{{ s.label }}</span>
                  <span style="font-family:var(--mono);color:var(--text-faint)">{{ s.score }}</span>
                </div>
              </div>
              <div style="margin-top:8px;font-size:11px;color:var(--text-faint)">
                score total {{ a.scoreTotal }}
                <span v-if="suspicious(a)" class="tag warn" style="margin-left:6px"
                      title="Above what one upgrade pool can produce - not obtainable in game">
                  over pool
                </span>
                <span v-if="a.unitName" class="tag" style="margin-left:6px">on {{ a.unitName }}</span>
              </div>
            </div>
          </div>
        </div>
        <div v-if="!accs.length" class="empty"><span class="icon">💍</span>No accessories in this save.</div>
      </div>
    </div>
  `,
};
