import useSWR from 'swr';

// Central fetcher for SWR
export const fetcher = async (url: string, init?: RequestInit) => {
  const token = typeof window !== 'undefined' ? localStorage.getItem('admin_token') : null;
  const headers = new Headers(init?.headers);
  headers.set('Content-Type', 'application/json');
  if (token) {
    headers.set('x-admin-token', token);
  }

  const res = await fetch(url, { ...init, headers });
  
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    if (res.status === 401) {
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new Event('kgc:unauthorized'));
      }
    }
    throw new Error(err.error || `HTTP error ${res.status}`);
  }
  
  return res.json();
};

export const runMutation = async (url: string, init?: RequestInit, successMessage?: string) => {
  try {
    const data = await fetcher(url, init);
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('kgc:toast', { detail: { message: successMessage || 'Success', type: 'success' } }));
    }
    return data;
  } catch (error: any) {
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('kgc:toast', { detail: { message: error.message, type: 'error' } }));
    }
    throw error;
  }
};

// SWR Hooks
export function useStatus() {
  return useSWR('/api/status', fetcher, { refreshInterval: 15000 });
}

export function useCatalog() {
  return useSWR('/api/catalog', fetcher, { revalidateOnFocus: false });
}

export function usePlayers() {
  return useSWR('/api/players', fetcher);
}

export function usePlayer(pid?: string) {
  return useSWR(pid ? `/api/player/${encodeURIComponent(pid)}` : null, fetcher);
}

export function useWhoAmI() {
  return useSWR('/api/auth/whoami', fetcher, { shouldRetryOnError: false });
}
