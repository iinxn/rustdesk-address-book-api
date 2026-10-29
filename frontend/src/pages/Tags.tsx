import { useEffect, useState } from 'react';
import { api } from '../api';
import { Confirm, Layout, LoadError, Loading, TagBadge, btn, btnGhost, input } from '../components';
import { useTheme } from '../hooks';
import { useI18n } from '../i18n';
import { useNotify } from '../notifications';
import type { Book, TagRow } from '../types';
import { colorCss } from '../types';

export default function Tags() {
  const { dark, toggle } = useTheme();
  const { t } = useI18n();
  const { notify } = useNotify();
  const [books, setBooks] = useState<Book[]>([]);
  const [book, setBook] = useState('');
  const [tags, setTags] = useState<TagRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [name, setName] = useState('');
  const [color, setColor] = useState('#3b82f6');
  const [creating, setCreating] = useState(false);
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
      setName(''); setCreating(false); notify(true, t('tags.created')); load();
    } catch (e) { notify(false, String((e as Error).message)); }
  };
  const saveColor = async (row: TagRow, c: string) => {
    try {
      await api.updateTag(row.id, { name: row.name, color: hexToInt(c) });
      notify(true, t('tags.colorSaved')); load();
    } catch (e) { notify(false, String((e as Error).message)); }
  };
  const doRename = async () => {
    if (!renaming || !newName.trim()) return;
    try {
      await api.updateTag(renaming.id, { name: newName.trim(), color: renaming.color });
      setRenaming(null); notify(true, t('tags.renamed')); load();
    } catch (e) { notify(false, String((e as Error).message)); }
  };
  const doDelete = async () => {
    if (!confirm) return;
    try {
      await api.deleteTag(confirm.id);
      setConfirm(null); notify(true, t('tags.deleted')); load();
    } catch (e) { notify(false, String((e as Error).message)); }
  };

  return (
    <Layout dark={dark} onTheme={toggle}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h1 className="text-xl font-bold">{t('tags.title')}</h1>
        <button onClick={() => { setName(''); setCreating(true); }} className={btn}>{t('tags.create')}</button>
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <select aria-label={t('tags.bookLabel')} value={book} onChange={(e) => setBook(e.target.value)} className={`${input} sm:w-auto`}>
          {books.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
      </div>
      {loading ? <Loading text={t('tags.loading')} /> : failed ? <LoadError onRetry={load} /> : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-slate-200 text-left text-slate-600 dark:border-slate-800 dark:text-slate-300">
              <th className="px-3 py-2">{t('tags.name')}</th><th className="px-3 py-2">{t('tags.color')}</th><th className="px-3 py-2">{t('tags.devices')}</th><th className="px-3 py-2"></th>
            </tr></thead>
            <tbody>
              {tags.map((row) => (
                <tr key={row.id} className="border-b border-slate-100 last:border-0 dark:border-slate-800">
                  <td className="px-3 py-2"><TagBadge name={row.name} color={row.color} /></td>
                  <td className="px-3 py-2">
                    <input type="color" value={colorCss(row.color)} onChange={(e) => saveColor(row, e.target.value)}
                      className="h-6 w-8 cursor-pointer" title={t('tags.changeColor')} />
                  </td>
                  <td className="px-3 py-2">{row.devices}</td>
                  <td className="px-3 py-2 text-right">
                    <button onClick={() => { setRenaming(row); setNewName(row.name); }} className={`${btnGhost} mr-1`}>{t('common.rename')}</button>
                    <button onClick={() => setConfirm(row)} className="rounded-md bg-red-600 px-2 py-1 text-white hover:bg-red-700">{t('common.delete')}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {tags.length === 0 && <p className="py-8 text-center text-sm text-slate-500 dark:text-slate-400">{t('tags.empty')}</p>}
        </div>
      )}
      {renaming && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setRenaming(null)}>
          <div className="w-80 rounded-lg bg-white p-4 text-slate-900 dark:bg-slate-900 dark:text-slate-100" onClick={(e) => e.stopPropagation()}>
            <h2 className="mb-3 font-bold">{t('tags.renameTitle')}</h2>
            <input value={newName} onChange={(e) => setNewName(e.target.value)} className={input} />
            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setRenaming(null)} className={btnGhost}>{t('common.cancel')}</button>
              <button onClick={doRename} className={btn}>{t('common.save')}</button>
            </div>
          </div>
        </div>
      )}
      {confirm && <Confirm text={t('tags.deleteConfirm', { name: confirm.name })} onYes={doDelete} onNo={() => setConfirm(null)} />}
      {creating && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setCreating(false)}>
          <div className="w-80 rounded-lg bg-white p-4 text-slate-900 dark:bg-slate-900 dark:text-slate-100" onClick={(e) => e.stopPropagation()}>
            <h2 className="mb-3 font-bold">{t('tags.createTitle')}</h2>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('tags.namePlaceholder')} className={`${input} mb-2`} />
            <label className="flex items-center gap-2 text-sm">{t('tags.color')}
              <input type="color" value={color} onChange={(e) => setColor(e.target.value)} className="h-8 w-10 cursor-pointer" />
            </label>
            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setCreating(false)} className={btnGhost}>{t('common.cancel')}</button>
              <button onClick={create} className={btn}>{t('common.create')}</button>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}
