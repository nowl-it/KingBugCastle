'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';

export default function LoginPage() {
  const [tab, setTab] = useState<'login' | 'register'>('login');
  const [uid, setUid] = useState('');
  const [pass, setPass] = useState('');
  const [name, setName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { login } = useAuth();
  const router = useRouter();

  const guestLogin = () => {
    const guestUid = 'guest-' + Math.random().toString(36).slice(2, 8);
    login({ uid: guestUid, name: 'Guest', token: guestUid, isGuest: true });
    router.replace('/dashboard');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (!uid.trim()) { setError('Enter a user ID'); return; }
    setLoading(true);
    try {
      if (tab === 'register') {
        await fetch('/api/auth/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ uid, password: pass, name: name || uid }),
        });
      }
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uid, password: pass }),
      });
      const d = await res.json();
      if (!d.ok) { setError(d.error || 'Login failed'); return; }
      login({ uid: d.uid, name: d.name, token: d.token, isGuest: false });
      router.replace('/dashboard');
    } catch (err: any) {
      setError(err.message || 'Connection error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0d1117] p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="w-12 h-12 mx-auto mb-3 rounded-xl flex items-center justify-center text-lg font-extrabold text-white"
               style={{background:'linear-gradient(135deg,#58a6ff,#bc8cff)'}}>K</div>
          <h1 className="text-xl font-bold">KGC Admin</h1>
          <p className="text-sm text-[#8b949e] mt-1">Server management panel</p>
        </div>

        <div className="card">
          <div className="flex border-b border-[#30363d]">
            <button onClick={() => setTab('login')}
              className={`flex-1 py-2.5 text-sm font-medium text-center transition-colors
                ${tab === 'login' ? 'text-[#58a6ff] border-b-2 border-[#58a6ff]' : 'text-[#8b949e] hover:text-[#e6edf3]'}`}>
              Sign In
            </button>
            <button onClick={() => setTab('register')}
              className={`flex-1 py-2.5 text-sm font-medium text-center transition-colors
                ${tab === 'register' ? 'text-[#58a6ff] border-b-2 border-[#58a6ff]' : 'text-[#8b949e] hover:text-[#e6edf3]'}`}>
              Register
            </button>
          </div>

          <form onSubmit={handleSubmit} className="p-5 space-y-4">
            <div>
              <label className="label">User ID</label>
              <input value={uid} onChange={e => setUid(e.target.value)} className="input" placeholder="Enter user ID..." autoFocus />
            </div>
            {tab === 'register' && (
              <div>
                <label className="label">Display Name</label>
                <input value={name} onChange={e => setName(e.target.value)} className="input" placeholder="Optional" />
              </div>
            )}
            <div>
              <label className="label">Password</label>
              <input type="password" value={pass} onChange={e => setPass(e.target.value)} className="input" placeholder="Password" />
            </div>

            {error && <p className="text-[#f85149] text-xs">{error}</p>}

            <button type="submit" disabled={loading}
              className="btn btn-primary w-full justify-center !py-2">
              {loading ? 'Please wait…' : tab === 'login' ? 'Sign In' : 'Create Account'}
            </button>
          </form>

          <div className="px-5 pb-5">
            <div className="relative mb-4">
              <div className="absolute inset-0 flex items-center"><div className="w-full border-t border-[#30363d]" /></div>
              <div className="relative flex justify-center"><span className="bg-[#161b22] px-2 text-xs text-[#8b949e]">or</span></div>
            </div>
            <button onClick={guestLogin}
              className="w-full py-2.5 text-sm font-medium rounded-md border border-dashed border-[#30363d] text-[#8b949e] hover:text-[#e6edf3] hover:border-[#8b949e] transition-all">
              Continue as Guest
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
