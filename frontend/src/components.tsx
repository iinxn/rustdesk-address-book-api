import { useEffect, useRef } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { clearSession, sessionUser } from './api';
import type { Toast } from './hooks';
import { colorCss, relTime, textOnColor } from './types';
import type { Presence } from './types';

const link =
  'block rounded-md px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800';

const navClass = ({ isActive }: { isActive: boolean }) =>
  `${link} ${isActive ? 'bg-slate-100 font-medium text-slate-900 dark:bg-slate-800 dark:text-white' : ''}`;

const mobileNavClass = ({ isActive }: { isActive: boolean }) =>
  `rounded px-2 py-1 ${isActive ? 'font-medium text-blue-700 dark:text-blue-400' : 'text-slate-600 dark:text-slate-300'}`;

/** Official RustDesk mark + product name (technical package names stay unchanged). */
export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <img
        src={`${import.meta.env.BASE_URL}logo.svg`}
        alt="RustDesk"
        className="h-8 w-8 shrink-0"
      />
      <div className="min-w-0">
        <div className="truncate text-sm font-bold leading-tight">RustDesk API</div>
        {!compact && (
          <div className="truncate text-[11px] text-slate-500 dark:text-slate-400">
            Address Book Panel
          </div>
        )}
      </div>
    </div>
  );
}

export function Layout({ children, onTheme, dark }: { children: React.ReactNode; onTheme: () => void; dark: boolean }) {
  const nav = useNavigate();
  const u = sessionUser();
  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <aside className="hidden w-56 shrink-0 flex-col border-r border-slate-200 bg-white p-4 md:flex dark:border-slate-800 dark:bg-slate-900">
        <div className="mb-6">
          <Brand />
        </div>
        <nav className="flex flex-col gap-1">
          <NavLink to="/" className={navClass}>Devices</NavLink>
          <NavLink to="/books" className={navClass}>Address Books</NavLink>
          <NavLink to="/tags" className={navClass}>Tags</NavLink>
          {u?.isAdmin && <NavLink to="/users" className={navClass}>Users</NavLink>}
        </nav>
        <div className="mt-auto space-y-1 pt-6 text-[11px] text-slate-500 dark:text-slate-400">
          <div>Self-hosted RustDesk API</div>
          <div>
            Developed by{' '}
            <a
              href="https://github.com/iinxn"
              target="_blank"
              rel="noopener noreferrer"
              className="font-medium text-slate-600 underline-offset-2 hover:text-blue-700 hover:underline dark:text-slate-300 dark:hover:text-blue-400"
            >
              iinxn
            </a>
          </div>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-2 border-b border-slate-200 bg-white px-4 py-2 dark:border-slate-800 dark:bg-slate-900">
          <div className="min-w-0 md:hidden">
            <Brand compact />
          </div>
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={onTheme}
              className="rounded-md border border-slate-200 px-2 py-1 text-sm dark:border-slate-700"
              title={dark ? 'Switch to light theme' : 'Switch to dark theme'}
              aria-label="Toggle theme"
            >
              {dark ? '☀️' : '🌙'}
            </button>
            <span className="hidden text-sm text-slate-500 sm:inline dark:text-slate-400">{u?.username}</span>
            <button
              onClick={() => { clearSession(); nav('/login'); }}
              className="rounded-md border border-slate-200 px-2 py-1 text-sm dark:border-slate-700"
            >
              Logout
            </button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 p-4 pb-20 md:pb-4">{children}</main>
        <nav aria-label="Mobile navigation" className="fixed inset-x-0 bottom-0 z-30 flex justify-around border-t border-slate-200 bg-white py-2 text-sm md:hidden dark:border-slate-800 dark:bg-slate-900">
          <NavLink to="/" className={mobileNavClass}>Devices</NavLink>
          <NavLink to="/books" className={mobileNavClass}>Books</NavLink>
          <NavLink to="/tags" className={mobileNavClass}>Tags</NavLink>
          {u?.isAdmin && <NavLink to="/users" className={mobileNavClass}>Users</NavLink>}
        </nav>
      </div>
    </div>
  );
}

