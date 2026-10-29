import { useEffect, useState } from 'react';

export function useDebounce<T>(v: T, ms = 250): T {
  const [s, setS] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setS(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return s;
}

/**
 * Theme preference. Light is the default for a fresh browser profile; dark is
 * opt-in and remembered. `main.tsx` applies the saved class before the first
 * paint, so there is no flash of the wrong theme.
 */
export function useTheme() {
  const [dark, setDark] = useState(() => localStorage.getItem('ab_theme') === 'dark');
  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    localStorage.setItem('ab_theme', dark ? 'dark' : 'light');
  }, [dark]);
  return { dark, toggle: () => setDark((d) => !d) };
}
