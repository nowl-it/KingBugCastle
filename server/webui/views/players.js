import { ref, watch, computed } from 'vue';
import { api, run, fmt, toast } from '../api.js';
import { store } from '../store.js';

const FIELDS = [
  ['name', 'Name', 'text'], ['castleName', 'Castle name', 'text'],
  ['gold', 'Gold', 'number'], ['cash', 'Cash', 'number'],
  ['paidCash', 'Paid cash', 'number'], ['heart', 'Heart', 'number'],
  ['level', 'Level', 'number'], ['exp', 'EXP', 'number'],
  ['bestClearedTheme', 'Best theme', 'number'], ['bestClearedStage', 'Best stage', 'number'],
  ['bestClearedHardTheme', 'Best hard theme', 'number'], ['bestClearedHardStage', 'Best hard stage', 'number'],
  ['buildingPoints', 'Building points', 'number'], ['playedCount', 'Games played', 'number'],
  ['winCount', 'Wins', 'number'],
];

export default {
  setup() {
    const form = ref({});
    const raw = ref('');
    const rawOpen = ref(false);
    const newName = ref('');
    const busy = ref(false);

    const loadForm = async () => {
      if (!store.selectedId) { form.value = {}; return; }
      const full = await api('/player/' + encodeURIComponent(store.selectedId) + '/raw').catch(() => null);
      if (!full) return;
      form.value = Object.fromEntries(FIELDS.map(([k]) => [k, full[k] ?? 0]));
      raw.value = JSON.stringify(full, null, 2);
    };
    watch(() => store.selectedId, loadForm, { immediate: true });

    const save = async () => {
      busy.value = true;
      const ok = await run(
        api('/player/' + encodeURIComponent(store.selectedId), { method: 'PATCH', body: form.value }),
        'Saved');
      busy.value = false;
      if (ok) store.loadPlayers();
    };

    const saveRaw = async () => {
      let parsed;
      try {
        parsed = JSON.parse(raw.value);
      } catch (e) {
        // Parse locally first - posting broken JSON would just come back as a 422 with
        // no line number, and this editor holds the whole save.
        toast('Invalid JSON: ' + e.message, 'err');
        return;
      }
      const ok = await run(
        api('/player/' + encodeURIComponent(store.selectedId) + '/raw', { method: 'PUT', body: parsed }),
        'Raw state written');
      if (ok) { await store.loadPlayers(); await loadForm(); }
    };

    const create = async () => {
      const ok = await run(api('/players', { method: 'POST', body: { name: newName.value || 'NewPlayer' } }),
        'Player created');
      if (ok) { newName.value = ''; await store.loadPlayers(); store.select(ok.summary.id); }
    };

    const clone = async () => {
      const ok = await run(api(`/players/${encodeURIComponent(store.selectedId)}/clone`, { method: 'POST', body: {} }),
        'Cloned');
      if (ok) { await store.loadPlayers(); store.select(ok.summary.id); }
    };

    const activate = async () => {
      const ok = await run(api(`/players/${encodeURIComponent(store.selectedId)}/activate`, { method: 'POST' }),
        'Now the active save');
      if (ok) store.refresh();
    };

    const del = async () => {
      const p = store.selected;
      if (!confirm(`Delete save "${p.name}" (${p.id})? This cannot be undone.`)) return;
      const ok = await run(api('/players/' + encodeURIComponent(p.id), { method: 'DELETE' }), 'Deleted');
      if (ok) { store.selectedId = null; store.refresh(); }
    };

    const selected = computed(() => store.selected);
    return { store, FIELDS, form, raw, rawOpen, newName, busy, selected,
             save, saveRaw, create, clone, activate, del, fmt };
  },
  template: `
    <div class="grid cols-2">
      <div class="panel">
        <div class="panel-head">
          <h2>Saves</h2>
          <button class="btn ghost sm" @click="store.loadPlayers()">Refresh</button>
        </div>
        <div class="toolbar">
          <input class="input grow" v-model="newName" placeholder="New player name"
                 @keyup.enter="create">
          <button class="btn primary sm" @click="create">Create</button>
        </div>
        <div class="list">
          <button v-for="p in store.players" :key="p.id" class="list-item"
                  :class="{ active: p.id === store.selectedId }" @click="store.select(p.id)">
            <div class="row1">
              <span class="nm">{{ p.name }}</span>
              <span class="tag ok" v-if="p.active">active</span>
            </div>
            <div class="id">{{ p.id }}</div>
            <div class="meta">
              Lv{{ p.level }} · {{ fmt.compact(p.gold) }}g · {{ fmt.compact(p.cash) }}c ·
              {{ p.counts.cards }} heroes · {{ p.counts.accessories }} acc · {{ p.counts.posts }} mail
            </div>
          </button>
          <div v-if="!store.players.length" class="empty">No saves found.</div>
        </div>
      </div>

      <div class="panel" v-if="selected">
        <div class="panel-head">
          <div>
            <h2>{{ selected.name }}</h2>
            <span class="sub">{{ selected.id }}</span>
          </div>
          <div style="display:flex;gap:6px">
            <button class="btn sm" @click="activate" :disabled="selected.active">Set active</button>
            <button class="btn sm" @click="clone">Clone</button>
            <button class="btn danger sm" @click="del">Delete</button>
          </div>
        </div>
        <div class="panel-body">
          <div class="sub-head">Identity, currencies &amp; progress</div>
          <div class="field-grid">
            <div class="field" v-for="[key, label, type] in FIELDS" :key="key">
              <label>{{ label }}</label>
              <input class="input" :type="type" v-model="form[key]">
            </div>
          </div>
          <div class="btn-row">
            <button class="btn primary" @click="save" :disabled="busy">Save changes</button>
          </div>

          <div class="divider"></div>

          <div class="sub-head" style="display:flex;justify-content:space-between;align-items:center">
            <span>Raw save JSON</span>
            <button class="btn ghost sm" @click="rawOpen = !rawOpen">{{ rawOpen ? 'Hide' : 'Show' }}</button>
          </div>
          <template v-if="rawOpen">
            <span class="hint warn">
              Full-state replace. Anything you drop here is gone from the save - the uid is
              pinned back to <code>{{ selected.id }}</code> on write, everything else is taken verbatim.
            </span>
            <textarea class="textarea input mono" style="min-height:340px;margin-top:8px" v-model="raw"></textarea>
            <div class="btn-row"><button class="btn danger" @click="saveRaw">Write raw state</button></div>
          </template>
        </div>
      </div>
      <div class="panel" v-else><div class="empty">Select a save to edit it.</div></div>
    </div>
  `,
};