export function TagBadge({ name, color }: { name: string; color?: number }) {
  const background = color !== undefined ? colorCss(color) : '#64748b';
  return (
    <span
      className="inline-block rounded-full px-2 py-0.5 text-xs font-medium"
      style={{ backgroundColor: background, color: textOnColor(background) }}
    >
      {name}
    </span>
  );
}

export function Badge({
  children,
  tone = 'slate',
  title,
}: {
  children: React.ReactNode;
  tone?: 'slate' | 'green' | 'amber' | 'blue' | 'red';
  title?: string;
}) {
  const tones = {
    slate: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
    green: 'bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300',
    amber: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
    blue: 'bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300',
    red: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300',
  };
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${tones[tone]}`}
    >
      {children}
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

/** Label/value pair that never invents data: empty values become a fallback. */
export function Field({
  label,
  value,
  mono = false,
  fallback = 'Not reported',
  hint,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
  fallback?: string;
  hint?: string;
}) {
  const empty = value === null || value === undefined || value === '';
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-slate-400">{label}</dt>
      <dd
        className={`mt-0.5 break-words text-sm ${mono ? 'font-mono' : ''} ${empty ? 'text-slate-400' : ''}`}
        title={hint}
      >
        {empty ? fallback : value}
      </dd>
    </div>
  );
}

export function Checkbox({
  checked,
  indeterminate = false,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean;
  indeterminate?: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate;
  }, [indeterminate]);
  return (
    <input
      ref={ref}
      type="checkbox"
      checked={checked}
      disabled={disabled}
      onChange={(e) => onChange(e.target.checked)}
      aria-label={label}
      className="h-4 w-4 shrink-0 cursor-pointer rounded border-slate-300 accent-blue-600 disabled:cursor-not-allowed dark:border-slate-600"
    />
  );
}

export function Modal({
  title,
  subtitle,
  onClose,
  children,
  footer,
  size = 'md',
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  size?: 'md' | 'lg';
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center sm:p-4"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`max-h-[92vh] w-full overflow-y-auto rounded-t-xl bg-white p-5 shadow-xl dark:bg-slate-900 sm:rounded-xl ${
          size === 'lg' ? 'sm:max-w-2xl' : 'sm:max-w-md'
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-bold">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded border border-slate-200 px-2 py-0.5 text-sm text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
          >
            ✕
          </button>
        </div>
        {children}
        {footer && <div className="mt-5 flex flex-wrap justify-end gap-2">{footer}</div>}
      </div>
    </div>
  );
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

export function Confirm({
  text,
  onYes,
  onNo,
  yesLabel = 'Delete',
  busy = false,
}: {
  text: string;
  onYes: () => void;
  onNo: () => void;
  yesLabel?: string;
  busy?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onNo();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onNo]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="presentation">
      <div className="w-full max-w-sm rounded-lg bg-white p-4 shadow-xl dark:bg-slate-900" role="dialog" aria-modal="true">
        <p className="mb-4 text-sm">{text}</p>
        <div className="flex justify-end gap-2">
          <button onClick={onNo} disabled={busy} className={btnGhost}>Cancel</button>
          <button onClick={onYes} disabled={busy} className={btnDanger}>
            {busy ? 'Working…' : yesLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function Toasts({ items }: { items: Toast[] }) {
  return (
    <div className="fixed bottom-4 right-4 z-[60] flex max-w-sm flex-col gap-2">
      {items.map((t) => (
        <div key={t.id} className={`rounded-md px-3 py-2 text-sm text-white shadow ${t.ok ? 'bg-green-600' : 'bg-red-600'}`}>
          {t.text}
        </div>
      ))}
    </div>
  );
}

export function Loading({ text }: { text: string }) {
  return <div className="py-10 text-center text-sm text-slate-500 dark:text-slate-400">{text}…</div>;
}

export function LoadError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="py-10 text-center text-sm">
      <p className="mb-2 text-red-600">Failed to load</p>
      <button onClick={onRetry} className={btnGhost}>Retry</button>
    </div>
  );
}

export const input =
  'w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800';
export const btn =
  'rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50';
export const btnDanger =
  'rounded-md bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700 disabled:opacity-50';
export const btnGhost =
  'rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700';
export const btnGhostDanger =
  'rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50 dark:border-red-900 dark:text-red-400 dark:hover:bg-red-950';
