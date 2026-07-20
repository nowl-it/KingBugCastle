// Shared API client + tiny global stores.
//
// Auth: when the server runs with KGC_ADMIN_TOKEN every request needs the token.
// It is taken from ?admin_token= once, kept in sessionStorage (not localStorage -
// it is a bearer credential and should die with the tab), and stripped from the
// visible URL so it does not end up in a screenshot or a shared link.
import { reactive } from 'vue';

const KEY = 'kgc_admin_token';

function initToken() {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get('admin_token');
  if (fromUrl) {
    sessionStorage.setItem(KEY, fromUrl);
    url.searchParams.delete('admin_token');
    history.replaceState({}, '', url);
  }
  return sessionStorage.getItem(KEY) || '';
}

export const auth = reactive({ token: initToken() });

export function setToken(t) {
  auth.token = t || '';
  if (t) sessionStorage.setItem(KEY, t); else sessionStorage.removeItem(KEY);
}

export const toasts = reactive({ items: [] });

let toastId = 0;
export function toast(message, kind = 'ok') {
  const id = ++toastId;
  toasts.items.push({ id, message, kind });
  setTimeout(() => {
    const i = toasts.items.findIndex((t) => t.id === id);
    if (i !== -1) toasts.items.splice(i, 1);
  }, kind === 'err' ? 6000 : 2800);
}

export async function api(path, { method = 'GET', body } = {}) {
  const headers = {};
  if (auth.token) headers['x-admin-token'] = auth.token;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await fetch('/api' + path, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      msg = j.detail || j.error || msg;
    } catch { /* non-JSON error body */ }
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

// Wrap a mutating call: toast on success, toast the reason on failure, never throw
// into a template. Returns true/false so callers can branch on it.
export async function run(promise, okMessage) {
  try {
    const r = await promise;
    if (okMessage) toast(okMessage, 'ok');
    return r ?? true;
  } catch (e) {
    toast(e.message, 'err');
    return false;
  }
}

export const fmt = {
  num: (n) => Number(n || 0).toLocaleString(),
  compact: (n) => {
    const v = Number(n || 0);
    if (Math.abs(v) >= 1e9) return (v / 1e9).toFixed(1) + 'B';
    if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(1) + 'M';
    if (Math.abs(v) >= 1e4) return (v / 1e3).toFixed(0) + 'K';
    return v.toLocaleString();
  },
  date: (s) => (s || '').replace('T', ' ').slice(0, 16),
};
