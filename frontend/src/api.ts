const KEY = 'ab_token';
const USER = 'ab_user';

export const getToken = () => localStorage.getItem(KEY) || '';
export const setSession = (token: string, username: string, isAdmin: boolean) => {
  localStorage.setItem(KEY, token);
  localStorage.setItem(USER, JSON.stringify({ username, isAdmin }));
};
export const clearSession = () => {
  localStorage.removeItem(KEY);
  localStorage.removeItem(USER);
};
export const sessionUser = (): { username: string; isAdmin: boolean } | null => {
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
  const data = text ? JSON.parse(text) : {};
  if (!r.ok) throw new ApiError(r.status, data.detail || data.error || `HTTP ${r.status}`);
  return data as T;
}

export const api = {
  login: (username: string, password: string) =>
    req<{ access_token: string; user: { name: string; is_admin: boolean } }>('POST', '/api/login', {
      username,
      password,
      type: 'account',
    }),
  stats: () => req<import('./types').Stats>('GET', '/api/v1/stats'),
  books: () => req<import('./types').Book[]>('GET', '/api/v1/address-books'),
  createBook: (name: string) => req<unknown>('POST', '/api/v1/address-books', { name }),
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
  tags: (bid: string) => req<import('./types').TagRow[]>('GET', `/api/v1/address-books/${bid}/tags`),
  createTag: (bid: string, b: unknown) => req<unknown>('POST', `/api/v1/address-books/${bid}/tags`, b),
  updateTag: (id: string, b: unknown) => req<unknown>('PUT', `/api/v1/tags/${id}`, b),
  deleteTag: (id: string) => req<{ ok: boolean }>('DELETE', `/api/v1/tags/${id}`),
  customers: () => req<import('./types').Customer[]>('GET', '/api/v1/customers'),
  createCustomer: (b: unknown) => req<unknown>('POST', '/api/v1/customers', b),
  updateCustomer: (id: string, b: unknown) => req<unknown>('PUT', `/api/v1/customers/${id}`, b),
  deleteCustomer: (id: string) => req<{ ok: boolean }>('DELETE', `/api/v1/customers/${id}`),
  users: () => req<import('./types').PanelUser[]>('GET', '/api/v1/users'),
  createUser: (b: unknown) => req<unknown>('POST', '/api/v1/users', b),
  updateUser: (id: string, b: unknown) => req<unknown>('PUT', `/api/v1/users/${id}`, b),
  deleteUser: (id: string) => req<{ ok: boolean }>('DELETE', `/api/v1/users/${id}`),
};
