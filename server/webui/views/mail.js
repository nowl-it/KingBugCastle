import { ref, watch, computed } from 'vue';
import { api, run, toast, fmt } from '../api.js';
import { store } from '../store.js';
import { PlayerBar } from './_shared.js';

const CURRENCY = ['', 'Gold', 'Cash', 'Heart'];

export default {
  components: { PlayerBar },
  setup() {
    const posts = ref([]);
    const broadcast = ref(false);
    const form = ref({ title: '', text: '', rewardType: '', rewardId: '', rewardAmount: 0, days: 30 });

    const load = async () => {
      if (!store.selectedId) return;
      const d = await api('/player/' + encodeURIComponent(store.selectedId)).catch(() => null);
      posts.value = d ? d.posts : [];
    };
    watch(() => store.selectedId, load, { immediate: true });

    const needsId = computed(() => !CURRENCY.includes(form.value.rewardType));
    const rewardList = computed(() => (store.catalog && store.catalog[form.value.rewardType]) || []);
    const isGrantable = computed(() => store.grantable.includes(form.value.rewardType));

    // The game's bundled emoji font stops around Unicode 6.0; newer codepoints deliver
    // intact but render blank, which looks like a server bug rather than a font gap.
    const newEmoji = computed(() => [...(form.value.title + form.value.text)]
      .some((c) => c.codePointAt(0) >= 0x1F900));

    const send = async () => {
      const title = form.value.title.trim().replace(/^(@raw:\s*)+/i, '');
      const text = form.value.text.trim().replace(/^(@raw:\s*)+/i, '');
      if (!title && !text) { toast('Need a title or a body', 'err'); return; }
      let rewardId = 0;
      if (needsId.value && form.value.rewardType) {
        rewardId = parseInt(form.value.rewardId, 10);
        if (!Number.isInteger(rewardId)) { toast('Pick a reward item', 'err'); return; }
      }
      const body = {
        title, text, rewardType: form.value.rewardType, rewardId,
        rewardAmount: +form.value.rewardAmount || 0, days: +form.value.days || 30,
      };
      const path = broadcast.value ? '/mail/broadcast'
        : `/player/${encodeURIComponent(store.selectedId)}/mail`;
      const ok = await run(api(path, { method: 'POST', body }),
        broadcast.value ? 'Sent to every save' : 'Mail sent');
      if (ok) {
        form.value.title = ''; form.value.text = '';
        await load(); store.loadPlayers();
      }
    };

    const del = async (id) => {
      const ok = await run(api(`/player/${encodeURIComponent(store.selectedId)}/mail/${id}`,
        { method: 'DELETE' }), 'Deleted');
      if (ok) { await load(); store.loadPlayers(); }
    };

    return { store, posts, form, broadcast, needsId, rewardList, isGrantable, newEmoji, send, del, fmt };
  },
  template: `
    <div class="grid cols-2">
      <div class="panel">
        <PlayerBar />
        <div class="panel-body" v-if="store.selectedId">
          <div class="sub-head">Compose</div>
          <div class="field-grid">
            <div class="field full">
              <label>Title <span class="counter">{{ form.title.length }}/80</span></label>
              <input class="input" maxlength="80" v-model="form.title"
                     placeholder="Plain text - do not type @raw:, the server adds it">
            </div>
            <div class="field full">
              <label>Body <span class="counter">{{ form.text.length }}/300</span></label>
              <textarea class="textarea" maxlength="300" v-model="form.text"></textarea>
            </div>
            <div class="field">
              <label>Reward type</label>
              <select class="select" v-model="form.rewardType">
                <option value="">None</option>
                <optgroup label="Currency"><option>Gold</option><option>Cash</option><option>Heart</option></optgroup>
                <optgroup label="Granted"><option>Item</option><option>Unit</option><option>UnitSoul</option><option>Card</option></optgroup>
                <optgroup label="Display only"><option>Artifact</option><option>Treasure</option><option>Accessory</option></optgroup>
              </select>
            </div>
            <div class="field">
              <label>Amount</label>
              <input class="input" type="number" min="0" v-model="form.rewardAmount">
            </div>
            <div class="field full" v-if="needsId && form.rewardType">
              <label>
                Reward item
                <span class="counter" :style="{ color: isGrantable ? '' : 'var(--warn)' }">
                  {{ rewardList.length }} available ·
                  {{ isGrantable ? 'granted to inventory' : 'display only - gift as an Item box' }}
                </span>
              </label>
              <input class="input" v-model="form.rewardId" list="reward-list" placeholder="Search by name or id...">
              <datalist id="reward-list">
                <option v-for="r in rewardList" :key="r.id"
                        :value="r.id + ' — ' + r.name + (r.sub ? ' [' + r.sub + ']' : '')"></option>
              </datalist>
            </div>
            <div class="field">
              <label>Expires (days)</label>
              <input class="input" type="number" min="1" max="365" v-model="form.days">
            </div>
          </div>

          <span class="hint" v-if="newEmoji" style="color:var(--warn)">
            Emoji beyond Unicode 6.0 render blank in game (old bundled font). Prefer 😀👍❤️🔥👑💰.
          </span>
          <span class="hint">
            Title and body are wrapped with <code>@raw:</code> server-side so they render
            verbatim instead of going through the Localizer.
          </span>

          <label class="pill" style="cursor:pointer;margin-top:12px">
            <input type="checkbox" v-model="broadcast" style="margin:0">
            send to every save ({{ store.players.length }})
          </label>

          <div class="btn-row">
            <button class="btn primary" @click="send">
              {{ broadcast ? 'Broadcast mail' : 'Send mail' }}
            </button>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head">
          <h2>Inbox</h2>
          <span class="sub">{{ posts.length }} message<span v-if="posts.length !== 1">s</span></span>
        </div>
        <div class="list">
          <div v-for="p in posts" :key="p.id" class="list-item" style="cursor:default">
            <div class="row1">
              <span class="nm">{{ p.title || '(no title)' }}</span>
              <button class="btn danger sm" @click="del(p.id)">Delete</button>
            </div>
            <div v-if="p.text" style="font-size:12.5px;color:var(--text-dim);margin-top:4px">{{ p.text }}</div>
            <div class="meta" v-if="p.rewardType">
              {{ p.rewardType }} ×{{ fmt.num(p.rewardAmount) }}
              <span v-if="p.rewardId"> · id {{ p.rewardId }}</span>
              · until {{ (p.untilAt || '').slice(0, 10) }}
            </div>
          </div>
          <div v-if="!posts.length" class="empty"><span class="icon">✉</span>Inbox is empty.</div>
        </div>
      </div>
    </div>
  `,
};
