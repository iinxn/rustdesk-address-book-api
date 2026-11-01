/** Table rows, tabs and section headers of the Devices page. */
import {
  Badge, Checkbox, StatusDot, TagBadge, btn, btnGhost, btnGhostDanger, statusLabel,
} from '../../components';
import { useI18n } from '../../i18n';
import { relTime } from '../../types';
import type { Device, DiscoveredDevice, Presence } from '../../types';
import { sourceLabel } from './format';

export function TabButton({ active, onClick, count, children }: {
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

export function SectionHeader({ title, subtitle, right }: {
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

export function EntryRow({ d, selectable, checked, onCheck, onOpen, onEdit, onDelete }: {
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

export function DiscoveredRow({ d, onOpen, onAdd, canAdd }: {
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

