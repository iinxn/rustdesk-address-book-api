import { useEffect, useState } from 'react';
import { api } from '../api';
import { Confirm, Layout, LoadError, Loading, TagBadge, Toasts, btn, btnGhost, input } from '../components';
import { useTheme, useToasts } from '../hooks';
import type { Book, TagRow } from '../types';
import { colorCss } from '../types';

export default function Tags() {
  const { dark, toggle } = useTheme();
  const { items, push } = useToasts();
  const [books, setBooks] = useState<Book[]>([]);
  const [book, setBook] = useState('');
  const [tags, setTags] = useState<TagRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [name, setName] = useState('');
  const [color, setColor] = useState('#3b82f6');
  const [renaming, setRenaming] = useState<TagRow | null>(null);
  const [newName, setNewName] = useState('');
  const [confirm, setConfirm] = useState<TagRow | null>(null);

  const load = () => {
    if (!book) return;
    setLoading(true); setFailed(false);
    api.tags(book).then(setTags).catch(() => setFailed(true)).finally(() => setLoading(false));
  };
  useEffect(() => {
    api.books().then((b) => { setBooks(b); if (b.length && !book) setBook(b[0].id); }).catch(() => setFailed(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(load, [book]);

  const hexToInt = (h: string) => parseInt('ff' + h.replace('#', ''), 16);

  const create = async () => {
    if (!name.trim()) return;
    try {
      await api.createTag(book, { name: name.trim(), color: hexToInt(color) });
      setName(''); push(true, 'Tag created'); load();
    } catch (e) { push(false, String((e as Error).message)); }
  };
  const saveColor = async (t: TagRow, c: string) => {
    try {
      await api.updateTag(t.id, { name: t.name, color: hexToInt(c) });
      push(true, 'Color saved'); load();
    } catch (e) { push(false, String((e as Error).message)); }
  };
  const doRename = async () => {
    if (!renaming || !newName.trim()) return;
    try {
      await api.updateTag(renaming.id, { name: newName.trim(), color: renaming.color });
      setRenaming(null); push(true, 'Tag renamed'); load();
    } catch (e) { push(false, String((e as Error).message)); }
  };
  const doDelete = async () => {
    if (!confirm) return;
    try {
      await api.deleteTag(confirm.id);
      setConfirm(null); push(true, 'Tag deleted'); load();
    } catch (e) { push(false, String((e as Error).message)); }
  };

  return (
    <Layout dark={dark} onTheme={toggle}>
      <h1 className="mb-3 text-xl font-bold">Tags</h1>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <select value={book} onChange={(e) => setBook(e.target.value)} className={`${input} w-auto`}>
          {books.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="New tag name" className={`${input} w-48`} />
        <input type="color" value={color} onChange={(e) => setColor(e.target.value)} className="h-8 w-10 cursor-pointer" />
        <button onClick={create} className={btn}>+ Create tag</button>
      </div>
      {loading ? <Loading text="Loading tags" /> : failed ? <LoadError onRetry={load} /> : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-slate-200 text-left text-slate-500 dark:border-slate-800">
              <th className="px-3 py-2">Name</th><th className="px-3 py-2">Color</th><th className="px-3 py-2">Devices</th><th className="px-3 py-2"></th>
            </tr></thead>
            <tbody>
              {tags.map((t) => (
                <tr key={t.id} className="border-b border-slate-100 last:border-0 dark:border-slate-800">
                  <td className="px-3 py-2"><TagBadge name={t.name} color={t.color} /></td>
                  <td className="px-3 py-2">
                    <input type="color" value={colorCss(t.color)} onChange={(e) => saveColor(t, e.target.value)}
                      className="h-6 w-8 cursor-pointer" title="Change color" />
                  </td>
                  <td className="px-3 py-2">{t.devices}</td>
                  <td className="px-3 py-2 text-right">
                    <button onClick={() => { setRenaming(t); setNewName(t.name); }} className={`${btnGhost} mr-1`}>Rename</button>
                    <button onClick={() => setConfirm(t)} className="rounded-md bg-red-600 px-2 py-1 text-white">Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {tags.length === 0 && <p className="py-8 text-center text-sm text-slate-500">No tags yet</p>}
        </div>
      )}
      {renaming && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setRenaming(null)}>
          <div className="w-80 rounded-lg bg-white p-4 dark:bg-slate-900" onClick={(e) => e.stopPropagation()}>
            <h2 className="mb-3 font-bold">Rename tag</h2>
            <input value={newName} onChange={(e) => setNewName(e.target.value)} className={input} />
            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setRenaming(null)} className={btnGhost}>Cancel</button>
              <button onClick={doRename} className={btn}>Save</button>
            </div>
          </div>
        </div>
      )}
      {confirm && <Confirm text={`Delete tag "${confirm.name}"? Devices stay, links are removed.`} onYes={doDelete} onNo={() => setConfirm(null)} />}
      <Toasts items={items} />
    </Layout>
  );
}
