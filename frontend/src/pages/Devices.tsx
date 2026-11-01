import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, sessionUser } from '../api';
import {
  Checkbox, Confirm, Layout, LoadError, Loading, Pagination, btn, btnDanger, btnGhost,
  input,
} from '../components';
import { useDebounce, useTheme } from '../hooks';
import { useI18n } from '../i18n';
import { useNotify } from '../notifications';
import { colorCss, textOnColor } from '../types';
import type { Book, Device, DiscoveredDevice, Stats, TagRow } from '../types';
import { DetailDrawer } from './devices/DetailDrawer';
import { AddDiscoveredModal, BulkTagModal, DeviceForm } from './devices/dialogs';
import { DiscoveredRow, EntryRow, SectionHeader, TabButton } from './devices/rows';

const SIZE = 50;
type Tab = 'all' | 'book' | 'discovered';
type DiscStatus = 'all' | 'online' | 'offline';

const emptyStats: Stats = {
  devices: 0, online: 0, offline: 0, unknown: 0, discovered: 0, discovered_online: 0,
};

export default function Devices() {
  const { dark, toggle } = useTheme();
  const { t } = useI18n();
  const { notify } = useNotify();
  const isAdmin = sessionUser()?.isAdmin ?? false;

  const [books, setBooks] = useState<Book[]>([]);
  const [book, setBook] = useState('');
  const [tab, setTab] = useState<Tab>(() => {
    const saved = localStorage.getItem('ab_tab');
    return saved === 'book' || saved === 'discovered' || saved === 'all' ? saved : 'all';
  });
  const [devices, setDevices] = useState<Device[]>([]);
  const [total, setTotal] = useState(0);
  const [disc, setDisc] = useState<DiscoveredDevice[]>([]);
  const [discTotal, setDiscTotal] = useState(0);
  const [tags, setTags] = useState<TagRow[]>([]);
  const [stats, setStats] = useState<Stats>(emptyStats);
  const [search, setSearch] = useState('');
  const [selTags, setSelTags] = useState<string[]>([]);
  const [mode, setMode] = useState<'and' | 'or'>('or');
  const [presence, setPresence] = useState('');
  const [sort, setSort] = useState('status');
  const [page, setPage] = useState(1);
  const [discStatus, setDiscStatus] = useState<DiscStatus>('all');
  const [discPage, setDiscPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [discLoading, setDiscLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [discFailed, setDiscFailed] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [detailRid, setDetailRid] = useState<string | null>(null);
  const [detailReload, setDetailReload] = useState(0);
  const [editing, setEditing] = useState<Device | 'new' | null>(null);
  const [formBook, setFormBook] = useState('');
  const [formTags, setFormTags] = useState<TagRow[]>([]);
  const [formTagsReady, setFormTagsReady] = useState(true);
  const [confirmDel, setConfirmDel] = useState<Device | null>(null);
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);
  const [bulkTagOpen, setBulkTagOpen] = useState(false);
  const [addTarget, setAddTarget] = useState<DiscoveredDevice | null>(null);
  const [busy, setBusy] = useState(false);
  const tagRequest = useRef(0);

  const q = useDebounce(search);
  const bookMeta = useMemo(() => books.find((b) => b.id === book), [books, book]);
  const canWrite = (bookMeta?.rule ?? 0) >= 2;
  const writableBooks = useMemo(() => books.filter((b) => b.rule >= 2), [books]);
  const booksById = useMemo(() => new Map(books.map((b) => [b.id, b])), [books]);
  const canWriteBook = useCallback((bookId: string) => (booksById.get(bookId)?.rule ?? 0) >= 2, [booksById]);

  const showEntries = tab !== 'discovered';
  const showDisc = tab !== 'book';
  const entryFiltersActive = q !== '' || selTags.length > 0 || presence !== '';
  const filtersActive = q !== '' || discStatus !== 'all'
    || (tab !== 'discovered' && (selTags.length > 0 || presence !== ''));
  const allOnPage = devices.length > 0 && selected.size === devices.length;
  const someOnPage = selected.size > 0 && !allOnPage;

  useEffect(() => {
    localStorage.setItem('ab_tab', tab);
  }, [tab]);

  useEffect(() => {
    // Deep link from the audit log: open this device's card once.
    const wanted = sessionStorage.getItem('ab_device');
    if (wanted) {
      sessionStorage.removeItem('ab_device');
      setDetailRid(wanted);
    }
  }, []);

  useEffect(() => {
    api.books().then((list) => {
      setBooks(list);
      const wanted = sessionStorage.getItem('ab_book') || '';
      sessionStorage.removeItem('ab_book');
      setBook((current) => {
        if (current && list.some((b) => b.id === current)) return current;
        if (wanted && list.some((b) => b.id === wanted)) return wanted;
        return list[0]?.id || '';
      });
    }).catch(() => {
      setFailed(true);
      setDiscFailed(true);
      setLoading(false);
      setDiscLoading(false);
    });
  }, []);

  const load = useCallback(async (silent = false) => {
    if (!book) return;
    const wantEntries = tab !== 'discovered';
    const wantDisc = tab !== 'book';
    if (!silent) {
      if (wantEntries) { setLoading(true); setFailed(false); }
      if (wantDisc) { setDiscLoading(true); setDiscFailed(false); }
    }
    try {
      const [pageData, tagData, statData, discData] = await Promise.all([
        wantEntries
          ? api.entries(book, { search: q, mode, presence, sort, page, page_size: SIZE }, selTags)
          : Promise.resolve(null),
        api.tags(book),
        api.stats(),
        wantDisc
          ? api.discovered({
            search: q,
            status: discStatus,
            page: discPage,
            page_size: SIZE,
            only_unlinked: tab === 'all' ? 1 : 0,
          })
          : Promise.resolve(null),
      ]);
      if (pageData) {
        setDevices(pageData.data);
        setTotal(pageData.total);
        setFailed(false);
      }
      setTags(tagData);
      setStats(statData);
      if (discData) {
        setDisc(discData.data);
        setDiscTotal(discData.total);
        setDiscFailed(false);
      }
    } catch {
      if (!silent) {
        if (wantEntries) setFailed(true);
        if (wantDisc) setDiscFailed(true);
      }
    } finally {
      if (!silent) {
        if (wantEntries) setLoading(false);
        if (wantDisc) setDiscLoading(false);
      }
    }
  }, [book, tab, q, mode, presence, sort, page, selTags, discStatus, discPage]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const timer = window.setInterval(() => { void load(true); }, 20000);
    return () => window.clearInterval(timer);
  }, [load]);
  useEffect(() => { setPage(1); }, [q, selTags, mode, presence, sort, book, tab]);
  useEffect(() => { setDiscPage(1); }, [q, discStatus, tab]);
  useEffect(() => { setSelected(new Set()); }, [book, q, selTags, mode, presence, sort, page, tab]);
  useEffect(() => {
    // A silent refresh can remove entries deleted elsewhere; never keep
    // selection for rows that are no longer visible.
    setSelected((prev) => {
      if (prev.size === 0) return prev;
      const visible = new Set(devices.map((d) => d.id));
      const next = new Set([...prev].filter((id) => visible.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [devices]);

  const reloadBooks = useCallback(() => {
    api.books().then(setBooks).catch(() => {});
  }, []);

  const refreshAll = useCallback(() => {
    void load(true);
    reloadBooks();
  }, [load, reloadBooks]);

  const clearAll = () => {
    setSearch('');
    setSelTags([]);
    setMode('or');
    setPresence('');
    setDiscStatus('all');
  };

  const toggleSelected = (id: string, on: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(id); else next.delete(id);
      return next;
    });
  };

  const toggleAllOnPage = () => {
    setSelected(allOnPage ? new Set() : new Set(devices.map((d) => d.id)));
  };

  const openCreate = () => {
    if (!book) { notify(false, t('dev.selectBookFirst')); return; }
    tagRequest.current += 1;
    setEditing('new');
    setFormBook(book);
    setFormTags(tags);
    setFormTagsReady(true);
  };

  const openEdit = (d: Device, bookId: string) => {
    const request = ++tagRequest.current;
    setEditing(d);
    setFormBook(bookId);
    if (bookId === book) {
      setFormTags(tags);
      setFormTagsReady(true);
      return;
    }
    // Tags belong to the entry's book, not necessarily the selected one.
    setFormTags([]);
    setFormTagsReady(false);
    api.tags(bookId)
      .then((list) => {
        if (request !== tagRequest.current) return;
        setFormTags(list);
        setFormTagsReady(true);
      })
      .catch(() => {
        if (request !== tagRequest.current) return;
        // Preserve the entry's current tag names rather than saving an empty
        // list (which would detach every tag).
        setFormTags(d.tags.map((name) => ({ id: name, name, color: 0, devices: 0 })));
        setFormTagsReady(true);
      });
  };

  useEffect(() => {
    // Keep the form's tag list in sync while the user edits an entry in the
    // currently selected book (tags may finish loading after the form opens).
    if (editing && formBook === book) {
      setFormTags(tags);
      setFormTagsReady(true);
    }
  }, [tags, editing, formBook, book]);

  const doDelete = async () => {
    if (!confirmDel || busy) return;
    setBusy(true);
    try {
      await api.deleteEntry(confirmDel.id);
      notify(true, t('dev.removedFromBook'));
      setConfirmDel(null);
      refreshAll();
    } catch (e) {
      notify(false, String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const doBulkDelete = async () => {
    if (busy || selected.size === 0) return;
    setBusy(true);
    try {
      const result = await api.bulkDelete([...selected]);
      if (result.deleted.length > 0) {
        notify(true, t('dev.deletedCount', { n: result.deleted.length }));
      }
      if (result.failed.length > 0) {
        notify(false, t('dev.deleteFailedCount', { n: result.failed.length }));
      }
      setBulkDeleteOpen(false);
      setSelected(new Set(result.failed.map((f) => f.id)));
      refreshAll();
    } catch (e) {
      notify(false, String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const applyBulkTags = async (add: string[], remove: string[]) => {
    if (busy) return;
    const ids = [...selected];
    if (ids.length === 0) return;
    setBusy(true);
    try {
      const result = await api.bulkTags(ids, add, remove);
      if (result.updated.length > 0) {
        notify(true, t('dev.tagsUpdatedCount', { n: result.updated.length }));
      }
      if (result.failed.length > 0) {
        notify(false, t('dev.tagsFailedCount', { n: result.failed.length }));
      }
      setSelected(new Set(result.failed.map((f) => f.id)));
      refreshAll();
    } finally {
      setBusy(false);
    }
  };

  const renderEntries = () => {
    if (loading && devices.length === 0) return <Loading text={t('dev.loadingDevices')} />;
    if (failed && devices.length === 0) return <LoadError onRetry={() => { void load(); }} />;
    if (devices.length === 0) {
      return (
        <div className="rounded-lg border border-dashed border-slate-300 py-10 text-center text-sm text-slate-500 dark:text-slate-400 dark:border-slate-700">
          {entryFiltersActive ? (
            <>
              {t('dev.noMatchFilters')}
              <br />
              <button onClick={clearAll} className={`${btnGhost} mt-2`}>{t('dev.clearFilters')}</button>
            </>
          ) : (
            <>
              {t('dev.emptyBook')}
              {canWrite && (
                <>
                  <br />
                  <button onClick={openCreate} className={`${btn} mt-2`}>{t('dev.addFirst')}</button>
                </>
              )}
            </>
          )}
        </div>
      );
    }
    return (
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        {canWrite && (
          <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-slate-50 px-3 py-2 text-xs dark:border-slate-800 dark:bg-slate-800/50">
            <Checkbox
              checked={allOnPage}
              indeterminate={someOnPage}
              onChange={toggleAllOnPage}
              label={t('dev.selectAllDevices')}
            />
            <span className="font-medium">{t('dev.selectAllPage')}</span>
            {someOnPage && <span className="ml-auto text-slate-500 dark:text-slate-400">{t('dev.selected', { n: selected.size })}</span>}
          </div>
        )}
        {devices.map((d) => (
          <EntryRow
            key={d.id}
            d={d}
            selectable={canWrite}
            checked={selected.has(d.id)}
            onCheck={(on) => toggleSelected(d.id, on)}
            onOpen={() => setDetailRid(d.rustdesk_id)}
            onEdit={() => openEdit(d, book)}
            onDelete={() => setConfirmDel(d)}
          />
        ))}
      </div>
    );
  };

  const renderDiscovered = (allTab: boolean) => {
    if (discLoading && disc.length === 0) return <Loading text={t('dev.loadingDiscovered')} />;
    if (discFailed && disc.length === 0) return <LoadError onRetry={() => { void load(); }} />;
    if (disc.length === 0) {
      if (allTab) {
        return (
          <p className="rounded-lg border border-dashed border-slate-300 px-3 py-5 text-center text-xs text-slate-500 dark:text-slate-400 dark:border-slate-700">
            {q !== '' || discStatus !== 'all'
              ? t('dev.noDiscoveredMatch')
              : t('dev.noDiscoveredOutside')}
          </p>
        );
      }
      return (
        <div className="rounded-lg border border-dashed border-slate-300 px-4 py-10 text-center text-sm text-slate-500 dark:text-slate-400 dark:border-slate-700">
          <p className="font-medium text-slate-600 dark:text-slate-300">
            {q !== '' || discStatus !== 'all'
              ? t('dev.noDiscoveredMatch')
              : t('dev.noDevicesConnected')}
          </p>
          <p className="mx-auto mt-2 max-w-lg text-xs">
            {t('dev.discoveryExplainer')}
          </p>
          {(q !== '' || discStatus !== 'all') && (
            <button onClick={clearAll} className={`${btnGhost} mt-3`}>{t('dev.clearFilters')}</button>
          )}
        </div>
      );
    }
    return (
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        {disc.map((d) => (
          <DiscoveredRow
            key={d.rustdesk_id}
            d={d}
            onOpen={() => setDetailRid(d.rustdesk_id)}
            onAdd={() => setAddTarget(d)}
            canAdd={writableBooks.length > 0}
          />
        ))}
      </div>
    );
  };

  return (
    <Layout dark={dark} onTheme={toggle}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h1 className="text-xl font-bold">{t('dev.title')}</h1>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('dev.subtitle')}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {bookMeta
              ? `${t('dev.stats', { online: bookMeta.online, offline: bookMeta.offline })}${bookMeta.unknown ? t('dev.statsUnknown', { n: bookMeta.unknown }) : ''}`
              : t('dev.stats', { online: stats.online, offline: stats.offline })}
            {stats.discovered > 0 && t('dev.statsDiscovered', { online: stats.discovered_online, total: stats.discovered })}
          </span>
          {tab !== 'discovered' && canWrite && (
            <button className={btn} onClick={openCreate}>{t('dev.add')}</button>
          )}
        </div>
      </div>

      <div className="mb-3 flex gap-1 overflow-x-auto rounded-lg border border-slate-200 bg-white p-1 dark:border-slate-800 dark:bg-slate-900">
        <TabButton active={tab === 'all'} onClick={() => setTab('all')}>{t('dev.tabAll')}</TabButton>
        <TabButton active={tab === 'book'} onClick={() => setTab('book')} count={bookMeta?.devices}>
          {t('dev.tabBook')}
        </TabButton>
        <TabButton active={tab === 'discovered'} onClick={() => setTab('discovered')} count={stats.discovered}>
          {t('dev.tabDiscovered')}
        </TabButton>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        {tab !== 'discovered' && (
          <select aria-label={t('dev.selectBook')} value={book} onChange={(e) => setBook(e.target.value)} className={`${input} max-w-full sm:w-auto`}>
            {books.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}{b.rule < 2 ? t('dev.readOnly') : ''}
              </option>
            ))}
          </select>
        )}
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('dev.searchPlaceholder')}
          className={`${input} w-full sm:max-w-xs`}
        />
        {tab !== 'discovered' && (
          <>
            <select aria-label={t('dev.sortLabel')} value={sort} onChange={(e) => setSort(e.target.value)} className={`${input} sm:w-auto`} title={t('dev.sortTitle')}>
              <option value="status">{t('dev.sortStatus')}</option>
              <option value="alias">{t('dev.sortAlias')}</option>
              <option value="rustdesk_id">{t('dev.sortId')}</option>
              <option value="last_seen">{t('dev.sortLastSeen')}</option>
            </select>
            <select aria-label={t('dev.presenceFilter')} value={presence} onChange={(e) => setPresence(e.target.value)} className={`${input} sm:w-auto`}>
              <option value="">{t('dev.allStates')}</option>
              <option value="online">{t('dev.online')}</option>
              <option value="offline">{t('dev.offline')}</option>
              <option value="unknown">{t('dev.unknown')}</option>
            </select>
          </>
        )}
        {tab !== 'book' && (
          <select aria-label={t('dev.discoveryStatus')} value={discStatus} onChange={(e) => setDiscStatus(e.target.value as DiscStatus)} className={`${input} sm:w-auto`}>
            <option value="all">{t('dev.allDiscovered')}</option>
            <option value="online">{t('dev.discoveredOnline')}</option>
            <option value="offline">{t('dev.discoveredOffline')}</option>
          </select>
        )}
        {filtersActive && <button onClick={clearAll} className={btnGhost}>{t('dev.clearFilters')}</button>}
      </div>

      {tab !== 'discovered' && (
        <div className="mb-3 flex flex-wrap items-center gap-1.5">
          <button
            onClick={() => setSelTags([])}
            className={`rounded-full px-2.5 py-0.5 text-xs ${selTags.length === 0 ? 'bg-slate-800 text-white dark:bg-slate-200 dark:text-slate-900' : 'bg-slate-200 text-slate-800 dark:bg-slate-700 dark:text-slate-200'}`}
          >
            {t('dev.allTags')}
          </button>
          {tags.map((tag) => {
            const on = selTags.includes(tag.name);
            return (
              <button
                key={tag.id}
                onClick={() => setSelTags((list) => (list.includes(tag.name) ? list.filter((x) => x !== tag.name) : [...list, tag.name]))}
                title={t('dev.tagDevices', { n: tag.devices })}
                className={`rounded-full px-2.5 py-0.5 text-xs ${on ? 'ring-2 ring-slate-500 ring-offset-1' : 'hover:ring-2 hover:ring-slate-400'}`}
                style={{ backgroundColor: colorCss(tag.color), color: textOnColor(colorCss(tag.color)) }}
              >
                {tag.name}
              </button>
            );
          })}
          {selTags.length > 1 && (
            <button onClick={() => setMode(mode === 'and' ? 'or' : 'and')} className={btnGhost} title={t('dev.matchMode')}>
              {mode.toUpperCase()}
            </button>
          )}
        </div>
      )}

      {failed && devices.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          {t('dev.refreshFailed')}
          <button onClick={() => { void load(); }} className="underline">{t('common.retry')}</button>
        </div>
      )}
      {discFailed && disc.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          {t('dev.discoveryRefreshFailed')}
          <button onClick={() => { void load(); }} className="underline">{t('common.retry')}</button>
        </div>
      )}

      {showEntries && (
        <section className={showDisc ? 'mb-6' : ''}>
          <SectionHeader
            title={t('dev.sectionBook')}
            subtitle={bookMeta ? `${bookMeta.name}${bookMeta.rule < 2 ? t('dev.sectionBookReadOnly') : ''}` : undefined}
            right={loading && devices.length > 0 ? <span className="text-xs text-slate-500 dark:text-slate-400">{t('dev.updating')}</span> : undefined}
          />
          {renderEntries()}
          <div className="mt-3 flex justify-end">
            <Pagination page={page} total={total} size={SIZE} onPage={setPage} />
          </div>
        </section>
      )}

      {showDisc && (
        <section>
          <SectionHeader
            title={tab === 'all' ? t('dev.discoveredNotInBooks') : t('dev.discoveredDevices')}
            subtitle={
              tab === 'all'
                ? t('dev.discoveredSubtitleAll')
                : t('dev.discoveredSubtitle')
            }
            right={discLoading && disc.length > 0 ? <span className="text-xs text-slate-500 dark:text-slate-400">{t('dev.updating')}</span> : undefined}
          />
          {disc.length > 0 && (
            <div className="mb-2 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-200">
              {t('dev.discoveryNote')}
            </div>
          )}
          {renderDiscovered(tab === 'all')}
          <div className="mt-3 flex justify-end">
            <Pagination page={discPage} total={discTotal} size={SIZE} onPage={setDiscPage} />
          </div>
        </section>
      )}

      {selected.size > 0 && tab !== 'discovered' && (
        <div className="sticky bottom-2 z-20 mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-blue-200 bg-white/95 px-3 py-2 shadow-lg backdrop-blur dark:border-blue-900 dark:bg-slate-900/95">
          <span className="text-sm font-medium">{t('dev.selected', { n: selected.size })}</span>
          <button className={btnGhost} onClick={() => setBulkTagOpen(true)}>{t('dev.addRemoveTags')}</button>
          <button className={btnDanger} onClick={() => setBulkDeleteOpen(true)}>{t('common.delete')}</button>
          <button className={`${btnGhost} ml-auto`} onClick={() => setSelected(new Set())}>{t('dev.clearSelection')}</button>
        </div>
      )}

      {detailRid && (
        <DetailDrawer
          rid={detailRid}
          reloadToken={detailReload}
          isAdmin={isAdmin}
          canWriteBook={canWriteBook}
          canAddToBook={writableBooks.length > 0}
          onClose={() => setDetailRid(null)}
          onChanged={refreshAll}
          onEdit={(d, bookId) => openEdit(d, bookId)}
          onAddToBook={(d) => setAddTarget(d)}
        />
      )}

      {editing && (
        <DeviceForm
          book={formBook}
          initial={editing === 'new' ? null : editing}
          tags={formTags}
          tagsReady={formTagsReady}
          onClose={() => setEditing(null)}
          onSaved={(msg) => {
            const wasEdit = editing !== 'new';
            setEditing(null);
            notify(true, msg);
            refreshAll();
            if (wasEdit) setDetailReload((v) => v + 1);
          }}
          onError={(m) => notify(false, m)}
        />
      )}

      {confirmDel && (
        <Confirm
          text={t('dev.removeConfirm', { name: confirmDel.alias || confirmDel.hostname || confirmDel.rustdesk_id })}
          yesLabel={t('common.remove')}
          busy={busy}
          onYes={() => { void doDelete(); }}
          onNo={() => setConfirmDel(null)}
        />
      )}
      {bulkDeleteOpen && (
        <Confirm
          text={t('dev.bulkDeleteConfirm', { n: selected.size })}
          busy={busy}
          onYes={() => { void doBulkDelete(); }}
          onNo={() => setBulkDeleteOpen(false)}
        />
      )}
      {bulkTagOpen && (
        <BulkTagModal
          count={selected.size}
          tags={tags}
          onClose={() => setBulkTagOpen(false)}
          onApply={applyBulkTags}
        />
      )}
      {addTarget && (
        <AddDiscoveredModal
          device={addTarget}
          books={writableBooks}
          defaultBook={book}
          onClose={() => setAddTarget(null)}
          onSaved={(d) => {
            setAddTarget(null);
            notify(true, t('dev.addedToBook', { id: d.rustdesk_id }));
            setDetailReload((v) => v + 1);
            refreshAll();
          }}
        />
      )}
    </Layout>
  );
}
