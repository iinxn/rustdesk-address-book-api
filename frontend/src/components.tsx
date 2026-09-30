import { NavLink, useNavigate } from 'react-router-dom';
import { clearSession, sessionUser } from './api';
import type { Toast } from './hooks';
import { colorCss, relTime } from './types';
import type { Presence } from './types';

const link =
  'block rounded-md px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800';

export function Layout({ children, onTheme, dark }: { children: React.ReactNode; onTheme: () => void; dark: boolean }) {
  const nav = useNavigate();
  const u = sessionUser();
  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <aside className="hidden w-52 shrink-0 flex-col border-r border-slate-200 bg-white p-4 md:flex dark:border-slate-800 dark:bg-slate-900">
        <div className="mb-6 text-lg font-bold">AB Panel</div>
        <nav className="flex flex-col gap-1">
          <NavLink to="/" className={link}>Devices</NavLink>
          <NavLink to="/books" className={link}>Address Books</NavLink>
          <NavLink to="/tags" className={link}>Tags</NavLink>
          <NavLink to="/customers" className={link}>Customers</NavLink>
          {u?.isAdmin && <NavLink to="/users" className={link}>Users</NavLink>}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-2 md:hidden dark:border-slate-800 dark:bg-slate-900">
          <span className="font-bold">AB Panel</span>
        </header>
        <header className="flex items-center justify-end gap-2 border-b border-slate-200 bg-white px-4 py-2 dark:border-slate-800 dark:bg-slate-900">
          <button onClick={onTheme} className="rounded-md border border-slate-200 px-2 py-1 text-sm dark:border-slate-700" title="Theme">
            {dark ? '☀️' : '🌙'}
          </button>
          <span className="text-sm text-slate-500 dark:text-slate-400">{u?.username}</span>
          <button
            onClick={() => { clearSession(); nav('/login'); }}
            className="rounded-md border border-slate-200 px-2 py-1 text-sm dark:border-slate-700"
          >
            Logout
          </button>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 p-4">{children}</main>
        <nav className="flex justify-around border-t border-slate-200 bg-white py-2 text-sm md:hidden dark:border-slate-800 dark:bg-slate-900">
          <NavLink to="/">Devices</NavLink>
          <NavLink to="/books">Books</NavLink>
          <NavLink to="/tags">Tags</NavLink>
          <NavLink to="/customers">Clients</NavLink>
          {u?.isAdmin && <NavLink to="/users">Users</NavLink>}
        </nav>
      </div>
    </div>
  );
}

export function TagBadge({ name, color }: { name: string; color?: number }) {
  return (
    <span
      className="inline-block rounded-full px-2 py-0.5 text-xs font-medium text-white"
      style={{ backgroundColor: color !== undefined ? colorCss(color) : '#64748b' }}
    >
      {name}
    </span>
  );
}

export function StatusDot({ p, lastSeen }: { p: Presence; lastSeen: string | null }) {
  if (p === 'online') return <span title="Online" className="inline-block h-2.5 w-2.5 rounded-full bg-green-500" />;
  if (p === 'offline')
    return <span title={`Last seen ${relTime(lastSeen)}`} className="inline-block h-2.5 w-2.5 rounded-full bg-slate-300 dark:bg-slate-600" />;
  return <span title="Last seen — Unknown" className="inline-block h-2.5 w-2.5 rounded-full border border-slate-400" />;
}

export function statusLabel(p: Presence, lastSeen: string | null): string {
  if (p === 'online') return 'Online';
  if (p === 'offline') return `Last seen ${relTime(lastSeen)}`;
  return 'Last seen — Unknown';
}

export function Pagination({ page, total, size, onPage }: { page: number; total: number; size: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size));
  if (pages <= 1) return null;
  return (
    <div className="flex items-center gap-2 text-sm">
      <button disabled={page <= 1} onClick={() => onPage(page - 1)} className="rounded border px-2 py-1 disabled:opacity-40 dark:border-slate-700">Previous</button>
      <span>{page} / {pages} · {total}</span>
      <button disabled={page >= pages} onClick={() => onPage(page + 1)} className="rounded border px-2 py-1 disabled:opacity-40 dark:border-slate-700">Next</button>
    </div>
  );
}

export function Confirm({ text, onYes, onNo }: { text: string; onYes: () => void; onNo: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-80 rounded-lg bg-white p-4 dark:bg-slate-900">
        <p className="mb-4 text-sm">{text}</p>
        <div className="flex justify-end gap-2">
          <button onClick={onNo} className="rounded border px-3 py-1 text-sm dark:border-slate-700">Cancel</button>
          <button onClick={onYes} className="rounded bg-red-600 px-3 py-1 text-sm text-white">Delete</button>
        </div>
      </div>
    </div>
  );
}

export function Toasts({ items }: { items: Toast[] }) {
  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {items.map((t) => (
        <div key={t.id} className={`rounded-md px-3 py-2 text-sm text-white shadow ${t.ok ? 'bg-green-600' : 'bg-red-600'}`}>
          {t.text}
        </div>
      ))}
    </div>
  );
}

export function Loading({ text }: { text: string }) {
  return <div className="py-10 text-center text-sm text-slate-500">{text}…</div>;
}

export function LoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="py-10 text-center text-sm">
      <p className="mb-2 text-red-600">Failed to load</p>
      <button onClick={onRetry} className="rounded border px-3 py-1 dark:border-slate-700">Retry</button>
    </div>
  );
}

export const input =
  'w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800';
export const btn =
  'rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50';
export const btnGhost =
  'rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700';
