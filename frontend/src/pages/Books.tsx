import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { Confirm, Layout, LoadError, Loading, btn, btnGhost, input } from '../components';
import { useTheme } from '../hooks';
import { useI18n } from '../i18n';
import { useNotify } from '../notifications';
import type { Book } from '../types';

export default function Books() {
  const { dark, toggle } = useTheme();
  const { t } = useI18n();
  const { notify } = useNotify();
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
  const typeLabel = (b: Book) =>
    b.type === 'personal'
      ? t('books.typePersonal')
      : b.type === 'shared'
        ? t('books.typeShared')
        : t('books.typeOther', { type: b.type });
  const doCreate = async () => {
    if (!name.trim()) return;
    try {
      await api.createBook(name.trim());
      setName(''); setCreating(false); notify(true, t('books.created')); load();
    } catch (e) { notify(false, String((e as Error).message)); }
  };
  const doRename = async () => {
    if (!renaming || !newName.trim()) return;
    try {
      await api.renameBook(renaming.id, newName.trim());
      setRenaming(null); notify(true, t('books.renamed')); load();
    } catch (e) { notify(false, String((e as Error).message)); }
  };
  const doDelete = async () => {
    if (!confirm) return;
    try {
      await api.deleteBook(confirm.id);
      setConfirm(null); notify(true, t('books.deleted')); load();
    } catch (e) { notify(false, String((e as Error).message)); }
  };
  const canManage = (b: Book) => b.type === 'shared' && (b.rule ?? 0) >= 3;
  return (
    <Layout dark={dark} onTheme={toggle}>
      <div className="mb-3 flex items-center justify-between">
        <h1 className="text-xl font-bold">{t('books.title')}</h1>
        <button onClick={() => { setName(''); setCreating(true); }} className={btn}>{t('books.create')}</button>
      </div>
      {loading ? <Loading text={t('books.loading')} /> : failed ? <LoadError onRetry={load} /> : (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {books.map((b) => (
            <div key={b.id} className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
              <button onClick={() => openBook(b)} className="font-medium text-blue-700 hover:underline dark:text-blue-400" title={t('books.openTitle')}>
                {b.name}
              </button>
              <div className="text-xs text-slate-500 dark:text-slate-400">
                {typeLabel(b)}{b.type === 'personal' ? t('books.personalNote') : ''}
              </div>
              <div className="mt-2 text-sm">
                {t('books.stats', { devices: b.devices, online: b.online, offline: b.offline })}
                {b.unknown ? t('books.statsUnknown', { n: b.unknown }) : ''}
              </div>
              {canManage(b) && (
                <div className="mt-2 flex gap-1">
                  <button onClick={() => { setRenaming(b); setNewName(b.name); }} className={`${btnGhost} px-2 py-0.5 text-xs`}>{t('common.rename')}</button>
                  <button onClick={() => setConfirm(b)} className="rounded-md bg-red-600 px-2 py-0.5 text-xs text-white hover:bg-red-700">{t('common.delete')}</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {renaming && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setRenaming(null)}>
          <div className="w-80 rounded-lg bg-white p-4 text-slate-900 dark:bg-slate-900 dark:text-slate-100" onClick={(e) => e.stopPropagation()}>
            <h2 className="mb-3 font-bold">{t('books.renameTitle')}</h2>
            <input value={newName} onChange={(e) => setNewName(e.target.value)} className={input} />
            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setRenaming(null)} className={btnGhost}>{t('common.cancel')}</button>
              <button onClick={doRename} className={btn}>{t('common.save')}</button>
            </div>
          </div>
        </div>
      )}
      {confirm && <Confirm text={t('books.deleteConfirm', { name: confirm.name })} onYes={doDelete} onNo={() => setConfirm(null)} />}
      {creating && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setCreating(false)}>
          <div className="w-80 rounded-lg bg-white p-4 text-slate-900 dark:bg-slate-900 dark:text-slate-100" onClick={(e) => e.stopPropagation()}>
            <h2 className="mb-3 font-bold">{t('books.createTitle')}</h2>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('books.namePlaceholder')} className={input} />
            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setCreating(false)} className={btnGhost}>{t('common.cancel')}</button>
              <button onClick={doCreate} className={btn}>{t('common.create')}</button>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}
