// Shared app state. A module singleton rather than provide/inject: every view needs
// the same player list and the same "who is selected", and threading that through
// props would be more plumbing than the app is worth.
import { reactive } from 'vue';
import { api, toast } from './api.js';

export const store = reactive({
  status: null,
  players: [],
  selectedId: null,
  catalog: null,
  grantable: [],
  loading: false,

  get selected() {
    return this.players.find((p) => p.id === this.selectedId) || null;
  },

  async loadStatus() {
    try {
      this.status = await api('/status');
    } catch (e) {
      this.status = null;
      toast('Status: ' + e.message, 'err');
    }
  },

  async loadPlayers() {
    this.loading = true;
    try {
      this.players = await api('/players');
      // Keep a selection alive across refreshes; fall back to the active save so the
      // editor is never staring at nothing on first load.
      if (!this.players.some((p) => p.id === this.selectedId)) {
        const active = this.players.find((p) => p.active);
        this.selectedId = (active || this.players[0] || {}).id || null;
      }
    } catch (e) {
      toast('Players: ' + e.message, 'err');
    } finally {
      this.loading = false;
    }
  },

  async loadCatalog() {
    if (this.catalog) return;
    try {
      const c = await api('/catalog');
      this.catalog = c.catalog;
      this.grantable = c.grantable || [];
    } catch (e) {
      toast('Catalog: ' + e.message, 'err');
    }
  },

  select(id) {
    this.selectedId = id;
  },

  async refresh() {
    await Promise.all([this.loadStatus(), this.loadPlayers()]);
  },
});
