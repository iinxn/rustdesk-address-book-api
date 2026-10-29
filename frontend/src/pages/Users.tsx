import { useEffect, useState } from 'react';
import { api, sessionUser, setDisplayName } from '../api';
import { Confirm, Layout, LoadError, Loading, btn, btnGhost, input } from '../components';
import { useTheme } from '../hooks';
import { useI18n } from '../i18n';
import { useNotify } from '../notifications';
import type { PanelUser } from '../types';

export default function Users() {
  const { dark, toggle } = useTheme();
  const { t } = useI18n();
  const { notify } = useNotify();
  const [rows, setRows] = useState<PanelUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [display, setDisplay] = useState('');
  const [pw, setPw] = useState('');
  const [isAdmin, setIsAdmin] = useState(false);
  const [editing, setEditing] = useState<PanelUser | null>(null);
  const [editName, setEditName] = useState('');
  const [editDisplay, setEditDisplay] = useState('');
  const [editAdmin, setEditAdmin] = useState(false);
  const [editPw, setEditPw] = useState('');
  const [confirm, setConfirm] = useState<PanelUser | null>(null);

  const load = () => {
    setLoading(true); setFailed(false);
    api.users().then(setRows).catch(() => setFailed(true)).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const openCreate = () => { setName(''); setDisplay(''); setPw(''); setIsAdmin(false); setCreating(true); };
  const doCreate = async () => {
    if (!name.trim() || !pw) { notify(false, t('users.required')); return; }
    try {
      await api.createUser({
        username: name.trim(),
        password: pw,
        is_admin: isAdmin,
        display_name: display.trim(),
      });
      setCreating(false); notify(true, t('users.created')); load();
    } catch (e) { notify(false, String((e as Error).message)); }
  };
  const openEdit = (u: PanelUser) => {
    setEditing(u);
    setEditName(u.username);
    setEditDisplay(u.display_name || '');
    setEditAdmin(u.is_admin);
    setEditPw('');
  };
  const doEdit = async () => {
    if (!editing || !editName.trim()) { notify(false, t('users.usernameRequired')); return; }
    try {
      await api.updateUser(editing.id, {
        username: editName.trim(),
        display_name: editDisplay.trim(),
        is_admin: editAdmin,
        // An empty field keeps the current password; the backend only
        // re-hashes and revokes sessions when `password` is truthy.
        ...(editPw ? { password: editPw } : {}),
      });
      // Keep the header in sync when an admin edits their own account.
      if (editing.username === sessionUser()?.username) setDisplayName(editDisplay.trim());
      setEditing(null); notify(true, t('users.updated')); load();
    } catch (e) { notify(false, String((e as Error).message)); }
  };
  const flip = async (u: PanelUser, patch: object, msg: string) => {
    try {
      await api.updateUser(u.id, patch);
      notify(true, msg); load();
    } catch (e) { notify(false, String((e as Error).message)); }
  };
  const doDelete = async () => {
    if (!confirm) return;
    try {
      await api.deleteUser(confirm.id);
      setConfirm(null); notify(true, t('users.deleted')); load();
    } catch (e) { notify(false, String((e as Error).message)); }
  };

  return (
    <Layout dark={dark} onTheme={toggle}>
      <div className="mb-3 flex items-center justify-between">
        <h1 className="text-xl font-bold">{t('users.title')}</h1>
        <button onClick={openCreate} className={btn}>{t('users.add')}</button>
      </div>
      {loading ? <Loading text={t('users.loading')} /> : failed ? <LoadError onRetry={load} /> : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-slate-200 text-left text-slate-600 dark:border-slate-800 dark:text-slate-300">
              <th className="px-3 py-2">{t('users.username')}</th><th className="px-3 py-2">{t('users.displayName')}</th><th className="px-3 py-2">{t('users.role')}</th><th className="px-3 py-2">{t('users.status')}</th><th className="px-3 py-2"></th>
            </tr></thead>
            <tbody>
              {rows.map((u) => (
                <tr key={u.id} className="border-b border-slate-100 last:border-0 dark:border-slate-800">
                  <td className="px-3 py-2">{u.username}</td>
                  <td className="px-3 py-2">
                    {u.display_name || <span className="text-slate-500 dark:text-slate-400">—</span>}
                  </td>
                  <td className="px-3 py-2">
                    <button onClick={() => flip(u, { is_admin: !u.is_admin }, t('users.roleUpdated'))}
                      className="rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-800 dark:bg-slate-700 dark:text-slate-200" title={t('users.toggleRole')}>
                      {u.is_admin ? t('users.admin') : t('users.user')}
                    </button>
                  </td>
                  <td className="px-3 py-2">
                    <button onClick={() => flip(u, { is_disabled: !u.is_disabled }, u.is_disabled ? t('users.enabled') : t('users.disabledMsg'))}
                      className={`rounded-full px-2 py-0.5 text-xs ${u.is_disabled ? 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300' : 'bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300'}`} title={t('users.toggleStatus')}>
                      {u.is_disabled ? t('users.disabled') : t('users.active')}
                    </button>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button onClick={() => openEdit(u)} className={`${btnGhost} mr-1`}>{t('common.edit')}</button>
                    <button onClick={() => setConfirm(u)} className="rounded-md bg-red-600 px-2 py-1 text-white hover:bg-red-700">{t('common.delete')}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {creating && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setCreating(false)}>
          <div className="w-80 rounded-lg bg-white p-4 text-slate-900 dark:bg-slate-900 dark:text-slate-100" onClick={(e) => e.stopPropagation()}>
            <h2 className="mb-3 font-bold">{t('users.addTitle')}</h2>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('users.usernamePlaceholder')} className={`${input} mb-2`} />
            <input value={display} onChange={(e) => setDisplay(e.target.value)} placeholder={t('users.displayPlaceholder')} maxLength={128} className={`${input} mb-2`} />
            <input value={pw} onChange={(e) => setPw(e.target.value)} type="password" placeholder={t('users.passwordPlaceholder')} className={`${input} mb-2`} />
            <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} /> {t('users.admin')}</label>
            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setCreating(false)} className={btnGhost}>{t('common.cancel')}</button>
              <button onClick={doCreate} className={btn}>{t('common.create')}</button>
            </div>
          </div>
        </div>
      )}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setEditing(null)}>
          <div className="w-80 rounded-lg bg-white p-4 text-slate-900 dark:bg-slate-900 dark:text-slate-100" onClick={(e) => e.stopPropagation()}>
            <h2 className="mb-3 font-bold">{t('users.editTitle')}</h2>
            <input value={editName} onChange={(e) => setEditName(e.target.value)} placeholder={t('users.usernamePlaceholder')} className={`${input} mb-2`} />
            <input value={editDisplay} onChange={(e) => setEditDisplay(e.target.value)} placeholder={t('users.displayPlaceholder')} maxLength={128} className={`${input} mb-2`} />
            <input value={editPw} onChange={(e) => setEditPw(e.target.value)} type="password" autoComplete="new-password" placeholder={t('users.newPasswordPlaceholder')} className={`${input} mb-2`} />
            <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={editAdmin} onChange={(e) => setEditAdmin(e.target.checked)} /> {t('users.admin')}</label>
            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setEditing(null)} className={btnGhost}>{t('common.cancel')}</button>
              <button onClick={doEdit} className={btn}>{t('common.save')}</button>
            </div>
          </div>
        </div>
      )}
      {confirm && <Confirm text={t('users.deleteConfirm', { name: confirm.username })} onYes={doDelete} onNo={() => setConfirm(null)} />}
    </Layout>
  );
}
