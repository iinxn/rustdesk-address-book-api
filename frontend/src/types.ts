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
  customer_id: string | null;
  customer: { id: string; name: string } | null;
  tags: string[];
  tag_objs: TagObj[];
  presence: Presence;
  last_seen: string | null;
  password_configured: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface Book {
  id: string;
  name: string;
  type: string;
  devices: number;
  online: number;
  offline: number;
  unknown: number;
}

export interface Customer {
  id: string;
  name: string;
  note: string;
  devices: number;
}

export interface PanelUser {
  id: string;
  username: string;
  is_admin: boolean;
  is_disabled: boolean;
}

export interface Stats {
  devices: number;
  online: number;
  offline: number;
  unknown: number;
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

export function relTime(iso: string | null): string {
  if (!iso) return 'Unknown';
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 0) return 'just now';
  if (s < 60) return 'just now';
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d === 1) return 'yesterday';
  return `${d} days ago`;
}
