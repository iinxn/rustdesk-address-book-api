import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import {
  Confirm, Layout, LoadError, Loading, Pagination, StatusDot, TagBadge, Toasts,
  btn, btnGhost, input, statusLabel,
} from '../components';
import { useDebounce, useTheme, useToasts } from '../hooks';
import type { Book, Customer, Device, Stats, TagRow } from '../types';

const SIZE = 50;

export default function Devices() {
  const { dark, toggle } = useTheme();
  const { items: toasts, push } = useToasts();
  const [books, setBooks] = useState<Book[]>([]);
  const [book, setBook] = useState('');
  const [devices, setDevices] = useState<Device[]>([]);
  const [total, setTotal] = useState(0);
  const [tags, setTags] = useState<TagRow[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [search, setSearch] = useState('');
  const [selTags, setSelTags] = useState<string[]>([]);
  const [mode, setMode] = useState<'and' | 'or'>('or');
  const [presence, setPresence] = useState('');
  const [customer, setCustomer] = useState(() => sessionStorage.getItem('ab_customer') || '');
  useEffect(() => { sessionStorage.removeItem('ab_customer'); }, []);
  const [sort, setSort] = useState('status');
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [sel, setSel] = useState<Device | null>(null);
  const [editing, setEditing] = useState<Device | 'new' | null>(null);
  const [confirmDel, setConfirmDel] = useState<Device | null>(null);

  const q = useDebounce(search);
  const filtersActive = q !== '' || selTags.length > 0 || presence !== '' || customer !== '';

  const load = useCallback(async (silent = false) => {
    if (!book) return;
    if (!silent) { setLoading(true); setFailed(false); }
    try {
      const [pg, t, s] = await Promise.all([
        api.entriesWithTags(book, {
          search: q, mode, presence, customer_id: customer, sort, page, page_size: SIZE,
        }, selTags),
        api.tags(book),
        api.stats(),
      ]);
      setDevices(pg.data); setTotal(pg.total); setTags(t as TagRow[]); setStats(s);
    } catch {
      if (!silent) setFailed(true);
    } finally {
      if (!silent) setLoading(false);
    }
  }, [book, q, mode, presence, customer, sort, page, selTags]);

  useEffect(() => {
    api.books().then((b) => {
      setBooks(b);
      if (b.length && !book) setBook(b[0].id);
    }).catch(() => setFailed(true));
    api.customers().then(setCustomers).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { setPage(1); }, [q, selTags, mode, presence, customer, sort, book]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const t = setInterval(() => load(true), 20000);
    return () => clearInterval(t);
  }, [load]);

  const toggleTag = (n: string) => setSelTags((l) => (l.includes(n) ? l.filter((x) => x !== n) : [...l, n]));
  const clearAll = () => { setSearch(''); setSelTags([]); setMode('or'); setPresence(''); setCustomer(''); };

  const doDelete = async () => {
    if (!confirmDel) return;
    try {
      await api.deleteEntry(confirmDel.id);
      push(true, 'Device deleted');
      setConfirmDel(null); setSel(null); load();
    } catch (e) { push(false, String((e as Error).message)); }
  };

  return (
    <Layout dark={dark} onTheme={toggle}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-bold">Devices</h1>
        <div className="flex items-center gap-2">
          {stats && <span className="text-sm text-slate-500 dark:text-slate-400">
            Devices: {stats.devices} · Online: {stats.online} · Offline: {stats.offline}{stats.unknown ? ` · Unknown: ${stats.unknown}` : ''}
          </span>}
          <button className={btn} onClick={() => setEditing('new')}>+ Add device</button>
        </div>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <select value={book} onChange={(e) => setBook(e.target.value)} className={`${input} w-auto`}>
          {books.map((b) => <option key={b.id} value={b.id}>{b.name} [{b.type}]</option>)}
        </select>
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="🔎 Search devices…" className={`${input} max-w-xs`} />
        <select value={sort} onChange={(e) => setSort(e.target.value)} className={`${input} w-auto`} title="Sort">
          <option value="status">Status + Alias</option>
          <option value="alias">Alias</option>
          <option value="rustdesk_id">RustDesk ID</option>
          <option value="last_seen">Last seen</option>
        </select>
        <select value={presence} onChange={(e) => setPresence(e.target.value)} className={`${input} w-auto`}>
          <option value="">All states</option>
          <option value="online">Online</option>
          <option value="offline">Offline</option>
          <option value="unknown">Unknown</option>
        </select>
        <select value={customer} onChange={(e) => setCustomer(e.target.value)} className={`${input} w-auto`}>
          <option value="">All customers</option>
          {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        {filtersActive && <button onClick={clearAll} className={btnGhost}>Clear filters</button>}
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        <button onClick={() => setSelTags([])} className={`rounded-full px-2.5 py-0.5 text-xs ${selTags.length === 0 ? 'bg-slate-800 text-white dark:bg-slate-200 dark:text-slate-900' : 'bg-slate-200 dark:bg-slate-700'}`}>
          All
        </button>
        {tags.map((t) => {
          const on = selTags.includes(t.name);
          return (
            <button key={t.id} onClick={() => toggleTag(t.name)} title={`${t.devices} devices`}
              className={`rounded-full px-2.5 py-0.5 text-xs text-white ${on ? 'ring-2 ring-offset-1 ring-slate-500' : 'opacity-80 hover:opacity-100'}`}
              style={{ backgroundColor: `#${t.color.toString(16).padStart(8, '0').slice(2)}` }}>
              {t.name}
            </button>
          );
        })}
        {selTags.length > 1 && (
          <button onClick={() => setMode(mode === 'and' ? 'or' : 'and')} className={btnGhost} title="AND / OR">
            {mode.toUpperCase()}
          </button>
        )}
      </div>

      {loading ? <Loading text="Loading devices" /> : failed ? <LoadError onRetry={() => load()} /> :
        devices.length === 0 ? (
          <div className="py-10 text-center text-sm text-slate-500">
            {filtersActive ? (<>No devices match current filters<br /><button onClick={clearAll} className={`${btnGhost} mt-2`}>Clear filters</button></>) : (<>No devices<br /><button onClick={() => setEditing('new')} className={`${btn} mt-2`}>Add your first device</button></>)}
          </div>
        ) : (
          <div className="overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
            {devices.map((d) => (
              <button key={d.id} onClick={() => setSel(d)}
                className="flex w-full items-start gap-3 border-b border-slate-100 px-3 py-2.5 text-left hover:bg-slate-50 last:border-0 dark:border-slate-800 dark:hover:bg-slate-800">
                <span className="mt-1.5"><StatusDot p={d.presence} lastSeen={d.last_seen} /></span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{d.alias || d.rustdesk_id}</span>
                  <span className="block font-mono text-xs text-slate-500">{d.rustdesk_id}</span>
                  {d.customer && <span className="block truncate text-xs text-slate-500">{d.customer.name}</span>}
                  <span className="mt-1 flex flex-wrap gap-1">
                    {d.tag_objs.map((t) => <TagBadge key={t.id} name={t.name} color={t.color} />)}
                  </span>
                  <span className="block text-xs text-slate-400" title={d.last_seen || undefined}>{statusLabel(d.presence, d.last_seen)}</span>
                </span>
              </button>
            ))}
          </div>
        )}

      <div className="mt-3 flex justify-end">
        <Pagination page={page} total={total} size={SIZE} onPage={setPage} />
      </div>

      {sel && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={() => setSel(null)}>
          <div className="w-full max-w-sm overflow-y-auto bg-white p-5 dark:bg-slate-900" onClick={(e) => e.stopPropagation()}>
            <h2 className="mb-1 text-lg font-bold">{sel.alias || sel.rustdesk_id}</h2>
            <p className="mb-4 flex items-center gap-2 text-sm text-slate-500">
              <StatusDot p={sel.presence} lastSeen={sel.last_seen} /> {statusLabel(sel.presence, sel.last_seen)}
            </p>
            <dl className="space-y-3 text-sm">
              <div><dt className="text-slate-500">RustDesk ID</dt><dd className="font-mono">{sel.rustdesk_id}</dd></div>
              <div><dt className="text-slate-500">Customer</dt><dd>{sel.customer?.name || '—'}</dd></div>
              <div><dt className="text-slate-500">Tags</dt><dd className="flex flex-wrap gap-1">{sel.tag_objs.map((t) => <TagBadge key={t.id} name={t.name} color={t.color} />)}{sel.tag_objs.length === 0 && '—'}</dd></div>
              <div><dt className="text-slate-500">Note</dt><dd className="whitespace-pre-wrap">{sel.note || '—'}</dd></div>
              <div><dt className="text-slate-500">Last seen</dt><dd title={sel.last_seen || undefined}>{sel.last_seen ? new Date(sel.last_seen).toLocaleString() : 'Unknown'}</dd></div>
              <div><dt className="text-slate-500">Password</dt><dd>{sel.password_configured ? '● Configured' : '—'}</dd></div>
              <div><dt className="text-slate-500">Created</dt><dd>{sel.created_at ? new Date(sel.created_at).toLocaleString() : '—'}</dd></div>
              <div><dt className="text-slate-500">Updated</dt><dd>{sel.updated_at ? new Date(sel.updated_at).toLocaleString() : '—'}</dd></div>
            </dl>
            <div className="mt-5 flex gap-2">
              <button className={btn} onClick={() => { setEditing(sel); setSel(null); }}>Edit</button>
              <button className="rounded-md bg-red-600 px-3 py-1.5 text-sm text-white" onClick={() => setConfirmDel(sel)}>Delete</button>
              <button className={btnGhost} onClick={() => setSel(null)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {editing && (
        <DeviceForm
          book={book} initial={editing === 'new' ? null : editing} tags={tags} customers={customers}
          onClose={() => setEditing(null)}
          onSaved={(msg) => { setEditing(null); push(true, msg); load(); }}
          onError={(m) => push(false, m)}
        />
      )}
      {confirmDel && <Confirm text={`Delete ${confirmDel.alias || confirmDel.rustdesk_id}?`} onYes={doDelete} onNo={() => setConfirmDel(null)} />}
      <Toasts items={toasts} />
    </Layout>
  );
}

function DeviceForm({ book, initial, tags, customers, onClose, onSaved, onError }: {
  book: string; initial: Device | null; tags: TagRow[]; customers: Customer[];
  onClose: () => void; onSaved: (m: string) => void; onError: (m: string) => void;
}) {
  const [rid, setRid] = useState(initial?.rustdesk_id || '');
  const [alias, setAlias] = useState(initial?.alias || '');
  const [note, setNote] = useState(initial?.note || '');
  const [cust, setCust] = useState(initial?.customer_id || '');
  const [pw, setPw] = useState('');
  const [sel, setSel] = useState<string[]>(initial?.tags || []);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!rid.trim()) { onError('RustDesk ID required'); return; }
    setBusy(true);
    try {
      const body = { rustdesk_id: rid.trim(), alias, note, customer_id: cust || null, tags: sel, password: pw };
      if (initial) await api.updateEntry(initial.id, body);
      else await api.createEntry(book, body);
      onSaved(initial ? 'Device updated' : 'Device created');
    } catch (e) { onError(String((e as Error).message)); }
    finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="max-h-[90vh] w-full max-w-md overflow-y-auto rounded-lg bg-white p-5 dark:bg-slate-900" onClick={(e) => e.stopPropagation()}>
        <h2 className="mb-4 text-lg font-bold">{initial ? 'Edit device' : 'Add device'}</h2>
        <div className="space-y-3">
          <label className="block text-sm">RustDesk ID<input value={rid} onChange={(e) => setRid(e.target.value)} className={input} /></label>
          <label className="block text-sm">Alias<input value={alias} onChange={(e) => setAlias(e.target.value)} className={input} /></label>
          <label className="block text-sm">Customer
            <select value={cust} onChange={(e) => setCust(e.target.value)} className={input}>
              <option value="">—</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          <div className="text-sm">Tags
            <div className="mt-1 max-h-32 overflow-y-auto rounded border border-slate-200 p-2 dark:border-slate-700">
              {tags.map((t) => (
                <label key={t.id} className="flex items-center gap-2 py-0.5 text-sm">
                  <input type="checkbox" checked={sel.includes(t.name)}
                    onChange={() => setSel((l) => (l.includes(t.name) ? l.filter((x) => x !== t.name) : [...l, t.name]))} />
                  <TagBadge name={t.name} color={t.color} />
                </label>
              ))}
              {tags.length === 0 && <span className="text-slate-400">No tags in this book</span>}
            </div>
          </div>
          <label className="block text-sm">Note<textarea value={note} onChange={(e) => setNote(e.target.value)} className={input} rows={2} /></label>
          <label className="block text-sm">Password {initial && '(leave empty to keep)'}<input type="password" value={pw} onChange={(e) => setPw(e.target.value)} className={input} /></label>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className={btnGhost}>Cancel</button>
          <button onClick={save} disabled={busy} className={btn}>Save</button>
        </div>
      </div>
    </div>
  );
}
