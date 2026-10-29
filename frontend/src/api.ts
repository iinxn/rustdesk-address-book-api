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
      'POST',
      '/api/login',
      {
        username,
        password,
        type: 'account',
      },
    ),
  stats: () => req<import('./types').Stats>('GET', '/api/v1/stats'),
  books: () => req<import('./types').Book[]>('GET', '/api/v1/address-books'),
  createBook: (name: string) => req<unknown>('POST', '/api/v1/address-books', { name }),
  renameBook: (id: string, name: string) => req<unknown>('PUT', `/api/v1/address-books/${id}`, { name }),
  deleteBook: (id: string) => req<{ ok: boolean }>('DELETE', `/api/v1/address-books/${id}`),
  entries: (bid: string, q: Record<string, string | number>) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(q)) if (v !== '' && v !== undefined) p.set(k, String(v));
    return req<import('./types').Page<import('./types').Device>>('GET', `/api/v1/address-books/${bid}/entries?${p}`);
  },
  entriesWithTags: (bid: string, q: Record<string, string | number>, tags: string[]) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(q)) if (v !== '' && v !== undefined) p.set(k, String(v));
    for (const t of tags) p.append('tag', t);
    return req<import('./types').Page<import('./types').Device>>('GET', `/api/v1/address-books/${bid}/entries?${p}`);
  },
  createEntry: (bid: string, b: unknown) => req<import('./types').Device>('POST', `/api/v1/address-books/${bid}/entries`, b),
  updateEntry: (id: string, b: unknown) => req<import('./types').Device>('PUT', `/api/v1/entries/${id}`, b),
  deleteEntry: (id: string) => req<{ ok: boolean }>('DELETE', `/api/v1/entries/${id}`),
  bulkDelete: (ids: string[]) =>
    req<import('./types').BulkDeleteResult>('POST', '/api/v1/entries/bulk-delete', { ids }),
  bulkTags: (ids: string[], add: string[], remove: string[]) =>
    req<import('./types').BulkTagsResult>('POST', '/api/v1/entries/bulk-tags', { ids, add, remove }),
  discovered: (q: { search?: string; status?: string; page?: number; page_size?: number; only_unlinked?: number }) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(q)) if (v !== '' && v !== undefined) p.set(k, String(v));
    return req<import('./types').Page<import('./types').DiscoveredDevice>>('GET', `/api/v1/discovered?${p}`);
  },
  addDiscovered: (rid: string, b: unknown) =>
    req<import('./types').Device>('POST', `/api/v1/discovered/${encodeURIComponent(rid)}/add`, b),
  forgetDiscovered: (rid: string) =>
    req<{ ok: boolean }>('DELETE', `/api/v1/discovered/${encodeURIComponent(rid)}`),
  deviceInfo: (rid: string) =>
    req<import('./types').DeviceDetail>('GET', `/api/v1/device-info/${encodeURIComponent(rid)}`),
  refreshInfo: (rid: string) =>
    req<{ ok: boolean; expires_in: number }>('POST', `/api/v1/device-info/${encodeURIComponent(rid)}/refresh`),
  tags: (bid: string) => req<import('./types').TagRow[]>('GET', `/api/v1/address-books/${bid}/tags`),
  createTag: (bid: string, b: unknown) => req<unknown>('POST', `/api/v1/address-books/${bid}/tags`, b),
  updateTag: (id: string, b: unknown) => req<unknown>('PUT', `/api/v1/tags/${id}`, b),
  deleteTag: (id: string) => req<{ ok: boolean }>('DELETE', `/api/v1/tags/${id}`),
  users: () => req<import('./types').PanelUser[]>('GET', '/api/v1/users'),
  createUser: (b: unknown) => req<unknown>('POST', '/api/v1/users', b),
  updateUser: (id: string, b: unknown) => req<unknown>('PUT', `/api/v1/users/${id}`, b),
  deleteUser: (id: string) => req<{ ok: boolean }>('DELETE', `/api/v1/users/${id}`),
  me: () => req<import('./types').PanelUser>('GET', '/api/v1/me'),
  updateMe: (displayName: string) =>
    req<import('./types').PanelUser>('PUT', '/api/v1/me', { display_name: displayName }),
};
