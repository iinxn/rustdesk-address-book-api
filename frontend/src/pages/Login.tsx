import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, setSession } from '../api';
import { Brand, LangSwitch, btn, input } from '../components';
import { useI18n } from '../i18n';

export default function Login() {
  const nav = useNavigate();
  const { t } = useI18n();
  const [u, setU] = useState('');
  const [p, setP] = useState('');
  const [err, setErr] = useState('');
  const go = async () => {
    setErr('');
    try {
      const r = await api.login(u, p);
      setSession(r.access_token, r.user.name, r.user.is_admin, r.user.display_name);
      nav('/');
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  return (
    <div className="relative flex min-h-screen items-center justify-center bg-slate-50 p-4 dark:bg-slate-950">
      <div className="absolute right-4 top-4">
        <LangSwitch />
      </div>
      <div className="w-80 rounded-lg border border-slate-200 bg-white p-6 text-slate-900 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-100">
        <div className="mb-4"><Brand /></div>
        <h1 className="mb-1 text-lg font-bold">{t('login.signIn')}</h1>
        <p className="mb-4 text-xs text-slate-500 dark:text-slate-400">
          {t('login.hint')}
        </p>
        {err && <p className="mb-2 text-sm text-red-600 dark:text-red-400">{err}</p>}
        <div className="space-y-2">
          <input
            value={u}
            onChange={(e) => setU(e.target.value)}
            placeholder={t('login.username')}
            aria-label={t('login.usernameLabel')}
            autoFocus
            autoComplete="username"
            className={input}
          />
          <input
            value={p}
            onChange={(e) => setP(e.target.value)}
            type="password"
            placeholder={t('login.password')}
            aria-label={t('login.passwordLabel')}
            autoComplete="current-password"
            className={input}
            onKeyDown={(e) => e.key === 'Enter' && go()}
          />
          <button onClick={go} className={`${btn} w-full`}>{t('login.submit')}</button>
        </div>
      </div>
    </div>
  );
}
