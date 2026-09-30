import { useEffect, useState } from 'react';

export function useDebounce<T>(v: T, ms = 250): T {
  const [s, setS] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setS(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return s;
}

export function useTheme() {
  const [dark, setDark] = useState(() => localStorage.getItem('ab_theme') !== 'light');
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    localStorage.setItem('ab_theme', dark ? 'dark' : 'light');
  }, [dark]);
  return { dark, toggle: () => setDark((d) => !d) };
}

export interface Toast {
  id: number;
  ok: boolean;
  text: string;
}

let nextId = 1;
export function useToasts() {
  const [items, setItems] = useState<Toast[]>([]);
  const push = (ok: boolean, text: string) => {
    const id = nextId++;
    setItems((l) => [...l, { id, ok, text }]);
    setTimeout(() => setItems((l) => l.filter((t) => t.id !== id)), 3500);
  };
  return { items, push };
}
