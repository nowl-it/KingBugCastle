'use client';

import { createContext, useContext, useState, useEffect, type ReactNode } from 'react';

interface AuthUser {
  uid: string;
  name: string;
  token: string;
  isGuest: boolean;
}

interface AuthContext {
  user: AuthUser | null;
  login: (u: AuthUser) => void;
  logout: () => void;
}

const Ctx = createContext<AuthContext>({ user: null, login: () => {}, logout: () => {} });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);

  useEffect(() => {
    const raw = localStorage.getItem('admin_auth');
    if (raw) try { setUser(JSON.parse(raw)); } catch { localStorage.removeItem('admin_auth'); }
  }, []);

  const login = (u: AuthUser) => { setUser(u); localStorage.setItem('admin_auth', JSON.stringify(u)); };
  const logout = () => { setUser(null); localStorage.removeItem('admin_auth'); };

  return <Ctx.Provider value={{ user, login, logout }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
