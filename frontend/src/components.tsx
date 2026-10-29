import { useEffect, useRef, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { api, clearSession, sessionUser, setDisplayName } from './api';
import { LANGS, translate, useI18n } from './i18n';
import type { Lang } from './i18n';
import { useNotify } from './notifications';
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
  const { t } = useI18n();
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
            {t('brand.subtitle')}{' '}
            <a
              href="https://github.com/iinxn"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-blue-700 hover:underline dark:hover:text-blue-400"
            >
              iinxn
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

/** RU / EN switch with the active language highlighted. */
export function LangSwitch() {
  const { lang, setLang, t } = useI18n();
  return (
    <div
      role="group"
      aria-label={t('lang.label')}
      className="flex overflow-hidden rounded-md border border-slate-300 dark:border-slate-700"
    >
      {LANGS.map((code) => (
        <button
          key={code}
          type="button"
          onClick={() => setLang(code)}
          aria-pressed={lang === code}
          className={`px-2 py-1 text-xs font-semibold transition-colors ${
            lang === code
              ? 'bg-blue-600 text-white'
              : 'bg-white text-slate-600 hover:bg-slate-100 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800'
          }`}
        >
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

export function Layout({ children, onTheme, dark }: { children: React.ReactNode; onTheme: () => void; dark: boolean }) {
  const nav = useNavigate();
  const u = sessionUser();
  const { t } = useI18n();
  const [profileOpen, setProfileOpen] = useState(false);
  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <aside className="hidden w-56 shrink-0 flex-col border-r border-slate-200 bg-white p-4 md:flex dark:border-slate-800 dark:bg-slate-900">
        <div className="mb-6">
          <Brand />
        </div>
        <nav className="flex flex-col gap-1">
          <NavLink to="/" className={navClass}>{t('nav.devices')}</NavLink>
          <NavLink to="/books" className={navClass}>{t('nav.books')}</NavLink>
          <NavLink to="/tags" className={navClass}>{t('nav.tags')}</NavLink>
          {u?.isAdmin && <NavLink to="/users" className={navClass}>{t('nav.users')}</NavLink>}
        </nav>
        <div className="mt-auto space-y-1 pt-6 text-[11px] text-slate-500 dark:text-slate-400">
          <div>{t('shell.selfHosted')}</div>
          <div>
            {t('shell.developedBy')}{' '}
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
            <LangSwitch />
            <button
              onClick={onTheme}
              className="rounded-md border border-slate-300 px-2 py-1 text-sm dark:border-slate-700"
              title={dark ? t('theme.toLight') : t('theme.toDark')}
              aria-label={t('theme.toggle')}
            >
              {dark ? '☀️' : '🌙'}
            </button>
            <button
              onClick={() => setProfileOpen(true)}
              className="max-w-[6rem] truncate text-sm text-slate-600 hover:text-slate-900 hover:underline sm:max-w-[10rem] dark:text-slate-400 dark:hover:text-slate-200"
              title={t('profile.displayName')}
              aria-label={t('profile.displayName')}
            >
              {u?.displayName || u?.username}
            </button>
            <button
              onClick={() => { clearSession(); nav('/login'); }}
              className="rounded-md border border-slate-300 px-2 py-1 text-sm dark:border-slate-700"
            >
              {t('auth.logout')}
            </button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 p-4 pb-20 md:pb-4">{children}</main>
        <nav aria-label={t('nav.mobile')} className="fixed inset-x-0 bottom-0 z-30 flex justify-around border-t border-slate-200 bg-white py-2 text-sm md:hidden dark:border-slate-800 dark:bg-slate-900">
          <NavLink to="/" className={mobileNavClass}>{t('nav.devices')}</NavLink>
          <NavLink to="/books" className={mobileNavClass}>{t('nav.books')}</NavLink>
          <NavLink to="/tags" className={mobileNavClass}>{t('nav.tags')}</NavLink>
          {u?.isAdmin && <NavLink to="/users" className={mobileNavClass}>{t('nav.users')}</NavLink>}
        </nav>
      </div>
      {profileOpen && <ProfileDialog initial={u?.displayName || ''} onClose={() => setProfileOpen(false)} />}
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
  const { lang } = useI18n();
  if (p === 'online') {
    return <span title={translate(lang, 'status.online')} className="inline-block h-2.5 w-2.5 rounded-full bg-green-500" />;
  }
  if (p === 'offline') {
    return (
      <span
        title={translate(lang, 'status.lastSeen', { time: relTime(lastSeen, lang) })}
        className="inline-block h-2.5 w-2.5 rounded-full bg-slate-300 dark:bg-slate-600"
      />
    );
  }
  return <span title={translate(lang, 'status.unknown')} className="inline-block h-2.5 w-2.5 rounded-full border border-slate-400" />;
}

export function statusLabel(p: Presence, lastSeen: string | null, lang: Lang): string {
  if (p === 'online') return translate(lang, 'status.online');
  if (p === 'offline') return translate(lang, 'status.lastSeen', { time: relTime(lastSeen, lang) });
  return translate(lang, 'status.unknown');
}

/** Label/value pair that never invents data: empty values become a fallback. */
export function Field({
  label,
  value,
  mono = false,
  fallback,
  hint,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
  fallback?: string;
  hint?: string;
}) {
  const { t } = useI18n();
  const empty = value === null || value === undefined || value === '';
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</dt>
      <dd
        className={`mt-0.5 break-words text-sm ${mono ? 'font-mono' : ''} ${empty ? 'text-slate-500 dark:text-slate-400' : ''}`}
        title={hint}
      >
        {empty ? (fallback ?? t('common.notReported')) : value}
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
  const { t } = useI18n();
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
        className={`max-h-[92vh] w-full overflow-y-auto rounded-t-xl bg-white p-5 text-slate-900 shadow-xl dark:bg-slate-900 dark:text-slate-100 sm:rounded-xl ${
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
            aria-label={t('common.close')}
            className="rounded border border-slate-200 px-2 py-0.5 text-sm text-slate-500 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-400 dark:hover:bg-slate-800"
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

/** Self-service display name: the value RustDesk sends to a remote PC as `my_name`. */
function ProfileDialog({ initial, onClose }: { initial: string; onClose: () => void }) {
  const { t } = useI18n();
  const { notify } = useNotify();
  const [name, setName] = useState(initial);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    setErr('');
    try {
      const me = await api.updateMe(name.trim());
      setDisplayName(me.display_name);
      notify(true, t('profile.saved'));
      onClose();
    } catch (e) {
      setErr(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title={t('profile.title')}
      subtitle={t('profile.subtitle')}
      onClose={onClose}
      footer={
        <>
          <button onClick={onClose} className={btnGhost}>{t('common.cancel')}</button>
          <button onClick={save} disabled={busy} className={btn}>{busy ? t('common.saving') : t('common.save')}</button>
        </>
      }
    >
      <label
        htmlFor="display-name"
        className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400"
      >
        {t('profile.displayName')}
      </label>
      <input
        id="display-name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        maxLength={128}
        placeholder={t('profile.placeholder')}
        className={input}
        autoFocus
        onKeyDown={(e) => e.key === 'Enter' && save()}
      />
      <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
        {t('profile.hint')}
      </p>
      {err && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{err}</p>}
    </Modal>
  );
}

export function Pagination({ page, total, size, onPage }: { page: number; total: number; size: number; onPage: (p: number) => void }) {
  const { t } = useI18n();
  const pages = Math.max(1, Math.ceil(total / size));
  if (pages <= 1) return null;
  return (
    <div className="flex items-center gap-2 text-sm">
      <button disabled={page <= 1} onClick={() => onPage(page - 1)} className="rounded border px-2 py-1 disabled:opacity-40 dark:border-slate-700">{t('common.previous')}</button>
      <span>{page} / {pages} · {total}</span>
      <button disabled={page >= pages} onClick={() => onPage(page + 1)} className="rounded border px-2 py-1 disabled:opacity-40 dark:border-slate-700">{t('common.next')}</button>
    </div>
  );
}

export function Confirm({
  text,
  onYes,
  onNo,
  yesLabel,
  busy = false,
}: {
  text: string;
  onYes: () => void;
  onNo: () => void;
  yesLabel?: string;
  busy?: boolean;
}) {
  const { t } = useI18n();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onNo();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onNo]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="presentation">
      <div className="w-full max-w-sm rounded-lg bg-white p-4 text-slate-900 shadow-xl dark:bg-slate-900 dark:text-slate-100" role="dialog" aria-modal="true">
        <p className="mb-4 text-sm">{text}</p>
        <div className="flex justify-end gap-2">
          <button onClick={onNo} disabled={busy} className={btnGhost}>{t('common.cancel')}</button>
          <button onClick={onYes} disabled={busy} className={btnDanger}>
            {busy ? t('common.working') : (yesLabel ?? t('common.delete'))}
          </button>
        </div>
      </div>
    </div>
  );
}

export function Loading({ text }: { text: string }) {
  return <div className="py-10 text-center text-sm text-slate-500 dark:text-slate-400">{text}…</div>;
}

export function LoadError({ onRetry }: { onRetry: () => void }) {
  const { t } = useI18n();
  return (
    <div className="py-10 text-center text-sm">
      <p className="mb-2 text-red-600 dark:text-red-400">{t('common.loadFailed')}</p>
      <button onClick={onRetry} className={btnGhost}>{t('common.retry')}</button>
    </div>
  );
}

export const input =
  'w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100';
export const btn =
  'rounded-md bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50';
export const btnDanger =
  'rounded-md bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700 disabled:opacity-50';
export const btnGhost =
  'rounded-md border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700';
export const btnGhostDanger =
  'rounded-md border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50 dark:border-red-900 dark:text-red-400 dark:hover:bg-red-950';
