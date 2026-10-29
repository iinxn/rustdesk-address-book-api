import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

/**
 * Global, non-blocking notifications.
 *
 * `notify(true, text)` / `notify(false, text)` can be called from any component
 * below `<NotificationProvider>`; the host is rendered once, above every page
 * and modal (`z-[100]`), and is `pointer-events-none`, so it never covers a
 * control or shifts the layout.
 *
 * Each toast is visible for `VISIBLE_MS`, then plays the exit animation and is
 * removed. Timers are tracked so unmounting the provider cannot leave stray
 * `setTimeout` callbacks behind.
 */
export type NoticeKind = 'success' | 'error';

type Notice = {
  id: number;
  kind: NoticeKind;
  text: string;
  leaving: boolean;
};

type NotifyValue = {
  notify: (ok: boolean, text: string) => void;
  notifySuccess: (text: string) => void;
  notifyError: (text: string) => void;
};

const VISIBLE_MS = 2600;
const LEAVE_MS = 220;
const MAX_VISIBLE = 5;

const NotificationContext = createContext<NotifyValue | null>(null);

let nextId = 1;

export function NotificationProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Notice[]>([]);
  const timers = useRef<number[]>([]);

  useEffect(
    () => () => {
      timers.current.forEach((id) => window.clearTimeout(id));
      timers.current = [];
    },
    [],
  );

  const notify = useCallback((ok: boolean, text: string) => {
    const id = nextId++;
    setItems((list) => {
      const notice: Notice = { id, kind: ok ? 'success' : 'error', text, leaving: false };
      const next = [...list, notice];
      return next.length > MAX_VISIBLE ? next.slice(next.length - MAX_VISIBLE) : next;
    });

    const leave = window.setTimeout(() => {
      setItems((list) => list.map((n) => (n.id === id ? { ...n, leaving: true } : n)));
      const remove = window.setTimeout(() => {
        setItems((list) => list.filter((n) => n.id !== id));
      }, LEAVE_MS);
      timers.current.push(remove);
    }, VISIBLE_MS);
    timers.current.push(leave);
  }, []);

  const value = useMemo<NotifyValue>(
    () => ({
      notify,
      notifySuccess: (text) => notify(true, text),
      notifyError: (text) => notify(false, text),
    }),
    [notify],
  );

  return (
    <NotificationContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed inset-x-0 top-3 z-[100] flex flex-col items-center gap-2 px-3"
      >
        {items.map((n) => (
          <div
            key={n.id}
            role="status"
            className={`pointer-events-none flex w-full max-w-md items-start gap-2 rounded-lg px-4 py-2.5 text-sm font-medium text-white shadow-lg ring-1 ring-black/10 ${
              n.kind === 'success' ? 'bg-green-700' : 'bg-red-700'
            } ${n.leaving ? 'toast-out' : 'toast-in'}`}
          >
            <span aria-hidden="true" className="mt-px shrink-0 font-bold">
              {n.kind === 'success' ? '✓' : '!'}
            </span>
            <span className="min-w-0 break-words">{n.text}</span>
          </div>
        ))}
      </div>
    </NotificationContext.Provider>
  );
}

export function useNotify(): NotifyValue {
  const ctx = useContext(NotificationContext);
  if (!ctx) throw new Error('useNotify must be used inside <NotificationProvider>');
  return ctx;
}
