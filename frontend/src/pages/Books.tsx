import { useEffect, useState } from 'react';
import { api } from '../api';
import { Layout, LoadError, Loading, Toasts } from '../components';
import { useTheme, useToasts } from '../hooks';
import type { Book } from '../types';

export default function Books() {
  const { dark, toggle } = useTheme();
  const { items, push } = useToasts();
  const [books, setBooks] = useState<Book[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [name, setName] = useState('');
  const load = () => {
    setLoading(true); setFailed(false);
    api.books().then(setBooks).catch(() => setFailed(true)).finally(() => setLoading(false));
  };
  useEffect(load, []);
  const doCreate = async () => {
    if (!name.trim()) return;
    try {
      await api.createBook(name.trim());
      setName(''); push(true, 'Address book created'); load();
    } catch (e) { push(false, String((e as Error).message)); }
  };
  return (
    <Layout dark={dark} onTheme={toggle}>
      <h1 className="mb-3 text-xl font-bold">Address Books</h1>
      <div className="mb-3 flex gap-2">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="New shared book name"
          className="w-64 rounded-md border border-slate-300 px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800" />
        <button onClick={doCreate} className="rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white">+ Create</button>
      </div>
      {loading ? <Loading text="Loading books" /> : failed ? <LoadError onRetry={load} /> : (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {books.map((b) => (
            <div key={b.id} className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
              <div className="font-medium">{b.name}</div>
              <div className="text-xs text-slate-500">{b.type}</div>
              <div className="mt-2 text-sm">{b.devices} devices · 🟢 {b.online} · ⚪ {b.offline}{b.unknown ? ` · ? ${b.unknown}` : ''}</div>
            </div>
          ))}
        </div>
      )}
      <Toasts items={items} />
    </Layout>
  );
}
