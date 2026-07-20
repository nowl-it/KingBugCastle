// Root component: top bar, tab shell, toast stack.
import { createApp, ref, computed, onMounted } from 'vue';
import { toasts, auth, setToken } from './api.js';
import { store } from './store.js';

import Overview from './views/overview.js';
import Players from './views/players.js';
import Heroes from './views/heroes.js';
import Items from './views/items.js';
import Accessories from './views/accessories.js';
import Mail from './views/mail.js';
import Tracker from './views/tracker.js';
import ServerView from './views/server.js';

const TABS = [
  { id: 'overview', label: 'Overview', comp: Overview },
  { id: 'players', label: 'Players', comp: Players },
  { id: 'heroes', label: 'Heroes', comp: Heroes },
  { id: 'items', label: 'Items', comp: Items },
  { id: 'accessories', label: 'Accessories', comp: Accessories },
  { id: 'mail', label: 'Mail', comp: Mail },
  { id: 'tracker', label: 'Battle Tracker', comp: Tracker },
  { id: 'server', label: 'Server', comp: ServerView },
];

const App = {
  components: Object.fromEntries(TABS.map((t) => [t.id, t.comp])),
  setup() {
    // The tab lives in the URL hash so a reload (and a bookmark) keeps its place.
    const tab = ref((location.hash || '#overview').slice(1));
    if (!TABS.some((t) => t.id === tab.value)) tab.value = 'overview';
    window.addEventListener('hashchange', () => {
      const next = location.hash.slice(1);
      if (TABS.some((t) => t.id === next)) tab.value = next;
    });

    const go = (id) => { tab.value = id; location.hash = '#' + id; };
    const current = computed(() => TABS.find((t) => t.id === tab.value).comp);

    const needsToken = ref(false);
    const tokenInput = ref('');

    onMounted(async () => {
      await store.refresh();
      // A 403 with no token configured locally means the server wants one.
      needsToken.value = store.status === null && !auth.token;
      store.loadCatalog();
      setInterval(() => store.loadStatus(), 15000);
    });

    const applyToken = async () => {
      setToken(tokenInput.value.trim());
      await store.refresh();
      needsToken.value = store.status === null;
    };

    return { TABS, tab, go, current, store, toasts, needsToken, tokenInput, applyToken, auth };
  },
  template: `
    <div class="app">
      <header class="topbar">
        <div class="brand">
          <div class="logo">KGC</div>
          <div>
            <h1>Dashboard</h1>
            <div class="sub">Private server control</div>
          </div>
        </div>
        <nav class="tabs">
          <button v-for="t in TABS" :key="t.id"
                  :class="{ active: tab === t.id }" @click="go(t.id)">{{ t.label }}</button>
        </nav>
        <div class="topbar-right">
          <span class="pill" v-if="store.status">
            v{{ store.status.version }} · {{ store.status.patchFolder }}
          </span>
          <span class="pill" v-if="store.status">
            {{ store.status.players }} player<span v-if="store.status.players !== 1">s</span>
          </span>
          <span class="pill warn" v-if="store.status && store.status.multiplayer">multiplayer</span>
          <span class="pill" :class="store.status ? 'ok' : 'err'">
            <span class="dot"></span>{{ store.status ? 'online' : 'offline' }}
          </span>
        </div>
      </header>

      <main class="content">
        <div v-if="needsToken" class="panel" style="max-width:460px;margin:60px auto">
          <div class="panel-head"><h2>Admin token required</h2></div>
          <div class="panel-body">
            <p class="hint" style="margin-top:0">
              This server runs with <code>KGC_ADMIN_TOKEN</code> set. Paste it to continue -
              it is kept in this tab only.
            </p>
            <div class="field">
              <label>Token</label>
              <input class="input mono" type="password" v-model="tokenInput"
                     @keyup.enter="applyToken" placeholder="KGC_ADMIN_TOKEN">
            </div>
            <div class="btn-row"><button class="btn primary" @click="applyToken">Unlock</button></div>
          </div>
        </div>
        <component v-else :is="current" />
      </main>

      <div class="toast-stack">
        <div v-for="t in toasts.items" :key="t.id" class="toast" :class="t.kind">{{ t.message }}</div>
      </div>
    </div>
  `,
};

export default App;

// Guarded so the module can be imported (by the template checker) without a DOM.
const mountPoint = document.querySelector('#app');
if (mountPoint) createApp(App).mount(mountPoint);
