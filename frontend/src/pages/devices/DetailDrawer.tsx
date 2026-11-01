/** Merged device card (address book + discovery + sysinfo). */
import { useCallback, useEffect, useState } from 'react';
import { api } from '../../api';
import {
  Badge, Confirm, Field, Loading, StatusDot, TagBadge, btn, btnGhost, btnGhostDanger,
  statusLabel,
} from '../../components';
import { useI18n } from '../../i18n';
import { useNotify } from '../../notifications';
import type {
  Device, DeviceDetail, DeviceDetailEntry, DiscoveredDevice, Presence,
} from '../../types';
import { absTime, freshness, lastSeenText, sourceLabel } from './format';

export function DetailDrawer({
  rid, reloadToken, isAdmin, canWriteBook, canAddToBook,
  onClose, onChanged, onEdit, onAddToBook,
}: {
  rid: string;
  reloadToken: number;
  isAdmin: boolean;
  canWriteBook: (bookId: string) => boolean;
  canAddToBook: boolean;
  onClose: () => void;
  onChanged: () => void;
  onEdit: (d: Device, bookId: string) => void;
  onAddToBook: (d: DiscoveredDevice) => void;
}) {
  const { t, lang } = useI18n();
  const { notify } = useNotify();
  const [data, setData] = useState<DeviceDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [delEntry, setDelEntry] = useState<Device | null>(null);
  const [forgetOpen, setForgetOpen] = useState(false);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const next = await api.deviceInfo(rid);
      setData(next);
      setError('');
    } catch (e) {
      if (!silent) setError(String((e as Error).message));
    } finally {
      if (!silent) setLoading(false);
    }
  }, [rid]);

  useEffect(() => { void load(); }, [load, reloadToken]);
  useEffect(() => {
    const timer = window.setInterval(() => { void load(true); }, 15000);
    return () => window.clearInterval(timer);
  }, [load]);

  const info = data?.info ?? null;
  const disc = data?.discovered ?? null;
  const entries = data?.entries ?? [];
  const primary = entries[0];
  const name = info?.hostname || primary?.alias || rid;
  const presence: Presence = data?.online ? 'online' : data?.last_seen ? 'offline' : 'unknown';
  const fresh = freshness(info, t, lang);

  const refresh = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.refreshInfo(rid);
      notify(
        true,
        data?.online
          ? t('dev.refreshOnline')
          : t('dev.refreshOffline'),
      );
      window.setTimeout(() => { void load(true); }, 8000);
    } catch (e) {
      notify(false, String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const removeEntry = async () => {
    if (!delEntry || busy) return;
    setBusy(true);
    try {
      await api.deleteEntry(delEntry.id);
      notify(true, t('dev.removedFromBook'));
      // Without a discovery row a non-admin can no longer open this card;
      // close it instead of leaving stale data on screen.
      const wasLastSource = entries.length === 1 && !disc;
      setDelEntry(null);
      onChanged();
      if (wasLastSource) onClose();
      else void load(true);
    } catch (e) {
      notify(false, String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const forget = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.forgetDiscovered(rid);
      notify(true, t('dev.discoveryRemoved'));
      setForgetOpen(false);
      onChanged();
      onClose();
    } catch (e) {
      notify(false, String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const cores = info
    ? (info.cpu_logical && info.cpu_physical
      ? t('dev.coresBoth', { logical: info.cpu_logical, physical: info.cpu_physical })
      : info.cpu_logical
        ? t('dev.coresLogical', { n: info.cpu_logical })
        : info.cpu_physical
          ? t('dev.coresPhysical', { n: info.cpu_physical })
          : '')
    : '';

  return (
    <>
      <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={onClose} role="presentation">
        <div
          className="flex h-full w-full max-w-xl flex-col overflow-y-auto bg-white text-slate-900 shadow-xl dark:bg-slate-900 dark:text-slate-100"
          onClick={(e) => e.stopPropagation()}
          role="dialog"
          aria-modal="true"
          aria-label={t('dev.device', { id: rid })}
        >
          <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-slate-200 bg-white px-5 py-4 dark:border-slate-800 dark:bg-slate-900">
            <div className="min-w-0">
              <h2 className="truncate text-lg font-bold">{name}</h2>
              <p className="font-mono text-xs text-slate-500 dark:text-slate-400">{rid}</p>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <span className="inline-flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
                  <StatusDot p={presence} lastSeen={data?.last_seen ?? null} />
                  {statusLabel(presence, data?.last_seen ?? null, lang)}
                </span>
                {data?.sources.includes('address_book') && <Badge tone="slate">{t('dev.sectionBook')}</Badge>}
                {data?.sources.includes('discovery') && <Badge tone="green">{t('dev.tabDiscovered')}</Badge>}
                {data?.sources.includes('sysinfo') && <Badge tone="blue">{t('dev.clientReport')}</Badge>}
              </div>
            </div>
            <button
              onClick={onClose}
              aria-label={t('common.close')}
              className="rounded border border-slate-200 px-2 py-0.5 text-sm text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"
            >
              ✕
            </button>
          </div>

          <div className="flex-1 space-y-5 px-5 py-4">
            {error && (
              <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
                {error}
                <button onClick={() => { void load(); }} className="ml-2 underline">{t('common.retry')}</button>
              </div>
            )}
            {!data && loading && <Loading text={t('dev.loadingDevice')} />}
            {!data && !loading && !error && <p className="text-sm text-slate-500 dark:text-slate-400">{t('dev.noData')}</p>}

            {data && (
              <>
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{t('dev.connection')}</h3>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
                    <Field label={t('dev.status')} value={statusLabel(presence, data.last_seen, lang)} />
                    <Field label={t('dev.lastSeen')} value={lastSeenText(data.last_seen, lang)} />
                    <Field label={t('dev.ip')} value={data.last_ip} mono />
                    <Field
                      label={t('dev.detectedVia')}
                      value={disc ? sourceLabel(disc.source) : ''}
                      fallback={entries.length > 0 ? t('dev.addressBookHeartbeat') : t('dev.notAvailable')}
                    />
                    <Field label={t('dev.firstSeen')} value={disc?.first_seen ? absTime(disc.first_seen, lang) : ''} />
                    <Field label={t('dev.lastConnected')} value={disc?.last_connected ? absTime(disc.last_connected, lang) : ''} />
                    <Field label={t('dev.lastDisconnected')} value={disc?.last_disconnected ? absTime(disc.last_disconnected, lang) : ''} />
                    <Field
                      label={t('dev.addressBooks')}
                      value={entries.map((e) => e.book_name).join(', ')}
                      fallback={t('dev.notInVisibleBook')}
                    />
                  </dl>
                </section>

                <section>
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{t('dev.system')}</h3>
                    <Badge tone={fresh.tone} title={fresh.title}>{fresh.label}</Badge>
                  </div>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
                    <Field label={t('dev.hostname')} value={info?.hostname || primary?.hostname || ''} />
                    <Field label={t('dev.username')} value={info?.username || primary?.username || ''} />
                    <Field label={t('dev.operatingSystem')} value={info?.os || primary?.platform || ''} />
                    <Field label={t('dev.osFamily')} value={info?.os_name || ''} />
                    <Field label={t('dev.osVersion')} value={info?.os_version || ''} />
                    <Field label={t('dev.clientVersion')} value={info?.version || ''} />
                    <Field label={t('dev.reportUploaded')} value={info?.collected_at ? lastSeenText(info.collected_at, lang) : ''} />
                    <Field
                      label={t('dev.lastHeartbeat')}
                      value={info?.last_heartbeat_at ? lastSeenText(info.last_heartbeat_at, lang) : ''}
                      fallback={t('dev.noHeartbeat')}
                    />
                  </dl>
                </section>

                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{t('dev.hardware')}</h3>
                  <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
                    <Field label={t('dev.cpu')} value={info?.cpu_model || info?.cpu || ''} hint={info?.cpu} />
                    <Field label={t('dev.frequency')} value={info?.cpu_freq_ghz ? `${info.cpu_freq_ghz} GHz` : ''} />
                    <Field label={t('dev.cores')} value={cores} />
                    <Field
                      label={t('dev.totalRam')}
                      value={info?.memory_gb ? `${info.memory_gb} GB` : info?.memory || ''}
                    />
                  </dl>
                </section>

                <div className="rounded-lg border border-dashed border-slate-300 p-3 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
                  <div className="mb-1 font-medium text-slate-600 dark:text-slate-300">
                    {t('dev.notProvidedTitle')}
                  </div>
                  <div className="mb-2 flex flex-wrap gap-1">
                    {[t('dev.fieldArchitecture'), t('dev.fieldRamUsage'), t('dev.fieldGpu'), t('dev.fieldDisks'), t('dev.fieldNetwork')].map((x) => (
                      <Badge key={x} tone="slate">{x}</Badge>
                    ))}
                  </div>
                  {t('dev.notProvidedNote')}
                </div>

                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{t('dev.sectionBook')}</h3>
                  {entries.length === 0 ? (
                    <p className="text-sm text-slate-500 dark:text-slate-400">{t('dev.notInVisibleBook')}</p>
                  ) : (
                    <div className="space-y-2">
                      {entries.map((e: DeviceDetailEntry) => (
                        <div key={e.id} className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <div className="min-w-0">
                              <div className="truncate font-medium">{e.alias || e.rustdesk_id}</div>
                              <div className="text-xs text-slate-500 dark:text-slate-400">
                                {e.book_name} · {statusLabel(e.presence, e.last_seen, lang)}
                              </div>
                              {e.tag_objs.length > 0 && (
                                <div className="mt-1 flex flex-wrap gap-1">
                                  {e.tag_objs.map((tag) => <TagBadge key={tag.id} name={tag.name} color={tag.color} />)}
                                </div>
                              )}
                            </div>
                            <div className="flex gap-1">
                              <button
                                className={btnGhost}
                                onClick={() => onEdit(e, e.book_id)}
                                disabled={!canWriteBook(e.book_id)}
                              >
                                {t('common.edit')}
                              </button>
                              <button
                                className={btnGhostDanger}
                                onClick={() => setDelEntry(e)}
                                disabled={!canWriteBook(e.book_id)}
                              >
                                {t('common.delete')}
                              </button>
                            </div>
                          </div>
                          {e.note && (
                            <p className="mt-2 whitespace-pre-wrap text-xs text-slate-500 dark:text-slate-400">{e.note}</p>
                          )}
                          <div className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                            {e.password_configured ? t('dev.storedPassword') : t('dev.noStoredPassword')}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </section>
              </>
            )}
          </div>

          <div className="sticky bottom-0 flex flex-wrap gap-2 border-t border-slate-200 bg-white px-5 py-3 dark:border-slate-800 dark:bg-slate-900">
            <button className={btn} onClick={() => { void refresh(); }} disabled={busy || !data}>
              {busy ? t('common.working') : t('dev.refreshInfo')}
            </button>
            {disc && disc.in_books.length === 0 && (
              <button
                className={btnGhost}
                onClick={() => onAddToBook(disc)}
                disabled={!canAddToBook}
                title={canAddToBook ? undefined : t('dev.noWritableBooks')}
              >
                {t('dev.addToBook')}
              </button>
            )}
            {isAdmin && disc && (
              <button className={btnGhostDanger} onClick={() => setForgetOpen(true)}>{t('dev.forget')}</button>
            )}
            <button className={`${btnGhost} ml-auto`} onClick={onClose}>{t('common.close')}</button>
          </div>
        </div>
      </div>

      {delEntry && (
        <Confirm
          text={t('dev.removeConfirm', { name: delEntry.alias || delEntry.rustdesk_id })}
          yesLabel={t('common.remove')}
          busy={busy}
          onYes={() => { void removeEntry(); }}
          onNo={() => setDelEntry(null)}
        />
      )}
      {forgetOpen && (
        <Confirm
          text={t('dev.forgetConfirm', { id: rid })}
          yesLabel={t('dev.forget')}
          busy={busy}
          onYes={() => { void forget(); }}
          onNo={() => setForgetOpen(false)}
        />
      )}
    </>
  );
}

