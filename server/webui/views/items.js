import { ref, watch, computed } from 'vue';
import { api, run, fmt } from '../api.js';
import { store } from '../store.js';
import { PlayerBar } from './_shared.js';

export default {
  components: { PlayerBar },
  setup() {
    const items = ref([]);
    const q = ref('');
    const addId = ref('');
    const addCount = ref(1);

    const load = async () => {
      if (!store.selectedId) return;
      items.value = await api('/player/' + encodeURIComponent(store.selectedId) + '/inventory').catch(() => []);
    };
    watch(() => store.selectedId, load, { immediate: true });

    const filtered = computed(() => {
      const needle = q.value.trim().toLowerCase();
      if (!needle) return items.value;
      return items.value.filter((i) => i.name.toLowerCase().includes(needle) || String(i.id).includes(needle));
    });

    const setCount = async (id, count) => {
      const ok = await run(api('/player/' + encodeURIComponent(store.selectedId) + '/inventory',
        { method: 'POST', body: { id: +id, count: +count } }), 'Inventory updated');
      if (ok) { await load(); store.loadPlayers(); }
    };

    const add = async () => {
      // The picker shows "1234 — Name"; take the leading id so a typed name still works.
      const id = parseInt(addId.value, 10);
      if (!Number.isInteger(id)) return;
      await setCount(id, +addCount.value);
      addId.value = '';
    };

    const catalogItems = computed(() => (store.catalog && store.catalog.Item) || []);

    return { store, items, q, filtered, addId, addCount, add, setCount, catalogItems, fmt };
  },
  template: `
    <div class="panel">
      <PlayerBar />
      <div class="toolbar" v-if="store.selectedId">
        <input class="input grow" v-model="q" placeholder="Filter owned items...">
        <input class="input" style="min-width:230px" v-model="addId" list="item-catalog"
               placeholder="Add item (search name or id)" @keyup.enter="add">
        <datalist id="item-catalog">
          <option v-for="i in catalogItems" :key="i.id" :value="i.id + ' — ' + i.name"></option>
        </datalist>
        <input class="input" style="width:90px" type="number" min="1" v-model="addCount">
        <button class="btn primary" @click="add">Add</button>
      </div>

      <div class="table-wrap" v-if="store.selectedId">
        <table>
          <thead>
            <tr><th class="num">ID</th><th>Item</th><th>Type</th><th class="num">Count</th><th class="num"></th></tr>
          </thead>
          <tbody>
            <tr v-for="i in filtered" :key="i.id">
              <td class="num">{{ i.id }}</td>
              <td><strong>{{ i.name }}</strong></td>
              <td><span class="tag">{{ i.sub }}</span></td>
              <td class="num"><input class="input cell-input" type="number" v-model="i.count"></td>
              <td class="num">
                <button class="btn sm" @click="setCount(i.id, i.count)">Save</button>
                <button class="btn sm danger" style="margin-left:5px" @click="setCount(i.id, 0)"
                        title="Remove from inventory">×</button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="!filtered.length" class="empty">
          <span class="icon">📦</span>No items{{ q ? ' match that filter' : ' in this save' }}.
        </div>
      </div>
    </div>
  `,
};
