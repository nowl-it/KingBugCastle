// Account tab: who you are, how the dashboard is guarded, and admin accounts.
//
// The endpoints behind this existed long before the UI did, which meant the only way
// to create a second operator - or to move off the weakest rung of the guard - was
// `python3 dashboard.py --create-admin`. Everything here is that CLI, in the browser.
import { ref, computed, onMounted } from 'vue';
import { api, run, toast } from '../api.js';

// The three ways in, worst to best. Shown so an operator can see at a glance which
// one is live - "loopback only" reads as safe until it is behind a tunnel, where
// every request arrives from loopback and the rung protects nothing.
const RUNGS = {
  loopback: {
    tag: 'warn',
    title: 'Loopback only',
    detail: 'Nothing is configured, so only requests from this machine are accepted. ' +
            'Behind a tunnel or reverse proxy every request looks like loopback, so this ' +
            'protects nothing. Create an admin account below before exposing the port.',
  },
  token: {
    tag: 'ok',
    title: 'Shared token',
    detail: 'KGC_ADMIN_TOKEN is set and required from everyone, including this machine. ' +
            'Good for scripts; an admin account is nicer for humans.',
  },
  account: {
    tag: 'ok',
    title: 'Admin accounts',
    detail: 'A username and password are required from everyone, including this machine. ' +
            'This is the strongest option and the one to use when the port is reachable ' +
            'from outside.',
  },
};

export default {
  setup() {
    const who = ref(null);
    const admins = ref([]);
    const form = ref({ username: '', password: '', confirm: '' });
    const busy = ref(false);

    const load = async () => {
      who.value = await api('/auth/whoami').catch(() => null);
      const r = await api('/auth/admins').catch(() => null);
      admins.value = (r && r.admins) || [];
    };
    onMounted(load);

    const rung = computed(() => {
      if (!who.value) return RUNGS.loopback;
      if (who.value.hasAdmins) return RUNGS.account;
      if (who.value.tokenMode) return RUNGS.token;
      return RUNGS.loopback;
    });

    // An existing username is an UPDATE, not an error - admin_create upserts. Saying
    // so up front stops "add" from silently resetting a colleague's password.
    const isUpdate = computed(() =>
      admins.value.some((a) => a.username === form.value.username.trim()));

    const problem = computed(() => {
      const f = form.value;
      if (!f.username.trim()) return 'Username is required';
      if (f.password.length < 8) return 'Password must be at least 8 characters';
      if (f.confirm !== f.password) return 'The two passwords do not match';
      return null;
    });
    // "Username is required" on a form nobody has typed in yet reads as an error the
    // page is already in, not as guidance.
    const touched = computed(() =>
      !!(form.value.username || form.value.password || form.value.confirm));

    // How this session got in. Signed in with an account -> the username; otherwise
    // authenticated at all means the shared token or the loopback rung let us in, and
    // "not signed in" alone would look like something is broken.
    const identity = computed(() => {
      if (!who.value) return '...';
      if (who.value.user) return who.value.user;
      if (!who.value.authenticated) return 'not signed in';
      return who.value.tokenMode ? 'shared token' : 'local machine';
    });

    const submit = async () => {
      if (problem.value) return toast(problem.value, 'err');
      busy.value = true;
      const ok = await run(
        api('/auth/admins', { method: 'POST',
                              body: { username: form.value.username.trim(),
                                      password: form.value.password } }),
        isUpdate.value ? 'Password updated' : 'Admin created');
      busy.value = false;
      if (ok) {
        form.value = { username: '', password: '', confirm: '' };
        await load();
      }
    };

    const remove = async (username) => {
      if (!confirm(`Delete admin "${username}"? Their sessions end immediately.`)) return;
      if (await run(api(`/auth/admins/${encodeURIComponent(username)}`, { method: 'DELETE' }),
                    'Admin deleted')) await load();
    };

    const signOut = async () => {
      await run(api('/auth/logout', { method: 'POST' }), 'Signed out');
      location.reload();
    };

    // last_login/created are epoch seconds from SQLite, not the ISO strings fmt.date
    // handles, so they need their own formatting.
    const stamp = (t) => (t ? new Date(t * 1000).toLocaleString() : 'never');

    return { who, admins, form, busy, rung, isUpdate, problem, touched, identity,
             submit, remove, signOut, stamp, load };
  },
  template: `
    <div class="grid" style="gap:16px">
      <div class="grid cols-2">
        <div class="panel">
          <div class="panel-head"><h2>Signed in</h2></div>
          <div class="panel-body">
            <table v-if="who">
              <tr><td>Signed in as</td><td class="num">{{ identity }}</td></tr>
              <tr><td>Guard</td><td class="num">
                <span class="tag" :class="rung.tag">{{ rung.title }}</span></td></tr>
              <tr><td>Accounts</td><td class="num">{{ admins.length }}</td></tr>
            </table>
            <p class="hint">{{ rung.detail }}</p>
            <div class="btn-row">
              <button class="btn" @click="load">Refresh</button>
              <button class="btn danger" v-if="who && who.user" @click="signOut">Sign out</button>
            </div>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2>{{ isUpdate ? 'Reset password' : 'Add admin' }}</h2>
            <span class="sub" v-if="isUpdate">that username already exists</span>
          </div>
          <div class="panel-body">
            <!-- capped: this panel sits in the wide column of a sidebar grid, and a
                 1000px-wide password box looks like a mistake -->
            <div style="max-width:420px">
              <div class="field">
                <label>Username</label>
                <input class="input" type="text" v-model="form.username" autocomplete="username">
              </div>
              <div class="field">
                <label>Password</label>
                <input class="input" type="password" v-model="form.password"
                       autocomplete="new-password" @keyup.enter="submit">
              </div>
              <div class="field">
                <label>Confirm password</label>
                <input class="input" type="password" v-model="form.confirm"
                       autocomplete="new-password" @keyup.enter="submit">
              </div>
              <p class="hint" v-if="touched && problem">{{ problem }}</p>
              <p class="hint" v-else-if="isUpdate">
                This replaces the existing password and ends that account's sessions.
              </p>
              <p class="hint" v-else>At least 8 characters.</p>
              <div class="btn-row">
                <button class="btn primary" :disabled="!!problem || busy" @click="submit">
                  {{ isUpdate ? 'Update password' : 'Create admin' }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head">
          <h2>Admin accounts</h2>
          <span class="sub">the last one cannot be deleted</span>
        </div>
        <div class="panel-body">
          <div class="table-wrap" v-if="admins.length">
            <table>
              <thead><tr><th>Username</th><th>Created</th><th>Last sign-in</th><th></th></tr></thead>
              <tbody>
                <tr v-for="a in admins" :key="a.username">
                  <td>{{ a.username }}<span class="tag" v-if="who && a.username === who.user"
                      style="margin-left:8px">you</span></td>
                  <td class="num">{{ stamp(a.created) }}</td>
                  <td class="num">{{ stamp(a.last_login) }}</td>
                  <td class="num">
                    <button class="btn ghost sm danger"
                            :disabled="admins.length <= 1 || (who && a.username === who.user)"
                            @click="remove(a.username)">Delete</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="empty">
            <span class="icon">!</span>
            No admin accounts. The dashboard is on its weakest rung - add one above.
          </div>
        </div>
      </div>
    </div>
  `,
};
