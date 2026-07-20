// Bits reused by more than one view.
import { store } from '../store.js';

// Every per-player view needs the same "which save am I editing" control, and they
// must all agree - one shared selection in the store, one shared widget on top.
export const PlayerBar = {
  setup() {
    return { store };
  },
  template: `
    <div class="toolbar" v-if="store.players.length">
      <span class="sub-head" style="margin:0">Player</span>
      <select class="select" style="width:auto;min-width:220px" v-model="store.selectedId">
        <option v-for="p in store.players" :key="p.id" :value="p.id">
          {{ p.name }} ({{ p.id }}){{ p.active ? ' · active' : '' }}
        </option>
      </select>
      <slot></slot>
    </div>
    <div v-else class="empty">No player saves yet - create one in the Players tab.</div>
  `,
};

export const Empty = {
  props: { icon: { default: '∅' }, text: { default: 'Nothing here' } },
  template: `<div class="empty"><span class="icon">{{ icon }}</span>{{ text }}</div>`,
};
