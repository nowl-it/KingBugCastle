import { useQuery, type UseQueryOptions } from '@tanstack/react-query';

export type JsonObject = Record<string, unknown>;
type QueryOptions = UseQueryOptions<unknown, Error, unknown, readonly unknown[]>;

// Central fetcher
// API response schemas are endpoint-specific. Until generated schemas are added,
// this is the single intentional dynamic boundary for raw JSON.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const fetcher = async (url: string, init?: RequestInit): Promise<any> => {
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
  } catch (error: unknown) {
    if (typeof window !== 'undefined') {
      const message = error instanceof Error ? error.message : 'Request failed';
      window.dispatchEvent(new CustomEvent('kgc:toast', { detail: { message, type: 'error' } }));
    }
    throw error;
  }
};

// React Query Hooks mapped to SWR signature
function useMappedQuery(options: QueryOptions) {
  const { data, error, isLoading, refetch } = useQuery(options);
  // API response schemas vary by endpoint and are not yet generated for this
  // dashboard. Keep the dynamic boundary here rather than propagating casts to
  // every screen; endpoint schemas can replace it incrementally.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return { data: data as any, error, isLoading, mutate: refetch };
}

export function useStatus() {
  return useMappedQuery({
    queryKey: ['/api/status'],
    queryFn: () => fetcher('/api/status'),
    refetchInterval: 2000
  });
}

export function useCatalog() {
  return useMappedQuery({
    queryKey: ['/api/catalog'],
    queryFn: () => fetcher('/api/catalog'),
    refetchOnWindowFocus: false
  });
}

export function useGrantRequests(status = "pending") {
  const query = status === "all" ? "" : `?status=${encodeURIComponent(status)}`;
  return useMappedQuery({
    queryKey: ['/api/requests', status],
    queryFn: () => fetcher(`/api/requests${query}`),
    refetchOnWindowFocus: false,
  });
}

export function useDonations() {
  return useMappedQuery({
    queryKey: ['/api/donations'],
    queryFn: () => fetcher('/api/donations'),
    refetchOnWindowFocus: false,
  });
}

export function usePlayers() {
  return useMappedQuery({
    queryKey: ['/api/players'],
    queryFn: () => fetcher('/api/players'),
    refetchInterval: 2000
  });
}

export function usePlayer(pid?: string) {
  return useMappedQuery({
    queryKey: pid ? ['/api/player', pid] : [],
    queryFn: () => pid ? fetcher(`/api/player/${encodeURIComponent(pid)}`) : Promise.resolve(null),
    enabled: !!pid,
    refetchInterval: 2000
  });
}

export function usePlayerRaw(pid?: string) {
  return useMappedQuery({
    queryKey: pid ? ['/api/player/raw', pid] : [],
    queryFn: () => pid ? fetcher(`/api/player/${encodeURIComponent(pid)}/raw`) : Promise.resolve(null),
    enabled: !!pid,
    refetchOnWindowFocus: false
  });
}

export function useHeroes(pid?: string) {
  return useMappedQuery({
    queryKey: pid ? ['/api/player/heroes', pid] : [],
    queryFn: () => pid ? fetcher(`/api/player/${encodeURIComponent(pid)}/heroes`) : Promise.resolve(null),
    enabled: !!pid,
    refetchInterval: 2000
  });
}

export function useInventory(pid?: string) {
  return useMappedQuery({
    queryKey: pid ? ['/api/player/inventory', pid] : [],
    queryFn: () => pid ? fetcher(`/api/player/${encodeURIComponent(pid)}/inventory`) : Promise.resolve(null),
    enabled: !!pid,
    refetchInterval: 2000
  });
}

export function useAccessories(pid?: string) {
  return useMappedQuery({
    queryKey: pid ? ['/api/player/accessories', pid] : [],
    queryFn: () => pid ? fetcher(`/api/player/${encodeURIComponent(pid)}/accessories`) : Promise.resolve(null),
    enabled: !!pid,
    refetchInterval: 2000
  });
}

export function useServerSection(section: string | null, refreshMs = 2000) {
  return useMappedQuery({
    queryKey: section ? ['/api/server', section] : [],
    queryFn: () => section ? fetcher(`/api/server/${section}`) : Promise.resolve(null),
    enabled: !!section,
    refetchInterval: refreshMs
  });
}

export function useAdmins() {
  return useMappedQuery({
    queryKey: ['/api/auth/admins'],
    queryFn: () => fetcher('/api/auth/admins')
  });
}

export function useWhoAmI() {
  return useMappedQuery({
    queryKey: ['/api/auth/whoami'],
    queryFn: () => fetcher('/api/auth/whoami'),
    retry: false
  });
}
