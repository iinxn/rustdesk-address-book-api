import { translate } from './i18n';
import type { Lang } from './i18n';

export type Presence = 'online' | 'offline' | 'unknown';

export interface TagObj {
  id: string;
  name: string;
  color: number;
}

export interface TagRow extends TagObj {
  devices: number;
}

export interface Device {
  id: string;
  rustdesk_id: string;
  alias: string;
  note: string;
  tags: string[];
  tag_objs: TagObj[];
  presence: Presence;
  last_seen: string | null;
  password_configured: boolean;
  /** Address-book metadata, falling back to the client report. */
  hostname: string;
  username: string;
  platform: string;
  ip: string | null;
  os: string | null;
  has_info: boolean;
  info_updated_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Whitelisted facts uploaded by the stock client to /api/sysinfo. */
export interface DeviceInfo {
  rustdesk_id: string;
  hostname: string;
  username: string;
  os: string;
  os_name: string;
  os_version: string;
  cpu: string;
  cpu_model: string;
  cpu_freq_ghz: number | null;
  cpu_logical: number | null;
  cpu_physical: number | null;
  memory: string;
  memory_gb: number | null;
  version: string;
  ip: string;
  collected_at: string | null;
  last_heartbeat_at: string | null;
}

export interface BookRef {
  id: string;
  name: string;
}

/** Rendezvous evidence seen by the shim; independent of address books. */
export interface DiscoveredDevice {
  rustdesk_id: string;
  first_seen: string | null;
  last_seen: string | null;
  last_connected: string | null;
  last_disconnected: string | null;
  last_ip: string;
  source: string;
  online: boolean;
  seen_count: number;
  in_books: BookRef[];
  info: DeviceInfo | null;
}

export interface DeviceDetailEntry extends Device {
  book_id: string;
  book_name: string;
}

export interface DeviceDetail {
  rustdesk_id: string;
  online: boolean;
  last_seen: string | null;
  last_ip: string;
  discovered: DiscoveredDevice | null;
  info: DeviceInfo | null;
  entries: DeviceDetailEntry[];
  sources: string[];
}

export interface BulkFailure {
  id: string;
  error: string;
}

export interface BulkDeleteResult {
  deleted: string[];
  failed: BulkFailure[];
}

export interface BulkTagsResult {
  updated: string[];
  failed: BulkFailure[];
  added: string[];
  removed: string[];
}

export interface Book {
  id: string;
  name: string;
  type: string;
  rule: number;
  devices: number;
  online: number;
  offline: number;
  unknown: number;
}

export interface PanelUser {
  id: string;
  username: string;
  display_name: string;
  is_admin: boolean;
  is_disabled: boolean;
}

export interface Stats {
  devices: number;
  online: number;
  offline: number;
  unknown: number;
  discovered: number;
  discovered_online: number;
}

export interface Page<T> {
  total: number;
  data: T[];
}

/** Flutter ARGB uint -> css hex */
export function colorCss(v: number): string {
  const r = (v >> 16) & 0xff;
  const g = (v >> 8) & 0xff;
  const b = v & 0xff;
  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`;
}

/** Pick a readable foreground for a tag colour (WCAG relative luminance). */
export function textOnColor(hex: string): string {
  const h = hex.replace('#', '');
  const channel = (i: number) => {
    const c = parseInt(h.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const luminance = 0.2126 * channel(0) + 0.7152 * channel(2) + 0.0722 * channel(4);
  return luminance > 0.179 ? '#0f172a' : '#ffffff';
}

/**
 * Backend timestamps are naive UTC (SQLite DateTime) and are serialized
 * without a timezone marker. `new Date("2026-01-01T12:00:00")` would treat
 * that as local time, shifting every age by the browser's UTC offset. Treat
 * timestamps without an explicit zone as UTC.
 */
export function parseUtc(iso: string): Date {
  const s = iso.includes('T') ? iso : iso.replace(' ', 'T');
  const hasZone = /(?:[zZ]|[+-]\d{2}:?\d{2})$/.test(s);
  const normalized = s.replace(/(\.\d{3})\d+$/, '$1');
  return new Date(hasZone ? normalized : `${normalized}Z`);
}

export function relTime(iso: string | null, lang: Lang): string {
  if (!iso) return translate(lang, 'time.unknown');
  const s = Math.floor((Date.now() - parseUtc(iso).getTime()) / 1000);
  if (s < 0) return translate(lang, 'time.justNow');
  if (s < 60) return translate(lang, 'time.justNow');
  const m = Math.floor(s / 60);
  if (m < 60) return translate(lang, 'time.minAgo', { n: m });
  const h = Math.floor(m / 60);
  if (h < 24) return translate(lang, 'time.hoursAgo', { n: h });
  const d = Math.floor(h / 24);
  if (d === 1) return translate(lang, 'time.yesterday');
  return translate(lang, 'time.daysAgo', { n: d });
}
