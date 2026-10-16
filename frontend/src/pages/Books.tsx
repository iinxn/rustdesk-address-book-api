import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { Confirm, Layout, LoadError, Loading, Toasts, btn, btnGhost, input } from '../components';
import { useTheme, useToasts } from '../hooks';
import type { Book } from '../types';

export default function Books() {
  const { dark, toggle } = useTheme();
  const { items, push } = useToasts();
  const nav = useNavigate();
  const [books, setBooks] = useState<Book[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [name, setName] = useState('');
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<Book | null>(null);
  const [newName, setNewName] = useState('');
  const [confirm, setConfirm] = useState<Book | null>(null);
  const load = () => {
    setLoading(true); setFailed(false);
    api.books().then(setBooks).catch(() => setFailed(true)).finally(() => setLoading(false));
  };
  useEffect(load, []);
  const openBook = (b: Book) => {
    sessionStorage.setItem('ab_book', b.id);
    nav('/');
  };
  const doCreate = async () => {
    if (!name.trim()) return;
    try {
      await api.createBook(name.trim());
      setName(''); setCreating(false); push(true, 'Address book created'); load();
    } catch (e) { push(false, String((e as Error).message)); }
  };
  const doRename = async () => {
    if (!renaming || !newName.trim()) return;
    try {
      await api.renameBook(renaming.id, newName.trim());
      setRenaming(null); push(true, 'Address book renamed'); load();
    } catch (e) { push(false, String((e as Error).message)); }
  };
  const doDelete = async () => {
    if (!confirm) return;
    try {
      await api.deleteBook(confirm.id);
      setConfirm(null); push(true, 'Address book deleted'); load();
    } catch (e) { push(false, String((e as Error).message)); }
  };
  const canManage = (b: Book) => b.type === 'shared' && (b.rule ?? 0) >= 3;
  return (
    <Layout dark={dark} onTheme={toggle}>
      <div className="mb-3 flex items-center justify-between">
        <h1 className="text-xl font-bold">Address Books</h1>
        <button onClick={() => { setName(''); setCreating(true); }} className={btn}>+ Create</button>
      </div>
      {loading ? <Loading text="Loading books" /> : failed ? <LoadError onRetry={load} /> : (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {books.map((b) => (
            <div key={b.id} className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
              <button onClick={() => openBook(b)} className="font-medium text-blue-600 hover:underline" title="Open devices">
                {b.name}
              </button>
              <div className="text-xs text-slate-500">{b.type}{b.type === 'personal' ? ' (name shown by client is fixed)' : ''}</div>
              <div className="mt-2 text-sm">{b.devices} devices · 🟢 {b.online} · ⚪ {b.offline}{b.unknown ? ` · ? ${b.unknown}` : ''}</div>
              {canManage(b) && (
                <div className="mt-2 flex gap-1">
                  <button onClick={() => { setRenaming(b); setNewName(b.name); }} className={`${btnGhost} px-2 py-0.5 text-xs`}>Rename</button>
                  <button onClick={() => setConfirm(b)} className="rounded-md bg-red-600 px-2 py-0.5 text-xs text-white">Delete</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {renaming && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setRenaming(null)}>
          <div className="w-80 rounded-lg bg-white p-4 dark:bg-slate-900" onClick={(e) => e.stopPropagation()}>
            <h2 className="mb-3 font-bold">Rename address book</h2>
            <input value={newName} onChange={(e) => setNewName(e.target.value)} className={input} />
            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setRenaming(null)} className={btnGhost}>Cancel</button>
              <button onClick={doRename} className={btn}>Save</button>
            </div>
          </div>
        </div>
      )}
      {confirm && <Confirm text={`Delete "${confirm.name}" with all its devices and tags?`} onYes={doDelete} onNo={() => setConfirm(null)} />}
      {creating && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setCreating(false)}>
          <div className="w-80 rounded-lg bg-white p-4 dark:bg-slate-900" onClick={(e) => e.stopPropagation()}>
            <h2 className="mb-3 font-bold">Create address book</h2>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Shared book name" className={input} />
            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setCreating(false)} className={btnGhost}>Cancel</button>
              <button onClick={doCreate} className={btn}>Create</button>
            </div>
          </div>
        </div>
      )}
      <Toasts items={items} />
    </Layout>
  );
}
