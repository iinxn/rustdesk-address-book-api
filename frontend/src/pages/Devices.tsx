import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, sessionUser } from '../api';
import {
  Badge, Checkbox, Confirm, Field, Layout, LoadError, Loading, Modal, Pagination,
  StatusDot, TagBadge, Toasts, btn, btnDanger, btnGhost, btnGhostDanger, input,
  statusLabel,
} from '../components';
import { useDebounce, useTheme, useToasts } from '../hooks';
import { colorCss, parseUtc, relTime, textOnColor } from '../types';
import type {
  Book, Device, DeviceDetail, DeviceDetailEntry, DeviceInfo, DiscoveredDevice,
  Presence, Stats, TagRow,
} from '../types';

const SIZE = 50;
type Tab = 'all' | 'book' | 'discovered';
type DiscStatus = 'all' | 'online' | 'offline';

const emptyStats: Stats = {
  devices: 0, online: 0, offline: 0, unknown: 0, discovered: 0, discovered_online: 0,
};

function absTime(iso: string | null): string {
  return iso ? parseUtc(iso).toLocaleString() : '';
}

function lastSeenText(iso: string | null): string {
  return iso ? `${absTime(iso)} (${relTime(iso)})` : '';
}

function sourceLabel(source: string): string {
  if (!source) return '';
  return source.split(',').map((s) => (s === 'tcp' ? 'TCP' : s === 'udp' ? 'UDP' : s)).join(' + ');
}

function freshness(info: DeviceInfo | null): { tone: 'green' | 'amber' | 'slate'; label: string; title: string } {
  if (!info || !info.collected_at) {
    return {
      tone: 'slate',
      label: 'No system report',
      title: 'This client has not uploaded system information.',
    };
  }
  const age = Date.now() - parseUtc(info.collected_at).getTime();
  if (age > 24 * 60 * 60 * 1000) {
    return { tone: 'amber', label: 'Stale report', title: `Last uploaded ${absTime(info.collected_at)}` };
  }
  return { tone: 'green', label: 'Fresh report', title: `Last uploaded ${absTime(info.collected_at)}` };
}

