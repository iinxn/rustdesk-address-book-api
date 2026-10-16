import { useEffect, useState } from 'react';
import { api } from '../api';
import { Confirm, Layout, LoadError, Loading, Toasts, btn, btnGhost, input } from '../components';
import { useTheme, useToasts } from '../hooks';
import type { PanelUser } from '../types';

export default function Users() {
  const { dark, toggle } = useTheme();
  const { items, push } = useToasts();
  const [rows, setRows] = useState<PanelUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [pw, setPw] = useState('');
  const [isAdmin, setIsAdmin] = useState(false);
  const [editing, setEditing] = useState<PanelUser | null>(null);
  const [editName, setEditName] = useState('');
  const [editAdmin, setEditAdmin] = useState(false);
  const [pwFor, setPwFor] = useState<PanelUser | null>(null);
  const [newPw, setNewPw] = useState('');
  const [confirm, setConfirm] = useState<PanelUser | null>(null);

  const load = () => {
    setLoading(true); setFailed(false);
    api.users().then(setRows).catch(() => setFailed(true)).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const openCreate = () => { setName(''); setPw(''); setIsAdmin(false); setCreating(true); };
  const doCreate = async () => {
    if (!name.trim() || !pw) { push(false, 'Username and password required'); return; }
    try {
      await api.createUser({ username: name.trim(), password: pw, is_admin: isAdmin });
      setCreating(false); push(true, 'User created'); load();
    } catch (e) { push(false, String((e as Error).message)); }
  };
  const openEdit = (u: PanelUser) => { setEditing(u); setEditName(u.username); setEditAdmin(u.is_admin); };
  const doEdit = async () => {
    if (!editing || !editName.trim()) { push(false, 'Username required'); return; }
    try {
      await api.updateUser(editing.id, { username: editName.trim(), is_admin: editAdmin });
      setEditing(null); push(true, 'User updated'); load();
    } catch (e) { push(false, String((e as Error).message)); }
  };
  const flip = async (u: PanelUser, patch: object, msg: string) => {
    try {
      await api.updateUser(u.id, patch);
      push(true, msg); load();
    } catch (e) { push(false, String((e as Error).message)); }
  };
  const doDelete = async () => {
    if (!confirm) return;
    try {
      await api.deleteUser(confirm.id);
      setConfirm(null); push(true, 'User deleted'); load();
    } catch (e) { push(false, String((e as Error).message)); }
  };

  return (
    <Layout dark={dark} onTheme={toggle}>
      <div className="mb-3 flex items-center justify-between">
        <h1 className="text-xl font-bold">Users</h1>
        <button onClick={openCreate} className={btn}>+ Add user</button>
      </div>
      {loading ? <Loading text="Loading users" /> : failed ? <LoadError onRetry={load} /> : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-slate-200 text-left text-slate-500 dark:border-slate-800">
              <th className="px-3 py-2">Username</th><th className="px-3 py-2">Role</th><th className="px-3 py-2">Status</th><th className="px-3 py-2"></th>
            </tr></thead>
            <tbody>
              {rows.map((u) => (
                <tr key={u.id} className="border-b border-slate-100 last:border-0 dark:border-slate-800">
                  <td className="px-3 py-2">{u.username}</td>
                  <td className="px-3 py-2">
                    <button onClick={() => flip(u, { is_admin: !u.is_admin }, 'Role updated')}
                      className="rounded-full bg-slate-200 px-2 py-0.5 text-xs dark:bg-slate-700" title="Toggle role">
                      {u.is_admin ? 'admin' : 'user'}
                    </button>
                  </td>
                  <td className="px-3 py-2">
                    <button onClick={() => flip(u, { is_disabled: !u.is_disabled }, u.is_disabled ? 'User enabled' : 'User disabled')}
                      className={`rounded-full px-2 py-0.5 text-xs ${u.is_disabled ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'}`} title="Toggle status">
                      {u.is_disabled ? 'disabled' : 'active'}
                    </button>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button onClick={() => openEdit(u)} className={`${btnGhost} mr-1`}>Edit</button>
                    <button onClick={() => { setPwFor(u); setNewPw(''); }} className={`${btnGhost} mr-1`}>Password</button>
                    <button onClick={() => setConfirm(u)} className="rounded-md bg-red-600 px-2 py-1 text-white">Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {creating && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setCreating(false)}>
          <div className="w-80 rounded-lg bg-white p-4 dark:bg-slate-900" onClick={(e) => e.stopPropagation()}>
            <h2 className="mb-3 font-bold">Add user</h2>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="username" className={`${input} mb-2`} />
            <input value={pw} onChange={(e) => setPw(e.target.value)} type="password" placeholder="password" className={`${input} mb-2`} />
            <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} /> admin</label>
            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setCreating(false)} className={btnGhost}>Cancel</button>
              <button onClick={doCreate} className={btn}>Create</button>
            </div>
          </div>
        </div>
      )}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setEditing(null)}>
          <div className="w-80 rounded-lg bg-white p-4 dark:bg-slate-900" onClick={(e) => e.stopPropagation()}>
            <h2 className="mb-3 font-bold">Edit user</h2>
            <input value={editName} onChange={(e) => setEditName(e.target.value)} placeholder="username" className={`${input} mb-2`} />
            <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={editAdmin} onChange={(e) => setEditAdmin(e.target.checked)} /> admin</label>
            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setEditing(null)} className={btnGhost}>Cancel</button>
              <button onClick={doEdit} className={btn}>Save</button>
            </div>
          </div>
        </div>
      )}
      {pwFor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setPwFor(null)}>
          <div className="w-80 rounded-lg bg-white p-4 dark:bg-slate-900" onClick={(e) => e.stopPropagation()}>
            <h2 className="mb-3 font-bold">Change password — {pwFor.username}</h2>
            <input value={newPw} onChange={(e) => setNewPw(e.target.value)} type="password" placeholder="new password" className={input} />
            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setPwFor(null)} className={btnGhost}>Cancel</button>
              <button onClick={() => flip(pwFor, { password: newPw }, 'Password changed').then(() => setPwFor(null))} className={btn}>Save</button>
            </div>
          </div>
        </div>
      )}
      {confirm && <Confirm text={`Delete user "${confirm.username}"?`} onYes={doDelete} onNo={() => setConfirm(null)} />}
      <Toasts items={items} />
    </Layout>
  );
}
