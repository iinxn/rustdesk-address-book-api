/** Add-discovered, bulk-tag and create/edit dialogs of the Devices page. */
import { useEffect, useState } from 'react';
import { api } from '../../api';
import { Badge, Checkbox, Modal, TagBadge, btn, btnGhost, input } from '../../components';
import { useI18n } from '../../i18n';
import type { Book, Device, DiscoveredDevice, TagRow } from '../../types';

export function AddDiscoveredModal({ device, books, defaultBook, onClose, onSaved }: {
  device: DiscoveredDevice;
  books: Book[];
  defaultBook: string;
  onClose: () => void;
  onSaved: (d: DiscoveredDevice) => void;
}) {
  const { t } = useI18n();
  const initialBook = books.some((b) => b.id === defaultBook) ? defaultBook : books[0]?.id || '';
  const [bookId, setBookId] = useState(initialBook);
  const [alias, setAlias] = useState(device.info?.hostname || device.rustdesk_id);
  const [note, setNote] = useState('');
  const [typed, setTyped] = useState('');
  const [picked, setPicked] = useState<string[]>([]);
  const [bookTags, setBookTags] = useState<TagRow[]>([]);
  const [tagsLoading, setTagsLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!bookId) { setTagsLoading(false); return; }
    let alive = true;
    setTagsLoading(true);
    api.tags(bookId)
      .then((list) => { if (alive) setBookTags(list); })
      .catch(() => { if (alive) setBookTags([]); })
      .finally(() => { if (alive) setTagsLoading(false); });
    return () => { alive = false; };
  }, [bookId]);

  const typedNames = typed.split(',').map((s) => s.trim()).filter(Boolean);
  const tagNames = Array.from(new Set([...picked, ...typedNames])).slice(0, 20);

  const togglePick = (name: string) => {
    setPicked((prev) => (prev.includes(name) ? prev.filter((x) => x !== name) : [...prev, name]));
  };

  const save = async () => {
    if (busy) return;
    if (!bookId) { setError(t('dev.chooseBook')); return; }
    setBusy(true);
    setError('');
    try {
      await api.addDiscovered(device.rustdesk_id, {
        book_id: bookId,
        alias: alias.trim(),
        note,
        tags: tagNames,
      });
      onSaved(device);
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={t('dev.addDiscoveredTitle')}
      subtitle={t('dev.addDiscoveredSubtitle')}
      onClose={onClose}
      footer={
        <>
          <button className={btnGhost} onClick={onClose} disabled={busy}>{t('common.cancel')}</button>
          <button className={btn} onClick={() => { void save(); }} disabled={busy || books.length === 0}>
            {busy ? t('dev.adding') : t('dev.addToBook')}
          </button>
        </>
      }
    >
      <div className="mb-4 rounded-lg bg-slate-50 px-3 py-2 text-sm dark:bg-slate-800">
        <div className="font-medium">{device.info?.hostname || device.rustdesk_id}</div>
        <div className="font-mono text-xs text-slate-500 dark:text-slate-400">{device.rustdesk_id}</div>
        <div className="text-xs text-slate-500 dark:text-slate-400">
          {[device.info?.os_name, device.info?.version ? `v${device.info.version}` : '', device.last_ip]
            .filter(Boolean).join(' · ') || t('dev.freshNo')}
        </div>
      </div>

      {error && <p className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">{error}</p>}
      {books.length === 0 && (
        <p className="mb-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          {t('dev.noWriteAccess')}
        </p>
      )}

      <div className="space-y-3">
        <label className="block text-sm">
          {t('dev.selectBook')}
          <select aria-label={t('dev.selectBook')} value={bookId} onChange={(e) => setBookId(e.target.value)} className={`${input} mt-1`}>
            {books.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </label>
        <label className="block text-sm">
          {t('dev.alias')}
          <input value={alias} onChange={(e) => setAlias(e.target.value)} className={`${input} mt-1`} />
        </label>
        <div className="text-sm">
          {t('dev.tags')}
          <div className="mt-1 max-h-36 overflow-y-auto rounded border border-slate-200 p-2 dark:border-slate-700">
            {bookTags.map((tag) => (
              <label key={tag.id} className="flex items-center gap-2 py-0.5 text-sm">
                <Checkbox
                  checked={picked.includes(tag.name)}
                  onChange={() => togglePick(tag.name)}
                  label={t('dev.tag', { name: tag.name })}
                />
                <TagBadge name={tag.name} color={tag.color} />
              </label>
            ))}
            {!tagsLoading && bookTags.length === 0 && (
              <span className="text-xs text-slate-500 dark:text-slate-400">{t('dev.noTagsBook')}</span>
            )}
            {tagsLoading && <span className="text-xs text-slate-500 dark:text-slate-400">{t('dev.loadingTags')}</span>}
          </div>
          <input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={t('dev.newTagsPlaceholder')}
            className={`${input} mt-2`}
          />
          {tagNames.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {tagNames.map((name) => <Badge key={name} tone="slate">{name}</Badge>)}
            </div>
          )}
        </div>
        <label className="block text-sm">
          {t('dev.note')}
          <textarea value={note} onChange={(e) => setNote(e.target.value)} className={`${input} mt-1`} rows={2} />
        </label>
      </div>
    </Modal>
  );
}

export function BulkTagModal({ count, tags, onClose, onApply }: {
  count: number;
  tags: TagRow[];
  onClose: () => void;
  onApply: (add: string[], remove: string[]) => Promise<void>;
}) {
  const { t } = useI18n();
  const [add, setAdd] = useState<string[]>([]);
  const [remove, setRemove] = useState<string[]>([]);
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const typedNames = typed.split(',').map((s) => s.trim()).filter(Boolean);
  const finalAdd = Array.from(new Set([...add, ...typedNames])).slice(0, 20);

  const toggleAdd = (name: string) => {
    setAdd((prev) => (prev.includes(name) ? prev.filter((x) => x !== name) : [...prev, name]));
    setRemove((prev) => prev.filter((x) => x !== name));
  };
  const toggleRemove = (name: string) => {
    setRemove((prev) => (prev.includes(name) ? prev.filter((x) => x !== name) : [...prev, name]));
    setAdd((prev) => prev.filter((x) => x !== name));
  };

  const apply = async () => {
    if (busy) return;
    if (finalAdd.length === 0 && remove.length === 0) {
      setError(t('dev.selectOneTag'));
      return;
    }
    const overlap = finalAdd.filter((name) => remove.includes(name));
    if (overlap.length > 0) {
      setError(t('dev.tagOverlap', { name: overlap[0] }));
      return;
    }
    setBusy(true);
    setError('');
    try {
      await onApply(finalAdd, remove);
      onClose();
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={t('dev.bulkTagsTitle')}
      subtitle={t('dev.bulkTagsSubtitle', { n: count })}
      onClose={onClose}
      size="lg"
      footer={
        <>
          <button className={btnGhost} onClick={onClose} disabled={busy}>{t('common.cancel')}</button>
          <button className={btn} onClick={() => { void apply(); }} disabled={busy}>
            {busy ? t('dev.applying') : t('dev.apply')}
          </button>
        </>
      }
    >
      {error && <p className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">{error}</p>}
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-green-700 dark:text-green-400">{t('dev.addTags')}</h3>
          <div className="max-h-40 overflow-y-auto rounded border border-slate-200 p-2 dark:border-slate-700">
            {tags.map((tag) => (
              <label key={tag.id} className="flex items-center gap-2 py-0.5 text-sm">
                <Checkbox checked={add.includes(tag.name)} onChange={() => toggleAdd(tag.name)} label={t('dev.addTag', { name: tag.name })} />
                <TagBadge name={tag.name} color={tag.color} />
              </label>
            ))}
            {tags.length === 0 && <span className="text-xs text-slate-500 dark:text-slate-400">{t('dev.noTagsBook')}</span>}
          </div>
          <input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={t('dev.newTagsPlaceholder')}
            className={`${input} mt-2`}
          />
          {typedNames.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {typedNames.map((name) => <Badge key={name} tone="green">{name}</Badge>)}
            </div>
          )}
        </div>
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-red-700 dark:text-red-400">{t('dev.removeTags')}</h3>
          <div className="max-h-40 overflow-y-auto rounded border border-slate-200 p-2 dark:border-slate-700">
            {tags.map((tag) => (
              <label key={tag.id} className="flex items-center gap-2 py-0.5 text-sm">
                <Checkbox checked={remove.includes(tag.name)} onChange={() => toggleRemove(tag.name)} label={t('dev.removeTag', { name: tag.name })} />
                <TagBadge name={tag.name} color={tag.color} />
              </label>
            ))}
            {tags.length === 0 && <span className="text-xs text-slate-500 dark:text-slate-400">{t('dev.noTagsBook')}</span>}
          </div>
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            {t('dev.tagDetachNote')}
          </p>
        </div>
      </div>
      <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">{t('dev.upTo20')}</p>
    </Modal>
  );
}

export function DeviceForm({ book, initial, tags, tagsReady = true, onClose, onSaved, onError }: {
  book: string;
  initial: Device | null;
  tags: TagRow[];
  tagsReady?: boolean;
  onClose: () => void;
  onSaved: (m: string) => void;
  onError: (m: string) => void;
}) {
  const { t } = useI18n();
  const [rid, setRid] = useState(initial?.rustdesk_id || '');
  const [alias, setAlias] = useState(initial?.alias || '');
  const [note, setNote] = useState(initial?.note || '');
  const [pw, setPw] = useState('');
  const [sel, setSel] = useState<string[]>(initial?.tags || []);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!rid.trim()) { onError(t('dev.rustdeskIdRequired')); return; }
    if (!tagsReady) { onError(t('dev.tagsStillLoading')); return; }
    setBusy(true);
    try {
      const body = { rustdesk_id: rid.trim(), alias, note, tags: sel, password: pw };
      if (initial) await api.updateEntry(initial.id, body);
      else await api.createEntry(book, body);
      onSaved(initial ? t('dev.deviceUpdated') : t('dev.deviceCreated'));
    } catch (e) {
      onError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose} role="presentation">
      <div
        className="max-h-[90vh] w-full max-w-md overflow-y-auto rounded-lg bg-white p-5 text-slate-900 shadow-xl dark:bg-slate-900 dark:text-slate-100"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={initial ? t('dev.editDevice') : t('dev.addDevice')}
      >
        <div className="mb-4 flex items-start justify-between gap-2">
          <h2 className="text-lg font-bold">{initial ? t('dev.editDevice') : t('dev.addDevice')}</h2>
          <button onClick={onClose} aria-label={t('common.close')} className="rounded border border-slate-200 px-2 py-0.5 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">✕</button>
        </div>
        <div className="space-y-3">
          <label className="block text-sm">
            {t('dev.rustdeskId')}
            <input value={rid} onChange={(e) => setRid(e.target.value)} className={`${input} mt-1`} />
          </label>
          <label className="block text-sm">
            {t('dev.alias')}
            <input value={alias} onChange={(e) => setAlias(e.target.value)} className={`${input} mt-1`} />
          </label>
          <div className="text-sm">
            {t('dev.tags')}
            <div className="mt-1 max-h-32 overflow-y-auto rounded border border-slate-200 p-2 dark:border-slate-700">
              {tags.map((tag) => (
                <label key={tag.id} className="flex items-center gap-2 py-0.5 text-sm">
                  <Checkbox
                    checked={sel.includes(tag.name)}
                    onChange={() => setSel((list) => (list.includes(tag.name) ? list.filter((x) => x !== tag.name) : [...list, tag.name]))}
                    label={t('dev.tag', { name: tag.name })}
                  />
                  <TagBadge name={tag.name} color={tag.color} />
                </label>
              ))}
              {tagsReady && tags.length === 0 && <span className="text-slate-500 dark:text-slate-400">{t('dev.noTagsBookShort')}</span>}
              {!tagsReady && <span className="text-slate-500 dark:text-slate-400">{t('dev.loadingTags')}</span>}
            </div>
          </div>
          <label className="block text-sm">
            {t('dev.note')}
            <textarea value={note} onChange={(e) => setNote(e.target.value)} className={`${input} mt-1`} rows={2} />
          </label>
          <label className="block text-sm">
            {t('common.password')} {initial && t('dev.passwordKeep')}
            <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} className={`${input} mt-1`} />
          </label>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className={btnGhost}>{t('common.cancel')}</button>
          <button onClick={() => { void save(); }} disabled={busy || !tagsReady} className={btn}>
            {busy ? t('common.saving') : t('common.save')}
          </button>
        </div>
      </div>
    </div>
  );
}

