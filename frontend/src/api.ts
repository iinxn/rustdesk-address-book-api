import type {
  AuditEvent, AuditMeta, Book, BulkDeleteResult, BulkTagsResult, Device, DeviceDetail,
  DiscoveredDevice, Page, PanelUser, Stats, TagRow,
} from './types';

const KEY = 'ab_token';
const USER = 'ab_user';

export type SessionUser = { username: string; displayName?: string; isAdmin: boolean };

export const getToken = () => localStorage.getItem(KEY) || '';
export const setSession = (token: string, username: string, isAdmin: boolean, displayName = '') => {
  localStorage.setItem(KEY, token);
  localStorage.setItem(USER, JSON.stringify({ username, displayName, isAdmin }));
};
/** Update only the cached display name after the profile dialog saves it. */
export const setDisplayName = (displayName: string) => {
  const u = sessionUser();
  if (u) localStorage.setItem(USER, JSON.stringify({ ...u, displayName }));
};
export const clearSession = () => {
  localStorage.removeItem(KEY);
  localStorage.removeItem(USER);
};
export const sessionUser = (): SessionUser | null => {
  try {
    return JSON.parse(localStorage.getItem(USER) || 'null');
  } catch {
    return null;
  }
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, msg: string) {
    super(msg);
    this.status = status;
  }
}

// --- request bodies (mirror app/schemas/panel.py) ---------------------------

export interface EntryInput { rustdesk_id: string; alias: string; note: string; tags: string[]; password: string }
export interface TagInput { name: string; color: number }
export interface UserCreate { username: string; password: string; is_admin: boolean; display_name: string }
/** Empty/absent `password` keeps the current one. */
export type UserPatch = Partial<UserCreate & { is_disabled: boolean }>;
export interface DiscoveredAddInput { book_id: string; alias: string; note: string; tags: string[] }
export interface DiscoveredQuery { search?: string; status?: string; page?: number; page_size?: number; only_unlinked?: number }
type Query = Record<string, string | number | undefined>;
type Ok = { ok: boolean };

/** Query string without empty values; `repeat` adds a key once per value (e.g. tag=a&tag=b). */
function qs(q: Query, repeat: Record<string, string[]> = {}): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v !== '' && v !== undefined) p.set(k, String(v));
  for (const [k, values] of Object.entries(repeat)) for (const v of values) p.append(k, v);
  return p.toString();
}

const enc = encodeURIComponent;

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getToken()}`,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 401) {
    clearSession();
    location.hash = '#/login';
    throw new ApiError(401, 'Unauthorized');
  }
  const text = await r.text();
  let data: Record<string, unknown> = {};
  try {
    data = text ? (JSON.parse(text) as Record<string, unknown>) : {};
  } catch {
    data = {};
  }
  if (!r.ok) throw new ApiError(r.status, String(data.detail || data.error || `HTTP ${r.status}`));
  return data as T;
}

export const api = {
  login: (username: string, password: string) =>
    req<{ access_token: string; user: { name: string; display_name: string; is_admin: boolean } }>(
      'POST', '/api/login', { username, password, type: 'account' },
    ),
  stats: () => req<Stats>('GET', '/api/v1/stats'),
  books: () => req<Book[]>('GET', '/api/v1/address-books'),
  createBook: (name: string) => req<unknown>('POST', '/api/v1/address-books', { name }),
  renameBook: (id: string, name: string) => req<unknown>('PUT', `/api/v1/address-books/${id}`, { name }),
  deleteBook: (id: string) => req<Ok>('DELETE', `/api/v1/address-books/${id}`),
  entries: (bid: string, q: Query, tags: string[] = []) =>
    req<Page<Device>>('GET', `/api/v1/address-books/${bid}/entries?${qs(q, { tag: tags })}`),
  createEntry: (bid: string, b: EntryInput) => req<Device>('POST', `/api/v1/address-books/${bid}/entries`, b),
  updateEntry: (id: string, b: EntryInput) => req<Device>('PUT', `/api/v1/entries/${id}`, b),
  deleteEntry: (id: string) => req<Ok>('DELETE', `/api/v1/entries/${id}`),
  bulkDelete: (ids: string[]) => req<BulkDeleteResult>('POST', '/api/v1/entries/bulk-delete', { ids }),
  bulkTags: (ids: string[], add: string[], remove: string[]) =>
    req<BulkTagsResult>('POST', '/api/v1/entries/bulk-tags', { ids, add, remove }),
  discovered: (q: DiscoveredQuery) => req<Page<DiscoveredDevice>>('GET', `/api/v1/discovered?${qs({ ...q })}`),
  addDiscovered: (rid: string, b: DiscoveredAddInput) =>
    req<Device>('POST', `/api/v1/discovered/${enc(rid)}/add`, b),
  forgetDiscovered: (rid: string) => req<Ok>('DELETE', `/api/v1/discovered/${enc(rid)}`),
  deviceInfo: (rid: string) => req<DeviceDetail>('GET', `/api/v1/device-info/${enc(rid)}`),
  refreshInfo: (rid: string) =>
    req<{ ok: boolean; expires_in: number }>('POST', `/api/v1/device-info/${enc(rid)}/refresh`),
  tags: (bid: string) => req<TagRow[]>('GET', `/api/v1/address-books/${bid}/tags`),
  createTag: (bid: string, b: TagInput) => req<unknown>('POST', `/api/v1/address-books/${bid}/tags`, b),
  updateTag: (id: string, b: TagInput) => req<unknown>('PUT', `/api/v1/tags/${id}`, b),
  deleteTag: (id: string) => req<Ok>('DELETE', `/api/v1/tags/${id}`),
  users: () => req<PanelUser[]>('GET', '/api/v1/users'),
  createUser: (b: UserCreate) => req<unknown>('POST', '/api/v1/users', b),
  updateUser: (id: string, b: UserPatch) => req<unknown>('PUT', `/api/v1/users/${id}`, b),
  deleteUser: (id: string) => req<Ok>('DELETE', `/api/v1/users/${id}`),
  me: () => req<PanelUser>('GET', '/api/v1/me'),
  updateMe: (displayName: string) => req<PanelUser>('PUT', '/api/v1/me', { display_name: displayName }),
  auditMeta: () => req<AuditMeta>('GET', '/api/v1/audit/meta'),
  audit: (q: Query) => req<Page<AuditEvent>>('GET', `/api/v1/audit?${qs(q)}`),
  auditEvent: (id: string) => req<AuditEvent>('GET', `/api/v1/audit/${enc(id)}`),
};
