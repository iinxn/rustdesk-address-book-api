import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, setSession } from '../api';
import { btn, input } from '../components';

export default function Login() {
  const nav = useNavigate();
  const [u, setU] = useState('');
  const [p, setP] = useState('');
  const [err, setErr] = useState('');
  const go = async () => {
    setErr('');
    try {
      const r = await api.login(u, p);
      setSession(r.access_token, r.user.name, r.user.is_admin);
      nav('/');
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 dark:bg-slate-950">
      <div className="w-80 rounded-lg border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-100">
        <h1 className="mb-4 text-lg font-bold">AB Panel — Login</h1>
        {err && <p className="mb-2 text-sm text-red-600">{err}</p>}
        <div className="space-y-2">
          <input value={u} onChange={(e) => setU(e.target.value)} placeholder="username" className={input} />
          <input value={p} onChange={(e) => setP(e.target.value)} type="password" placeholder="password"
            className={input} onKeyDown={(e) => e.key === 'Enter' && go()} />
          <button onClick={go} className={`${btn} w-full`}>Login</button>
        </div>
      </div>
    </div>
  );
}
