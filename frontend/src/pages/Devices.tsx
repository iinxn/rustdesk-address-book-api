import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, sessionUser } from '../api';
import {
  Badge, Checkbox, Confirm, Field, Layout, LoadError, Loading, Modal, Pagination,
  StatusDot, TagBadge, btn, btnDanger, btnGhost, btnGhostDanger, input,
  statusLabel,
} from '../components';
import { useDebounce, useTheme } from '../hooks';
import { useI18n } from '../i18n';
import type { Lang, TKey } from '../i18n';
import { useNotify } from '../notifications';
import { colorCss, parseUtc, relTime, textOnColor } from '../types';
import type {
  Book, Device, DeviceDetail, DeviceDetailEntry, DeviceInfo, DiscoveredDevice,
  Presence, Stats, TagRow,
} from '../types';

const SIZE = 50;
type Tab = 'all' | 'book' | 'discovered';
type DiscStatus = 'all' | 'online' | 'offline';
type TFn = (key: TKey, vars?: Record<string, string | number>) => string;

const emptyStats: Stats = {
  devices: 0, online: 0, offline: 0, unknown: 0, discovered: 0, discovered_online: 0,
};

function absTime(iso: string | null, lang: Lang): string {
  return iso ? parseUtc(iso).toLocaleString(lang === 'ru' ? 'ru-RU' : 'en-US') : '';
}

function lastSeenText(iso: string | null, lang: Lang): string {
  return iso ? `${absTime(iso, lang)} (${relTime(iso, lang)})` : '';
}

function sourceLabel(source: string): string {
  if (!source) return '';
  return source.split(',').map((s) => (s === 'tcp' ? 'TCP' : s === 'udp' ? 'UDP' : s)).join(' + ');
}

function freshness(info: DeviceInfo | null, t: TFn, lang: Lang): { tone: 'green' | 'amber' | 'slate'; label: string; title: string } {
  if (!info || !info.collected_at) {
    return {
      tone: 'slate',
      label: t('dev.freshNo'),
      title: t('dev.freshNoTitle'),
    };
  }
  const age = Date.now() - parseUtc(info.collected_at).getTime();
  if (age > 24 * 60 * 60 * 1000) {
    return { tone: 'amber', label: t('dev.freshStale'), title: t('dev.lastUploaded', { time: absTime(info.collected_at, lang) }) };
  }
  return { tone: 'green', label: t('dev.freshFresh'), title: t('dev.lastUploaded', { time: absTime(info.collected_at, lang) }) };
}

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
          ? api.entriesWithTags(book, { search: q, mode, presence, sort, page, page_size: SIZE }, selTags)
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