export default function Devices() {
  const { dark, toggle } = useTheme();
  const { items: toasts, push } = useToasts();
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
    if (!book) { push(false, 'Select an address book first'); return; }
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
      push(true, 'Removed from address book');
      setConfirmDel(null);
      refreshAll();
    } catch (e) {
      push(false, String((e as Error).message));
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
        push(true, `Deleted ${result.deleted.length} device${result.deleted.length === 1 ? '' : 's'}`);
      }
      if (result.failed.length > 0) {
        push(false, `${result.failed.length} device${result.failed.length === 1 ? '' : 's'} could not be deleted (permission or already gone)`);
      }
      setBulkDeleteOpen(false);
      setSelected(new Set(result.failed.map((f) => f.id)));
      refreshAll();
    } catch (e) {
      push(false, String((e as Error).message));
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
        push(true, `Updated tags on ${result.updated.length} device${result.updated.length === 1 ? '' : 's'}`);
      }
      if (result.failed.length > 0) {
        push(false, `${result.failed.length} device${result.failed.length === 1 ? '' : 's'} were not updated (permission or already gone)`);
      }
      setSelected(new Set(result.failed.map((f) => f.id)));
      refreshAll();
    } finally {
      setBusy(false);
    }
  };

  const renderEntries = () => {
    if (loading && devices.length === 0) return <Loading text="Loading devices" />;
    if (failed && devices.length === 0) return <LoadError onRetry={() => { void load(); }} />;
    if (devices.length === 0) {
      return (
        <div className="rounded-lg border border-dashed border-slate-300 py-10 text-center text-sm text-slate-500 dark:text-slate-400 dark:border-slate-700">
          {entryFiltersActive ? (
            <>
              No devices match the current filters.
              <br />
              <button onClick={clearAll} className={`${btnGhost} mt-2`}>Clear filters</button>
            </>
          ) : (
            <>
              This address book is empty.
              {canWrite && (
                <>
                  <br />
                  <button onClick={openCreate} className={`${btn} mt-2`}>Add your first device</button>
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
              label="Select all devices on this page"
            />
            <span className="font-medium">Select all on this page</span>
            {someOnPage && <span className="ml-auto text-slate-500 dark:text-slate-400">{selected.size} selected</span>}
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
    if (discLoading && disc.length === 0) return <Loading text="Loading discovered devices" />;
    if (discFailed && disc.length === 0) return <LoadError onRetry={() => { void load(); }} />;
    if (disc.length === 0) {
      if (allTab) {
        return (
          <p className="rounded-lg border border-dashed border-slate-300 px-3 py-5 text-center text-xs text-slate-500 dark:text-slate-400 dark:border-slate-700">
            {q !== '' || discStatus !== 'all'
              ? 'No discovered devices match the current filters.'
              : 'No discovered devices outside your address books. Devices seen by the server but already in a visible book are hidden here.'}
          </p>
        );
      }
      return (
        <div className="rounded-lg border border-dashed border-slate-300 px-4 py-10 text-center text-sm text-slate-500 dark:text-slate-400 dark:border-slate-700">
          <p className="font-medium text-slate-600 dark:text-slate-300">
            {q !== '' || discStatus !== 'all'
              ? 'No discovered devices match the current filters.'
              : 'No devices have connected to this server yet.'}
          </p>
          <p className="mx-auto mt-2 max-w-lg text-xs">
            Discovery uses the RustDesk rendezvous connection seen by the server.
            Clients do not need an API address for this part. System details appear
            only when a client also uploads them to the API.
          </p>
          {(q !== '' || discStatus !== 'all') && (
            <button onClick={clearAll} className={`${btnGhost} mt-3`}>Clear filters</button>
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
          <h1 className="text-xl font-bold">Devices</h1>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Address books, server discovery and client-reported system details.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {bookMeta
              ? `${bookMeta.online} online · ${bookMeta.offline} offline${bookMeta.unknown ? ` · ${bookMeta.unknown} unknown` : ''}`
              : `${stats.online} online · ${stats.offline} offline`}
            {stats.discovered > 0 && ` · discovered ${stats.discovered_online}/${stats.discovered}`}
          </span>
          {tab !== 'discovered' && canWrite && (
            <button className={btn} onClick={openCreate}>+ Add device</button>
          )}
        </div>
      </div>

      <div className="mb-3 flex gap-1 overflow-x-auto rounded-lg border border-slate-200 bg-white p-1 dark:border-slate-800 dark:bg-slate-900">
        <TabButton active={tab === 'all'} onClick={() => setTab('all')}>All devices</TabButton>
        <TabButton active={tab === 'book'} onClick={() => setTab('book')} count={bookMeta?.devices}>
          Address book
        </TabButton>
        <TabButton active={tab === 'discovered'} onClick={() => setTab('discovered')} count={stats.discovered}>
          Discovered
        </TabButton>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        {tab !== 'discovered' && (
          <select aria-label="Address book" value={book} onChange={(e) => setBook(e.target.value)} className={`${input} max-w-full sm:w-auto`}>
            {books.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}{b.rule < 2 ? ' (read-only)' : ''}
              </option>
            ))}
          </select>
        )}
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search ID, hostname, user, note…"
          className={`${input} w-full sm:max-w-xs`}
        />
        {tab !== 'discovered' && (
          <>
            <select aria-label="Sort devices" value={sort} onChange={(e) => setSort(e.target.value)} className={`${input} sm:w-auto`} title="Sort">
              <option value="status">Status + Alias</option>
              <option value="alias">Alias</option>
              <option value="rustdesk_id">RustDesk ID</option>
              <option value="last_seen">Last seen</option>
            </select>
            <select aria-label="Presence filter" value={presence} onChange={(e) => setPresence(e.target.value)} className={`${input} sm:w-auto`}>
              <option value="">All states</option>
              <option value="online">Online</option>
              <option value="offline">Offline</option>
              <option value="unknown">Unknown</option>
            </select>
          </>
        )}
        {tab !== 'book' && (
          <select aria-label="Discovery status" value={discStatus} onChange={(e) => setDiscStatus(e.target.value as DiscStatus)} className={`${input} sm:w-auto`}>
            <option value="all">All discovered</option>
            <option value="online">Discovered online</option>
            <option value="offline">Discovered offline</option>
          </select>
        )}
        {filtersActive && <button onClick={clearAll} className={btnGhost}>Clear filters</button>}
      </div>

      {tab !== 'discovered' && (
        <div className="mb-3 flex flex-wrap items-center gap-1.5">
          <button
            onClick={() => setSelTags([])}
            className={`rounded-full px-2.5 py-0.5 text-xs ${selTags.length === 0 ? 'bg-slate-800 text-white dark:bg-slate-200 dark:text-slate-900' : 'bg-slate-200 dark:bg-slate-700'}`}
          >
            All tags
          </button>
          {tags.map((t) => {
            const on = selTags.includes(t.name);
            return (
              <button
                key={t.id}
                onClick={() => setSelTags((list) => (list.includes(t.name) ? list.filter((x) => x !== t.name) : [...list, t.name]))}
                title={`${t.devices} device${t.devices === 1 ? '' : 's'}`}
                className={`rounded-full px-2.5 py-0.5 text-xs ${on ? 'ring-2 ring-slate-500 ring-offset-1' : 'hover:ring-2 hover:ring-slate-400'}`}
                style={{ backgroundColor: colorCss(t.color), color: textOnColor(colorCss(t.color)) }}
              >
                {t.name}
              </button>
            );
          })}
          {selTags.length > 1 && (
            <button onClick={() => setMode(mode === 'and' ? 'or' : 'and')} className={btnGhost} title="Match all selected tags or any of them">
              {mode.toUpperCase()}
            </button>
          )}
        </div>
      )}

      {failed && devices.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          Refresh failed — showing the previous result.
          <button onClick={() => { void load(); }} className="underline">Retry</button>
        </div>
      )}
      {discFailed && disc.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          Discovery refresh failed — showing the previous result.
          <button onClick={() => { void load(); }} className="underline">Retry</button>
        </div>
      )}

      {showEntries && (
        <section className={showDisc ? 'mb-6' : ''}>
          <SectionHeader
            title="Address book"
            subtitle={bookMeta ? `${bookMeta.name}${bookMeta.rule < 2 ? ' · read-only' : ''}` : undefined}
            right={loading && devices.length > 0 ? <span className="text-xs text-slate-400">Updating…</span> : undefined}
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
            title={tab === 'all' ? 'Discovered, not in your address books' : 'Discovered devices'}
            subtitle={
              tab === 'all'
                ? 'Seen by the RustDesk server but not linked to a visible address book.'
                : 'Rendezvous evidence from the server, including devices already in address books.'
            }
            right={discLoading && disc.length > 0 ? <span className="text-xs text-slate-400">Updating…</span> : undefined}
          />
          {disc.length > 0 && (
            <div className="mb-2 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-200">
              Discovery needs no client API setting. Hostname, OS and hardware details require a custom API server on the client.
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
          <span className="text-sm font-medium">{selected.size} selected</span>
          <button className={btnGhost} onClick={() => setBulkTagOpen(true)}>Add / remove tags</button>
          <button className={btnDanger} onClick={() => setBulkDeleteOpen(true)}>Delete</button>
          <button className={`${btnGhost} ml-auto`} onClick={() => setSelected(new Set())}>Clear selection</button>
        </div>
      )}

      {detailRid && (
        <DetailDrawer
          rid={detailRid}
          reloadToken={detailReload}
          isAdmin={isAdmin}
          canWriteBook={canWriteBook}
          canAddToBook={writableBooks.length > 0}
          notify={push}
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
            push(true, msg);
            refreshAll();
            if (wasEdit) setDetailReload((v) => v + 1);
          }}
          onError={(m) => push(false, m)}
        />
      )}

      {confirmDel && (
        <Confirm
          text={`Remove ${confirmDel.alias || confirmDel.hostname || confirmDel.rustdesk_id} from the address book? Tags themselves are not deleted.`}
          yesLabel="Remove"
          busy={busy}
          onYes={() => { void doDelete(); }}
          onNo={() => setConfirmDel(null)}
        />
      )}
      {bulkDeleteOpen && (
        <Confirm
          text={`Delete ${selected.size} selected device${selected.size === 1 ? '' : 's'} from the address book? Tags themselves are not deleted.`}
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
            push(true, `Added ${d.rustdesk_id} to the address book`);
            setDetailReload((v) => v + 1);
            refreshAll();
          }}
        />
      )}

      <Toasts items={toasts} />
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
  const name = d.alias || d.hostname || d.rustdesk_id;
  const meta = [d.os || d.platform, d.ip].filter(Boolean).join(' · ');
  return (
    <div className="flex items-start gap-2 border-b border-slate-100 px-2 py-2.5 last:border-0 sm:gap-3 sm:px-3 dark:border-slate-800">
      {selectable && (
        <div className="pt-1">
          <Checkbox checked={checked} onChange={onCheck} label={`Select ${name}`} />
        </div>
      )}
      <button onClick={onOpen} className="flex min-w-0 flex-1 items-start gap-2 text-left sm:gap-3">
        <span className="mt-1.5 shrink-0"><StatusDot p={d.presence} lastSeen={d.last_seen} /></span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
            <span className="truncate font-medium">{name}</span>
            {d.hostname && d.hostname !== name && (
              <span className="truncate text-xs text-slate-400">{d.hostname}</span>
            )}
            {d.has_info && <Badge tone="blue" title="The client uploaded system information">info</Badge>}
          </span>
          <span className="block font-mono text-xs text-slate-500 dark:text-slate-400">{d.rustdesk_id}</span>
          <span className="block truncate text-xs text-slate-500 dark:text-slate-400">
            {meta || 'OS and IP not reported'}
          </span>
          {d.tag_objs.length > 0 && (
            <span className="mt-1 flex flex-wrap gap-1">
              {d.tag_objs.map((t) => <TagBadge key={t.id} name={t.name} color={t.color} />)}
            </span>
          )}
          <span className="block text-xs text-slate-400" title={d.last_seen || undefined}>
            {statusLabel(d.presence, d.last_seen)}
          </span>
        </span>
      </button>
      {selectable && (
        <div className="hidden shrink-0 gap-1 sm:flex">
          <button className={btnGhost} onClick={onEdit}>Edit</button>
          <button className={btnGhostDanger} onClick={onDelete}>Delete</button>
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
          {info?.username && <span className="text-xs text-slate-400">@{info.username}</span>}
          {!info && (
            <Badge tone="amber" title="The client has not uploaded system information">
              no sysinfo
            </Badge>
          )}
        </span>
        <span className="block font-mono text-xs text-slate-500 dark:text-slate-400">{d.rustdesk_id}</span>
        <span className="block truncate text-xs text-slate-500 dark:text-slate-400">
          {meta || 'OS, client version and IP not reported'}
        </span>
        <span className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-slate-400">
          <span>{statusLabel(p, d.last_seen)}</span>
          <span>· first seen {relTime(d.first_seen)}</span>
          {d.source && <span>· via {sourceLabel(d.source)}</span>}
        </span>
        {d.in_books.length > 0 && (
          <span className="mt-1 block text-xs text-green-700 dark:text-green-400">
            In book: {d.in_books.map((b) => b.name).join(', ')}
          </span>
        )}
      </button>
      {d.in_books.length === 0 && canAdd && (
        <button className={`${btn} shrink-0`} onClick={onAdd}>Add to book</button>
      )}
    </div>
  );
}

function DetailDrawer({
  rid, reloadToken, isAdmin, canWriteBook, canAddToBook, notify,
  onClose, onChanged, onEdit, onAddToBook,
}: {
  rid: string;
  reloadToken: number;
  isAdmin: boolean;
  canWriteBook: (bookId: string) => boolean;
  canAddToBook: boolean;
  notify: (ok: boolean, text: string) => void;
  onClose: () => void;
  onChanged: () => void;
  onEdit: (d: Device, bookId: string) => void;
  onAddToBook: (d: DiscoveredDevice) => void;
}) {
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
  const fresh = freshness(info);

  const refresh = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.refreshInfo(rid);
      notify(
        true,
        data?.online
          ? 'Refresh requested. The client will report on its next heartbeat (about 15 s).'
          : 'Refresh requested. It will apply when the device reconnects (within 30 minutes).',
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
      notify(true, 'Removed from address book');
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
      notify(true, 'Discovery record removed');
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
      ? `${info.cpu_logical} logical / ${info.cpu_physical} physical`
      : info.cpu_logical
        ? `${info.cpu_logical} logical`
        : info.cpu_physical
          ? `${info.cpu_physical} physical`
          : '')
    : '';

  return (
    <>
      <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={onClose} role="presentation">
        <div
          className="flex h-full w-full max-w-xl flex-col overflow-y-auto bg-white shadow-xl dark:bg-slate-900"
          onClick={(e) => e.stopPropagation()}
          role="dialog"
          aria-modal="true"
          aria-label={`Device ${rid}`}
        >
          <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-slate-200 bg-white px-5 py-4 dark:border-slate-800 dark:bg-slate-900">
            <div className="min-w-0">
              <h2 className="truncate text-lg font-bold">{name}</h2>
              <p className="font-mono text-xs text-slate-500 dark:text-slate-400">{rid}</p>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <span className="inline-flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
                  <StatusDot p={presence} lastSeen={data?.last_seen ?? null} />
                  {statusLabel(presence, data?.last_seen ?? null)}
                </span>
                {data?.sources.includes('address_book') && <Badge tone="slate">Address book</Badge>}
                {data?.sources.includes('discovery') && <Badge tone="green">Discovered</Badge>}
                {data?.sources.includes('sysinfo') && <Badge tone="blue">Client report</Badge>}
              </div>
            </div>
            <button
              onClick={onClose}
              aria-label="Close"
              className="rounded border border-slate-200 px-2 py-0.5 text-sm text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
            >
              ✕
            </button>
          </div>

          <div className="flex-1 space-y-5 px-5 py-4">
            {error && (
              <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
                {error}
                <button onClick={() => { void load(); }} className="ml-2 underline">Retry</button>
              </div>
            )}
            {!data && loading && <Loading text="Loading device" />}
            {!data && !loading && !error && <p className="text-sm text-slate-500 dark:text-slate-400">No data.</p>}

            {data && (
              <>
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Connection</h3>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
                    <Field label="Status" value={statusLabel(presence, data.last_seen)} />
                    <Field label="Last seen" value={lastSeenText(data.last_seen)} />
                    <Field label="IP address" value={data.last_ip} mono />
                    <Field
                      label="Detected via"
                      value={disc ? sourceLabel(disc.source) : ''}
                      fallback={entries.length > 0 ? 'Address book heartbeat' : 'Not available'}
                    />
                    <Field label="First seen" value={disc?.first_seen ? absTime(disc.first_seen) : ''} />
                    <Field label="Last connected" value={disc?.last_connected ? absTime(disc.last_connected) : ''} />
                    <Field label="Last disconnected" value={disc?.last_disconnected ? absTime(disc.last_disconnected) : ''} />
                    <Field
                      label="Address books"
                      value={entries.map((e) => e.book_name).join(', ')}
                      fallback="Not in a visible book"
                    />
                  </dl>
                </section>

                <section>
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">System</h3>
                    <Badge tone={fresh.tone} title={fresh.title}>{fresh.label}</Badge>
                  </div>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
                    <Field label="Hostname" value={info?.hostname || primary?.hostname || ''} />
                    <Field label="Username" value={info?.username || primary?.username || ''} />
                    <Field label="Operating system" value={info?.os || primary?.platform || ''} />
                    <Field label="OS family" value={info?.os_name || ''} />
                    <Field label="OS version" value={info?.os_version || ''} />
                    <Field label="Client version" value={info?.version || ''} />
                    <Field label="Report uploaded" value={info?.collected_at ? lastSeenText(info.collected_at) : ''} />
                    <Field
                      label="Last heartbeat"
                      value={info?.last_heartbeat_at ? lastSeenText(info.last_heartbeat_at) : ''}
                      fallback="No heartbeat received"
                    />
                  </dl>
                </section>

                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Hardware</h3>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
                    <Field label="CPU" value={info?.cpu_model || info?.cpu || ''} hint={info?.cpu} />
                    <Field label="Frequency" value={info?.cpu_freq_ghz ? `${info.cpu_freq_ghz} GHz` : ''} />
                    <Field label="Cores" value={cores} />
                    <Field
                      label="Total RAM"
                      value={info?.memory_gb ? `${info.memory_gb} GB` : info?.memory || ''}
                    />
                  </dl>
                </section>

                <div className="rounded-lg border border-dashed border-slate-300 p-3 text-xs text-slate-500 dark:text-slate-400 dark:border-slate-700 dark:text-slate-400">
                  <div className="mb-1 font-medium text-slate-600 dark:text-slate-300">
                    Not provided by the stock RustDesk client
                  </div>
                  <div className="mb-2 flex flex-wrap gap-1">
                    {['Architecture', 'RAM usage', 'GPU', 'Disks', 'Network adapters'].map((x) => (
                      <Badge key={x} tone="slate">{x}</Badge>
                    ))}
                  </div>
                  The client uploads hostname, username, OS, CPU model/cores, total RAM and its
                  version. These fields stay unavailable instead of being guessed.
                </div>

                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Address book</h3>
                  {entries.length === 0 ? (
                    <p className="text-sm text-slate-500 dark:text-slate-400">This device is not in any address book you can see.</p>
                  ) : (
                    <div className="space-y-2">
                      {entries.map((e: DeviceDetailEntry) => (
                        <div key={e.id} className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <div className="min-w-0">
                              <div className="truncate font-medium">{e.alias || e.rustdesk_id}</div>
                              <div className="text-xs text-slate-500 dark:text-slate-400">
                                {e.book_name} · {statusLabel(e.presence, e.last_seen)}
                              </div>
                              {e.tag_objs.length > 0 && (
                                <div className="mt-1 flex flex-wrap gap-1">
                                  {e.tag_objs.map((t) => <TagBadge key={t.id} name={t.name} color={t.color} />)}
                                </div>
                              )}
                            </div>
                            <div className="flex gap-1">
                              <button
                                className={btnGhost}
                                onClick={() => onEdit(e, e.book_id)}
                                disabled={!canWriteBook(e.book_id)}
                              >
                                Edit
                              </button>
                              <button
                                className={btnGhostDanger}
                                onClick={() => setDelEntry(e)}
                                disabled={!canWriteBook(e.book_id)}
                              >
                                Delete
                              </button>
                            </div>
                          </div>
                          {e.note && (
                            <p className="mt-2 whitespace-pre-wrap text-xs text-slate-500 dark:text-slate-400">{e.note}</p>
                          )}
                          <div className="mt-1 text-[11px] text-slate-400">
                            {e.password_configured ? 'Stored password configured' : 'No stored password'}
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
              {busy ? 'Working…' : 'Refresh info'}
            </button>
            {disc && disc.in_books.length === 0 && (
              <button
                className={btnGhost}
                onClick={() => onAddToBook(disc)}
                disabled={!canAddToBook}
                title={canAddToBook ? undefined : 'You have no writable address books'}
              >
                Add to book
              </button>
            )}
            {isAdmin && disc && (
              <button className={btnGhostDanger} onClick={() => setForgetOpen(true)}>Forget</button>
            )}
            <button className={`${btnGhost} ml-auto`} onClick={onClose}>Close</button>
          </div>
        </div>
      </div>

      {delEntry && (
        <Confirm
          text={`Remove ${delEntry.alias || delEntry.rustdesk_id} from the address book? Tags themselves are not deleted.`}
          yesLabel="Remove"
          busy={busy}
          onYes={() => { void removeEntry(); }}
          onNo={() => setDelEntry(null)}
        />
      )}
      {forgetOpen && (
        <Confirm
          text={`Remove the discovery record for ${rid}? Address book entries and the stored system report are not deleted.`}
          yesLabel="Forget"
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
    if (!bookId) { setError('Choose an address book.'); return; }
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
      title="Add discovered device"
      subtitle="The device stays in the discovered registry; a copy is added to the selected book."
      onClose={onClose}
      footer={
        <>
          <button className={btnGhost} onClick={onClose} disabled={busy}>Cancel</button>
          <button className={btn} onClick={() => { void save(); }} disabled={busy || books.length === 0}>
            {busy ? 'Adding…' : 'Add to book'}
          </button>
        </>
      }
    >
      <div className="mb-4 rounded-lg bg-slate-50 px-3 py-2 text-sm dark:bg-slate-800">
        <div className="font-medium">{device.info?.hostname || device.rustdesk_id}</div>
        <div className="font-mono text-xs text-slate-500 dark:text-slate-400">{device.rustdesk_id}</div>
        <div className="text-xs text-slate-500 dark:text-slate-400">
          {[device.info?.os_name, device.info?.version ? `v${device.info.version}` : '', device.last_ip]
            .filter(Boolean).join(' · ') || 'No system report'}
        </div>
      </div>

      {error && <p className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">{error}</p>}
      {books.length === 0 && (
        <p className="mb-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
          You do not have write access to any address book.
        </p>
      )}

      <div className="space-y-3">
        <label className="block text-sm">
          Address book
          <select aria-label="Address book" value={bookId} onChange={(e) => setBookId(e.target.value)} className={`${input} mt-1`}>
            {books.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </label>
        <label className="block text-sm">
          Alias
          <input value={alias} onChange={(e) => setAlias(e.target.value)} className={`${input} mt-1`} />
        </label>
        <div className="text-sm">
          Tags
          <div className="mt-1 max-h-36 overflow-y-auto rounded border border-slate-200 p-2 dark:border-slate-700">
            {bookTags.map((t) => (
              <label key={t.id} className="flex items-center gap-2 py-0.5 text-sm">
                <Checkbox
                  checked={picked.includes(t.name)}
                  onChange={() => togglePick(t.name)}
                  label={`Tag ${t.name}`}
                />
                <TagBadge name={t.name} color={t.color} />
              </label>
            ))}
            {!tagsLoading && bookTags.length === 0 && (
              <span className="text-xs text-slate-400">No tags in this book yet</span>
            )}
            {tagsLoading && <span className="text-xs text-slate-400">Loading tags…</span>}
          </div>
          <input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder="New tags, comma separated"
            className={`${input} mt-2`}
          />
          {tagNames.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {tagNames.map((name) => <Badge key={name} tone="slate">{name}</Badge>)}
            </div>
          )}
        </div>
        <label className="block text-sm">
          Note
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
      setError('Select or type at least one tag.');
      return;
    }
    const overlap = finalAdd.filter((name) => remove.includes(name));
    if (overlap.length > 0) {
      setError(`Tag "${overlap[0]}" is selected for both adding and removing.`);
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
      title="Add or remove tags"
      subtitle={`${count} selected device${count === 1 ? '' : 's'}. Existing tags are preserved; only the checked tags change.`}
      onClose={onClose}
      size="lg"
      footer={
        <>
          <button className={btnGhost} onClick={onClose} disabled={busy}>Cancel</button>
          <button className={btn} onClick={() => { void apply(); }} disabled={busy}>
            {busy ? 'Applying…' : 'Apply'}
          </button>
        </>
      }
    >
      {error && <p className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">{error}</p>}
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-green-700 dark:text-green-400">Add tags</h3>
          <div className="max-h-40 overflow-y-auto rounded border border-slate-200 p-2 dark:border-slate-700">
            {tags.map((t) => (
              <label key={t.id} className="flex items-center gap-2 py-0.5 text-sm">
                <Checkbox checked={add.includes(t.name)} onChange={() => toggleAdd(t.name)} label={`Add ${t.name}`} />
                <TagBadge name={t.name} color={t.color} />
              </label>
            ))}
            {tags.length === 0 && <span className="text-xs text-slate-400">No tags in this book yet</span>}
          </div>
          <input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder="New tags, comma separated"
            className={`${input} mt-2`}
          />
          {typedNames.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {typedNames.map((name) => <Badge key={name} tone="green">{name}</Badge>)}
            </div>
          )}
        </div>
        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-red-700 dark:text-red-400">Remove tags</h3>
          <div className="max-h-40 overflow-y-auto rounded border border-slate-200 p-2 dark:border-slate-700">
            {tags.map((t) => (
              <label key={t.id} className="flex items-center gap-2 py-0.5 text-sm">
                <Checkbox checked={remove.includes(t.name)} onChange={() => toggleRemove(t.name)} label={`Remove ${t.name}`} />
                <TagBadge name={t.name} color={t.color} />
              </label>
            ))}
            {tags.length === 0 && <span className="text-xs text-slate-400">No tags in this book yet</span>}
          </div>
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            A tag is only detached from the selected devices; the tag itself is not deleted.
          </p>
        </div>
      </div>
      <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">Up to 20 tags per operation.</p>
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
  const [rid, setRid] = useState(initial?.rustdesk_id || '');
  const [alias, setAlias] = useState(initial?.alias || '');
  const [note, setNote] = useState(initial?.note || '');
  const [pw, setPw] = useState('');
  const [sel, setSel] = useState<string[]>(initial?.tags || []);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!rid.trim()) { onError('RustDesk ID required'); return; }
    if (!tagsReady) { onError('Tags are still loading; try again in a moment.'); return; }
    setBusy(true);
    try {
      const body = { rustdesk_id: rid.trim(), alias, note, tags: sel, password: pw };
      if (initial) await api.updateEntry(initial.id, body);
      else await api.createEntry(book, body);
      onSaved(initial ? 'Device updated' : 'Device created');
    } catch (e) {
      onError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose} role="presentation">
      <div
        className="max-h-[90vh] w-full max-w-md overflow-y-auto rounded-lg bg-white p-5 shadow-xl dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={initial ? 'Edit device' : 'Add device'}
      >
        <div className="mb-4 flex items-start justify-between gap-2">
          <h2 className="text-lg font-bold">{initial ? 'Edit device' : 'Add device'}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded border border-slate-200 px-2 py-0.5 text-sm text-slate-500 dark:text-slate-400 dark:border-slate-700">✕</button>
        </div>
        <div className="space-y-3">
          <label className="block text-sm">
            RustDesk ID
            <input value={rid} onChange={(e) => setRid(e.target.value)} className={`${input} mt-1`} />
          </label>
          <label className="block text-sm">
            Alias
            <input value={alias} onChange={(e) => setAlias(e.target.value)} className={`${input} mt-1`} />
          </label>
          <div className="text-sm">
            Tags
            <div className="mt-1 max-h-32 overflow-y-auto rounded border border-slate-200 p-2 dark:border-slate-700">
              {tags.map((t) => (
                <label key={t.id} className="flex items-center gap-2 py-0.5 text-sm">
                  <Checkbox
                    checked={sel.includes(t.name)}
                    onChange={() => setSel((list) => (list.includes(t.name) ? list.filter((x) => x !== t.name) : [...list, t.name]))}
                    label={`Tag ${t.name}`}
                  />
                  <TagBadge name={t.name} color={t.color} />
                </label>
              ))}
              {tagsReady && tags.length === 0 && <span className="text-slate-400">No tags in this book</span>}
              {!tagsReady && <span className="text-slate-400">Loading tags…</span>}
            </div>
          </div>
          <label className="block text-sm">
            Note
            <textarea value={note} onChange={(e) => setNote(e.target.value)} className={`${input} mt-1`} rows={2} />
          </label>
          <label className="block text-sm">
            Password {initial && '(leave empty to keep)'}
            <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} className={`${input} mt-1`} />
          </label>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className={btnGhost}>Cancel</button>
          <button onClick={() => { void save(); }} disabled={busy || !tagsReady} className={btn}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
