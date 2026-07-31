// Root component: top bar, tab shell, auth gate, toast stack.
import { createApp, ref, computed, onMounted } from "vue";
import { toasts, auth, setToken, api, run, toast } from "./api.js";
import { store } from "./store.js";

import Overview from "./views/overview.js";
import Players from "./views/players.js";
import Heroes from "./views/heroes.js";
import Items from "./views/items.js";
import Accessories from "./views/accessories.js";
import Mail from "./views/mail.js";
import Tracker from "./views/tracker.js";
import ServerView from "./views/server.js";
import Account from "./views/account.js";

const TABS = [
	{ id: "overview", label: "Overview", comp: Overview },
	{ id: "players", label: "Players", comp: Players },
	{ id: "heroes", label: "Heroes", comp: Heroes },
	{ id: "items", label: "Items", comp: Items },
	{ id: "accessories", label: "Accessories", comp: Accessories },
	{ id: "mail", label: "Mail", comp: Mail },
	{ id: "tracker", label: "Battle Tracker", comp: Tracker },
	{ id: "server", label: "Server", comp: ServerView },
	{ id: "account", label: "Account", comp: Account },
];

const App = {
	components: Object.fromEntries(TABS.map((t) => [t.id, t.comp])),
	setup() {
		// The tab lives in the URL hash so a reload (and a bookmark) keeps its place.
		const tab = ref((location.hash || "#overview").slice(1));
		if (!TABS.some((t) => t.id === tab.value)) tab.value = "overview";
		window.addEventListener("hashchange", () => {
			const next = location.hash.slice(1);
			if (TABS.some((t) => t.id === next)) tab.value = next;
		});

		const go = (id) => {
			tab.value = id;
			location.hash = "#" + id;
		};
		const current = computed(() => TABS.find((t) => t.id === tab.value).comp);

		const who = ref(null);
		const tokenInput = ref("");
		const loginInput = ref({ username: "", password: "" });
		const busy = ref(false);

		const needsAuth = computed(() => !!who.value && !who.value.authenticated);

		// Which gate to draw. The old code fell back to the sign-in form whenever no
		// token was configured - including the case where no admin account exists yet,
		// which renders a form that cannot possibly succeed. That branch is `locked`.
		const gate = computed(() => {
			const w = who.value;
			if (!w) return "loading";
			if (w.hasAdmins) return "login";
			if (w.tokenMode) return "token";
			return "locked";          // loopback-only, and we are not on loopback
		});

		// Authenticated, but nothing actually guards the port. True only on the
		// loopback rung, which stops guarding the moment a tunnel is in front of it.
		const unprotected = computed(() =>
			!!who.value && who.value.authenticated && !who.value.hasAdmins && !who.value.tokenMode);

		const checkAuth = async () => {
			try {
				const res = await fetch("/api/auth/whoami", {
					headers: auth.token ? { "x-admin-token": auth.token } : {},
				});
				who.value = await res.json();
				return !!who.value.authenticated;
			} catch (e) {
				who.value = null;
				return false;
			}
		};

		const enter = async () => {
			await store.refresh();
			store.loadCatalog();
		};

		onMounted(async () => {
			if (await checkAuth()) {
				await enter();
				setInterval(() => store.loadStatus(), 15000);
			}
		});

		const applyToken = async () => {
			setToken(tokenInput.value.trim());
			if (await checkAuth()) await enter();
			else toast("That token was not accepted", "err");
		};

		const doLogin = async () => {
			busy.value = true;
			const ok = await run(api("/auth/login", { method: "POST", body: loginInput.value }));
			busy.value = false;
			if (ok && (await checkAuth())) await enter();
		};

		const signOut = async () => {
			await run(api("/auth/logout", { method: "POST" }), "Signed out");
			setToken("");
			location.reload();
		};

		return {
			TABS, tab, go, current, store, toasts, who, needsAuth, gate, unprotected,
			tokenInput, loginInput, busy,
			applyToken, doLogin, signOut, auth,
		};
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
        <nav class="tabs" v-if="!needsAuth">
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
          <button class="pill user" v-if="who && who.user" @click="signOut"
                  title="Sign out">{{ who.user }} · sign out</button>
        </div>
      </header>

      <main class="content">
        <div v-if="needsAuth" class="panel gate">
          <div v-if="gate === 'token'">
            <div class="panel-head"><h2>Admin token required</h2></div>
            <div class="panel-body">
              <p class="hint" style="margin-top:0">
                This server runs with <code>KGC_ADMIN_TOKEN</code> set. Paste it to continue -
                it is kept in this tab only.
              </p>
              <div class="field">
                <label>Token</label>
                <input class="input mono" type="password" v-model="tokenInput"
                       @keyup.enter="applyToken" placeholder="KGC_ADMIN_TOKEN"
                       autocomplete="off">
              </div>
              <div class="btn-row"><button class="btn primary" @click="applyToken">Unlock</button></div>
            </div>
          </div>

          <div v-else-if="gate === 'login'">
            <div class="panel-head"><h2>Sign in</h2></div>
            <div class="panel-body">
              <div class="field">
                <label>Username</label>
                <input class="input" type="text" v-model="loginInput.username"
                       autocomplete="username" @keyup.enter="doLogin">
              </div>
              <div class="field">
                <label>Password</label>
                <input class="input" type="password" v-model="loginInput.password"
                       autocomplete="current-password" @keyup.enter="doLogin">
              </div>
              <div class="btn-row">
                <button class="btn primary" :disabled="busy" @click="doLogin">Sign in</button>
              </div>
            </div>
          </div>

          <div v-else-if="gate === 'locked'">
            <div class="panel-head"><h2>Not reachable from here</h2></div>
            <div class="panel-body">
              <p class="hint" style="margin-top:0">
                No admin account exists and no <code>KGC_ADMIN_TOKEN</code> is set, so the
                dashboard only accepts requests from the machine it runs on. There is no
                password to enter yet.
              </p>
              <p class="hint">To get in from here, do one of these on the server:</p>
              <ul class="hint">
                <li>open the dashboard locally and create an admin in the Account tab,</li>
                <li>or run <code>python3 dashboard.py --create-admin &lt;user&gt;</code>,</li>
                <li>or start it with <code>KGC_ADMIN_TOKEN</code> set.</li>
              </ul>
            </div>
          </div>

          <div v-else class="panel-body"><div class="empty">Checking access...</div></div>
        </div>

        <template v-else>
          <div class="banner warn" v-if="unprotected">
            <span>
              Nothing guards this dashboard except the loopback check, which stops working
              behind a tunnel or reverse proxy.
            </span>
            <button class="btn sm" @click="go('account')">Create an admin account</button>
          </div>
          <component :is="current" />
        </template>
      </main>

      <div class="toast-stack">
        <div v-for="t in toasts.items" :key="t.id" class="toast" :class="t.kind">{{ t.message }}</div>
      </div>
    </div>
  `,
};

export default App;

// Guarded so the module can be imported (by the template checker) without a DOM.
const mountPoint = document.querySelector("#app");
if (mountPoint) createApp(App).mount(mountPoint);