function TabButton({ active, onClick, count, children }: {
  active: boolean;
  onClick: () => void;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm ${
        active
          ? 'bg-blue-600 text-white'
          : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
      }`}
    >
      {children}
      {count !== undefined && (
        <span className={`ml-1.5 rounded-full px-1.5 py-0.5 text-[11px] ${
          active ? 'bg-blue-700 text-white' : 'bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300'
        }`}>
          {count}
        </span>
      )}
    </button>
  );
}

function SectionHeader({ title, subtitle, right }: {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
}) {
  return (
    <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
      <div>
        <h2 className="text-sm font-semibold">{title}</h2>
        {subtitle && <p className="text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

function EntryRow({ d, selectable, checked, onCheck, onOpen, onEdit, onDelete }: {
  d: Device;
  selectable: boolean;
  checked: boolean;
  onCheck: (on: boolean) => void;
  onOpen: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { t, lang } = useI18n();
  const name = d.alias || d.hostname || d.rustdesk_id;
  const meta = [d.os || d.platform, d.ip].filter(Boolean).join(' · ');
  return (
    <div className="flex items-start gap-2 border-b border-slate-100 px-2 py-2.5 last:border-0 sm:gap-3 sm:px-3 dark:border-slate-800">
      {selectable && (
        <div className="pt-1">
          <Checkbox checked={checked} onChange={onCheck} label={t('dev.selectOne', { name })} />
        </div>
      )}
      <button onClick={onOpen} className="flex min-w-0 flex-1 items-start gap-2 text-left sm:gap-3">
        <span className="mt-1.5 shrink-0"><StatusDot p={d.presence} lastSeen={d.last_seen} /></span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="truncate font-medium">{name}</span>
            {d.hostname && d.hostname !== name && (
              <span className="truncate text-xs text-slate-500 dark:text-slate-400">{d.hostname}</span>
            )}
            {d.has_info && <Badge tone="blue" title={t('dev.infoBadgeTitle')}>{t('dev.infoBadge')}</Badge>}
          </span>
          <span className="block font-mono text-xs text-slate-500 dark:text-slate-400">{d.rustdesk_id}</span>
          <span className="block truncate text-xs text-slate-500 dark:text-slate-400">
            {meta || t('dev.osIpNotReported')}
          </span>
          {d.tag_objs.length > 0 && (
            <span className="mt-1 flex flex-wrap gap-1">
              {d.tag_objs.map((tag) => <TagBadge key={tag.id} name={tag.name} color={tag.color} />)}
            </span>
          )}
          <span className="block text-xs text-slate-500 dark:text-slate-400" title={d.last_seen || undefined}>
            {statusLabel(d.presence, d.last_seen, lang)}
          </span>
        </span>
      </button>
      {selectable && (
        <div className="hidden shrink-0 gap-1 sm:flex">
          <button className={btnGhost} onClick={onEdit}>{t('common.edit')}</button>
          <button className={btnGhostDanger} onClick={onDelete}>{t('common.delete')}</button>
        </div>
      )}
    </div>
  );
}

function DiscoveredRow({ d, onOpen, onAdd, canAdd }: {
  d: DiscoveredDevice;
  onOpen: () => void;
  onAdd: () => void;
  canAdd: boolean;
}) {
  const { t, lang } = useI18n();
  const info = d.info;
  const name = info?.hostname || d.rustdesk_id;
  const p: Presence = d.online ? 'online' : 'offline';
  const meta = [
    info?.os_name || info?.os,
    info?.version ? `v${info.version}` : '',
    d.last_ip,
  ].filter(Boolean).join(' · ');
  return (
    <div className="flex flex-wrap items-start gap-2 border-b border-slate-100 px-3 py-2.5 last:border-0 sm:flex-nowrap dark:border-slate-800">
      <span className="mt-1.5"><StatusDot p={p} lastSeen={d.last_seen} /></span>
      <button onClick={onOpen} className="min-w-0 flex-1 text-left">
        <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="truncate font-medium">{name}</span>
          {info?.username && <span className="text-xs text-slate-500 dark:text-slate-400">@{info.username}</span>}
          {!info && (
            <Badge tone="amber" title={t('dev.noSysinfoTitle')}>
              {t('dev.noSysinfo')}
            </Badge>
          )}
        </span>
        <span className="block font-mono text-xs text-slate-500 dark:text-slate-400">{d.rustdesk_id}</span>
        <span className="block truncate text-xs text-slate-500 dark:text-slate-400">
          {meta || t('dev.osVersionIpNotReported')}
        </span>
        <span className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-slate-500 dark:text-slate-400">
          <span>{statusLabel(p, d.last_seen, lang)}</span>
          <span>{t('dev.firstSeenVia', { time: relTime(d.first_seen, lang) })}</span>
          {d.source && <span>{t('dev.via', { source: sourceLabel(d.source) })}</span>}
        </span>
        {d.in_books.length > 0 && (
          <span className="mt-1 block text-xs text-green-700 dark:text-green-400">
            {t('dev.inBook', { books: d.in_books.map((b) => b.name).join(', ') })}
          </span>
        )}
      </button>
      {d.in_books.length === 0 && canAdd && (
        <button className={`${btn} shrink-0`} onClick={onAdd}>{t('dev.addToBook')}</button>
      )}
    </div>
  );
}

function DetailDrawer({
  rid, reloadToken, isAdmin, canWriteBook, canAddToBook,
  onClose, onChanged, onEdit, onAddToBook,
}: {
  rid: string;
  reloadToken: number;
  isAdmin: boolean;
  canWriteBook: (bookId: string) => boolean;
  canAddToBook: boolean;
  onClose: () => void;
  onChanged: () => void;
  onEdit: (d: Device, bookId: string) => void;
  onAddToBook: (d: DiscoveredDevice) => void;
}) {
  const { t, lang } = useI18n();
  const { notify } = useNotify();
  const [data, setData] = useState<DeviceDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [delEntry, setDelEntry] = useState<Device | null>(null);
  const [forgetOpen, setForgetOpen] = useState(false);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const next = await api.deviceInfo(rid);
      setData(next);
      setError('');
    } catch (e) {
      if (!silent) setError(String((e as Error).message));
    } finally {
      if (!silent) setLoading(false);
    }
  }, [rid]);

  useEffect(() => { void load(); }, [load, reloadToken]);
  useEffect(() => {
    const timer = window.setInterval(() => { void load(true); }, 15000);
    return () => window.clearInterval(timer);
  }, [load]);

  const info = data?.info ?? null;
  const disc = data?.discovered ?? null;
  const entries = data?.entries ?? [];
  const primary = entries[0];
  const name = info?.hostname || primary?.alias || rid;
  const presence: Presence = data?.online ? 'online' : data?.last_seen ? 'offline' : 'unknown';
  const fresh = freshness(info, t, lang);

  const refresh = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.refreshInfo(rid);
      notify(
        true,
        data?.online
          ? t('dev.refreshOnline')
          : t('dev.refreshOffline'),
      );
      window.setTimeout(() => { void load(true); }, 8000);
    } catch (e) {
      notify(false, String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const removeEntry = async () => {
    if (!delEntry || busy) return;
    setBusy(true);
    try {
      await api.deleteEntry(delEntry.id);
      notify(true, t('dev.removedFromBook'));
      // Without a discovery row a non-admin can no longer open this card;
      // close it instead of leaving stale data on screen.
      const wasLastSource = entries.length === 1 && !disc;
      setDelEntry(null);
      onChanged();
      if (wasLastSource) onClose();
      else void load(true);
    } catch (e) {
      notify(false, String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const forget = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.forgetDiscovered(rid);
      notify(true, t('dev.discoveryRemoved'));
      setForgetOpen(false);
      onChanged();
      onClose();
    } catch (e) {
      notify(false, String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const cores = info
    ? (info.cpu_logical && info.cpu_physical
      ? t('dev.coresBoth', { logical: info.cpu_logical, physical: info.cpu_physical })
      : info.cpu_logical
        ? t('dev.coresLogical', { n: info.cpu_logical })
        : info.cpu_physical
          ? t('dev.coresPhysical', { n: info.cpu_physical })
          : '')
    : '';

  return (
    <>
      <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={onClose} role="presentation">
        <div
          className="flex h-full w-full max-w-xl flex-col overflow-y-auto bg-white text-slate-900 shadow-xl dark:bg-slate-900 dark:text-slate-100"
          onClick={(e) => e.stopPropagation()}
          role="dialog"
          aria-modal="true"
          aria-label={t('dev.device', { id: rid })}
        >
          <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-slate-200 bg-white px-5 py-4 dark:border-slate-800 dark:bg-slate-900">
            <div className="min-w-0">
              <h2 className="truncate text-lg font-bold">{name}</h2>
              <p className="font-mono text-xs text-slate-500 dark:text-slate-400">{rid}</p>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <span className="inline-flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
                  <StatusDot p={presence} lastSeen={data?.last_seen ?? null} />
                  {statusLabel(presence, data?.last_seen ?? null, lang)}
                </span>
                {data?.sources.includes('address_book') && <Badge tone="slate">{t('dev.sectionBook')}</Badge>}
                {data?.sources.includes('discovery') && <Badge tone="green">{t('dev.tabDiscovered')}</Badge>}
                {data?.sources.includes('sysinfo') && <Badge tone="blue">{t('dev.clientReport')}</Badge>}
              </div>
            </div>
            <button
              onClick={onClose}
              aria-label={t('common.close')}
              className="rounded border border-slate-200 px-2 py-0.5 text-sm text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
            >
              ✕
            </button>
          </div>

          <div className="flex-1 space-y-5 px-5 py-4">
            {error && (
              <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
                {error}
                <button onClick={() => { void load(); }} className="ml-2 underline">{t('common.retry')}</button>
              </div>
            )}
            {!data && loading && <Loading text={t('dev.loadingDevice')} />}
            {!data && !loading && !error && <p className="text-sm text-slate-500 dark:text-slate-400">{t('dev.noData')}</p>}

            {data && (
              <>
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{t('dev.connection')}</h3>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
                    <Field label={t('dev.status')} value={statusLabel(presence, data.last_seen, lang)} />
                    <Field label={t('dev.lastSeen')} value={lastSeenText(data.last_seen, lang)} />
                    <Field label={t('dev.ip')} value={data.last_ip} mono />
                    <Field
                      label={t('dev.detectedVia')}
                      value={disc ? sourceLabel(disc.source) : ''}
                      fallback={entries.length > 0 ? t('dev.addressBookHeartbeat') : t('dev.notAvailable')}
                    />
                    <Field label={t('dev.firstSeen')} value={disc?.first_seen ? absTime(disc.first_seen, lang) : ''} />
                    <Field label={t('dev.lastConnected')} value={disc?.last_connected ? absTime(disc.last_connected, lang) : ''} />
                    <Field label={t('dev.lastDisconnected')} value={disc?.last_disconnected ? absTime(disc.last_disconnected, lang) : ''} />
                    <Field
                      label={t('dev.addressBooks')}
                      value={entries.map((e) => e.book_name).join(', ')}
                      fallback={t('dev.notInVisibleBook')}
                    />
                  </dl>
                </section>

                <section>
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{t('dev.system')}</h3>
                    <Badge tone={fresh.tone} title={fresh.title}>{fresh.label}</Badge>
                  </div>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
                    <Field label={t('dev.hostname')} value={info?.hostname || primary?.hostname || ''} />
                    <Field label={t('dev.username')} value={info?.username || primary?.username || ''} />
                    <Field label={t('dev.operatingSystem')} value={info?.os || primary?.platform || ''} />
                    <Field label={t('dev.osFamily')} value={info?.os_name || ''} />
                    <Field label={t('dev.osVersion')} value={info?.os_version || ''} />
                    <Field label={t('dev.clientVersion')} value={info?.version || ''} />
                    <Field label={t('dev.reportUploaded')} value={info?.collected_at ? lastSeenText(info.collected_at, lang) : ''} />
                    <Field
                      label={t('dev.lastHeartbeat')}
                      value={info?.last_heartbeat_at ? lastSeenText(info.last_heartbeat_at, lang) : ''}
                      fallback={t('dev.noHeartbeat')}
                    />
                  </dl>
                </section>

                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{t('dev.hardware')}</h3>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
                    <Field label={t('dev.cpu')} value={info?.cpu_model || info?.cpu || ''} hint={info?.cpu} />
                    <Field label={t('dev.frequency')} value={info?.cpu_freq_ghz ? `${info.cpu_freq_ghz} GHz` : ''} />
                    <Field label={t('dev.cores')} value={cores} />
                    <Field
                      label={t('dev.totalRam')}
                      value={info?.memory_gb ? `${info.memory_gb} GB` : info?.memory || ''}
                    />
                  </dl>
                </section>

                <div className="rounded-lg border border-dashed border-slate-300 p-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
                  <div className="mb-1 font-medium text-slate-600 dark:text-slate-300">
                    {t('dev.notProvidedTitle')}
                  </div>
                  <div className="mb-2 flex flex-wrap gap-1">
                    {[t('dev.fieldArchitecture'), t('dev.fieldRamUsage'), t('dev.fieldGpu'), t('dev.fieldDisks'), t('dev.fieldNetwork')].map((x) => (
                      <Badge key={x} tone="slate">{x}</Badge>
                    ))}
                  </div>
                  {t('dev.notProvidedNote')}
                </div>

                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{t('dev.sectionBook')}</h3>
                  {entries.length === 0 ? (
                    <p className="text-sm text-slate-500 dark:text-slate-400">{t('dev.notInVisibleBook')}</p>
                  ) : (
                    <div className="space-y-2">
                      {entries.map((e: DeviceDetailEntry) => (
                        <div key={e.id} className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <div className="min-w-0">
                              <div className="truncate font-medium">{e.alias || e.rustdesk_id}</div>
                              <div className="text-xs text-slate-500 dark:text-slate-400">
                                {e.book_name} · {statusLabel(e.presence, e.last_seen, lang)}
                              </div>
                              {e.tag_objs.length > 0 && (
                                <div className="mt-1 flex flex-wrap gap-1">
                                  {e.tag_objs.map((tag) => <TagBadge key={tag.id} name={tag.name} color={tag.color} />)}
                                </div>
                              )}
                            </div>
                            <div className="flex gap-1">
                              <button
                                className={btnGhost}
                                onClick={() => onEdit(e, e.book_id)}
                                disabled={!canWriteBook(e.book_id)}
                              >
                                {t('common.edit')}
                              </button>
                              <button
                                className={btnGhostDanger}
                                onClick={() => setDelEntry(e)}
                                disabled={!canWriteBook(e.book_id)}
                              >
                                {t('common.delete')}
                              </button>
                            </div>
                          </div>
                          {e.note && (
                            <p className="mt-2 whitespace-pre-wrap text-xs text-slate-500 dark:text-slate-400">{e.note}</p>
                          )}
                          <div className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                            {e.password_configured ? t('dev.storedPassword') : t('dev.noStoredPassword')}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </section>
              </>
            )}
          </div>

          <div className="sticky bottom-0 flex flex-wrap gap-2 border-t border-slate-200 bg-white px-5 py-3 dark:border-slate-800 dark:bg-slate-900">
            <button className={btn} onClick={() => { void refresh(); }} disabled={busy || !data}>
              {busy ? t('common.working') : t('dev.refreshInfo')}
            </button>
            {disc && disc.in_books.length === 0 && (
              <button
                className={btnGhost}
                onClick={() => onAddToBook(disc)}
                disabled={!canAddToBook}
                title={canAddToBook ? undefined : t('dev.noWritableBooks')}
              >
                {t('dev.addToBook')}
              </button>
            )}
            {isAdmin && disc && (
              <button className={btnGhostDanger} onClick={() => setForgetOpen(true)}>{t('dev.forget')}</button>
            )}
            <button className={`${btnGhost} ml-auto`} onClick={onClose}>{t('common.close')}</button>
          </div>
        </div>
      </div>

      {delEntry && (
        <Confirm
          text={t('dev.removeConfirm', { name: delEntry.alias || delEntry.rustdesk_id })}
          yesLabel={t('common.remove')}
          busy={busy}
          onYes={() => { void removeEntry(); }}
          onNo={() => setDelEntry(null)}
        />
      )}
      {forgetOpen && (
        <Confirm
          text={t('dev.forgetConfirm', { id: rid })}
          yesLabel={t('dev.forget')}
          busy={busy}
          onYes={() => { void forget(); }}
          onNo={() => setForgetOpen(false)}
        />
      )}
    </>
  );
}

function AddDiscoveredModal({ device, books, defaultBook, onClose, onSaved }: {
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

function BulkTagModal({ count, tags, onClose, onApply }: {
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

function DeviceForm({ book, initial, tags, tagsReady = true, onClose, onSaved, onError }: {
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
