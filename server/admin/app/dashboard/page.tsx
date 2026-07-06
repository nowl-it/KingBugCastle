'use client';

import { useAuth } from '@/lib/auth';
import { useRouter } from 'next/navigation';

export default function DashboardPage() {
  const { user, logout } = useAuth();
  const router = useRouter();

  const doLogout = () => {
    logout();
    router.replace('/');
  };

  return (
    <div className="min-h-screen bg-[#0d1117] p-6">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center text-sm font-extrabold text-white"
                 style={{background:'linear-gradient(135deg,#58a6ff,#bc8cff)'}}>K</div>
            <div>
              <h1 className="text-lg font-bold">Dashboard</h1>
              <p className="text-sm text-[#8b949e]">
                {user?.isGuest ? 'Guest' : user?.name}
                <span className="text-[#484f58] ml-2 font-mono text-xs">{user?.uid}</span>
              </p>
            </div>
          </div>
          <button onClick={doLogout} className="btn btn-sm">Sign Out</button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
          <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-4">
            <div className="text-2xl font-bold">0</div>
            <div className="text-xs text-[#8b949e] uppercase tracking-wider mt-1">Players</div>
          </div>
          <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-4">
            <div className="text-2xl font-bold">—</div>
            <div className="text-xs text-[#8b949e] uppercase tracking-wider mt-1">Uptime</div>
          </div>
          <div className="bg-[#161b22] border border-[#30363d] rounded-lg p-4">
            <div className="text-2xl font-bold">—</div>
            <div className="text-xs text-[#8b949e] uppercase tracking-wider mt-1">Routes</div>
          </div>
        </div>

        <p className="text-center text-[#484f58] text-sm mt-12">Welcome to the admin panel. More features coming soon.</p>
      </div>
    </div>
  );
}
