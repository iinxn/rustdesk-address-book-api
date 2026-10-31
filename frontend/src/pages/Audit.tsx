import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import {
  Badge,
  Field,
  Layout,
  LoadError,
  Loading,
  Modal,
  Pagination,
  btn,
  btnGhost,
  input,
} from '../components';
import { useDebounce, useTheme } from '../hooks';
import { useI18n } from '../i18n';
import type { TKey } from '../i18n';
import { parseUtc } from '../types';
import type { AuditEvent, AuditMeta } from '../types';

const SIZE = 50;
const RID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

function dateStart(value: string): string {
  if (!value) return '';
  return new Date(`${value}T00:00:00`).toISOString();
}

function dateEnd(value: string): string {
  if (!value) return '';
  return new Date(`${value}T23:59:59.999`).toISOString();
}

function fmtTime(iso: string | null, lang: 'ru' | 'en'): string {
  if (!iso) return '—';
  const d = parseUtc(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(lang === 'ru' ? 'ru-RU' : 'en-GB', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function outcomeTone(outcome: string): 'green' | 'red' | 'amber' | 'slate' {
  if (outcome === 'success') return 'green';
  if (outcome === 'denied' || outcome === 'error') return 'red';
  if (outcome === 'partial') return 'amber';
  return 'slate';
}

function categoryTone(category: string): 'green' | 'red' | 'amber' | 'blue' | 'slate' {
  if (category === 'auth' || category === 'access' || category === 'connection') return 'blue';
  if (category === 'device') return 'green';
  if (category === 'data') return 'amber';
  if (category === 'security') return 'red';
  return 'slate';
}

function detail(e: AuditEvent, key: string): string {
  const value = e.details?.[key];
  return typeof value === 'string' ? value : '';
}

/** "касса (123456789)", or just the id when no name is known. */
function deviceText(name: string, id: string): string {
  if (!id) return '';
  return name && name !== id ? `${name} (${id})` : id;
}

export default function Audit() {
  const { dark, toggle } = useTheme();
  const { t, lang } = useI18n();
  const nav = useNavigate();
  const [meta, setMeta] = useState<AuditMeta | null>(null);
  const [rows, setRows] = useState<AuditEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<'desc' | 'asc'>('desc');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [actor, setActor] = useState('');
  const [sourceIp, setSourceIp] = useState('');
  const [category, setCategory] = useState('');
  const [eventType, setEventType] = useState('');
  const [targetType, setTargetType] = useState('');
  const [targetId, setTargetId] = useState('');
  const [outcome, setOutcome] = useState('');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<AuditEvent | null>(null);

  const actorQ = useDebounce(actor);
  const ipQ = useDebounce(sourceIp);
  const targetQ = useDebounce(targetId);
  const searchQ = useDebounce(search);

  useEffect(() => {
    api.auditMeta().then(setMeta).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const data = await api.audit({
        page,
        page_size: SIZE,
        sort,
        category,
        event_type: eventType,
        actor: actorQ,
        source_ip: ipQ,
        target_type: targetType,
        target_id: targetQ,
        outcome,
        search: searchQ,
        since: dateStart(from),
        until: dateEnd(to),
      });
      setRows(data.data);
      setTotal(data.total);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [page, sort, category, eventType, actorQ, ipQ, targetType, targetQ, outcome, searchQ, from, to]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setPage(1);
  }, [sort, category, eventType, actorQ, ipQ, targetType, targetQ, outcome, searchQ, from, to]);

  const eventLabel = (type: string): string => {
    const key = `audit.evt.${type}` as TKey;
    const value = t(key);
    return value === key ? type : value;
  };
  const categoryLabel = (value: string): string => {
    const key = `audit.category.${value}` as TKey;
    const label = t(key);
    return label === key ? value : label;
  };
  const outcomeLabel = (value: string): string => {
    const key = `audit.outcome.${value}` as TKey;
    const label = t(key);
    return label === key ? value : label;
  };
  const actorTypeLabel = (value: string): string => {
    const key = `audit.actorType.${value}` as TKey;
    const label = t(key);
    return label === key ? value : label;
  };

  const categories = useMemo(
    () => meta?.categories ?? ['access', 'auth', 'connection', 'device', 'data', 'security', 'system'],
    [meta],
  );
  const outcomes = useMemo(
    () => meta?.outcomes ?? ['success', 'denied', 'error', 'partial', 'unknown'],
    [meta],
  );

  const reset = () => {
    setFrom('');
    setTo('');
    setActor('');
    setSourceIp('');
    setCategory('');
    setEventType('');
    setTargetType('');
    setTargetId('');
    setOutcome('');
    setSearch('');
    setSort('desc');
    setPage(1);
  };

  const openDevice = (rid: string) => {
    sessionStorage.setItem('ab_device', rid);
    setSelected(null);
    nav('/');
  };

  const optLabel = (key: string, fallback: string): string => {
    const label = t(key as TKey);
    return label === key ? fallback : label;
  };

  const isConnection = (e: AuditEvent) => e.category === 'connection';
  const connTo = (e: AuditEvent) => deviceText(detail(e, 'to_name'), e.target_id);
  const connFrom = (e: AuditEvent) => deviceText(detail(e, 'from_name'), detail(e, 'from_id'));
  const connUserKnown = (e: AuditEvent) => e.actor_type === 'user';
  const connType = (e: AuditEvent) => {
    const value = detail(e, 'conn_type');
    return value ? optLabel(`audit.connection.type.${value}`, value) : '';
  };
  const connSummary = (e: AuditEvent) =>
    connUserKnown(e)
      ? t('audit.connection.summary', { user: e.actor_name || e.actor_id, device: connTo(e) })
      : t('audit.connection.summaryUnknown', { device: connTo(e) });

  const actorText = (e: AuditEvent) => {
    if (isConnection(e) && !connUserKnown(e)) {
      return connFrom(e) || t('audit.connection.unknownSource');
    }
    return e.actor_name || e.actor_id || t('audit.unknown');
  };

  const destinationText = (e: AuditEvent) => {
    if (isConnection(e)) return connTo(e) || '—';
    const route = e.route || e.destination || '—';
    const target = e.target_id
      ? `${e.target_type || t('audit.target')}: ${e.target_id}`
      : '';
    return target ? `${route} · ${target}` : route;
  };

  const selectClass = `${input} pr-7`;

  return (
    <Layout dark={dark} onTheme={toggle}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h1 className="text-xl font-bold">{t('audit.title')}</h1>
          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
            {t('audit.subtitle')}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {meta?.enabled === false ? (
            <Badge tone="red">{t('audit.retentionOff')}</Badge>
          ) : (
            <Badge tone="slate">
              {t('audit.retention', { days: meta?.retention_days ?? 90 })}
            </Badge>
          )}
          <button
            type="button"
            onClick={() => setSort((s) => (s === 'desc' ? 'asc' : 'desc'))}
            className={btnGhost}
            title={t('audit.sortTime')}
          >
            {sort === 'desc' ? `↓ ${t('audit.sortDesc')}` : `↑ ${t('audit.sortAsc')}`}
          </button>
        </div>
      </div>

      <section className="mb-3 rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
        <div className="mb-2 flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">{t('audit.filters')}</h2>
          <button type="button" onClick={reset} className={`${btnGhost} px-2 py-1 text-xs`}>
            {t('audit.reset')}
          </button>
        </div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <label className="text-xs">
            <span className="mb-0.5 block text-slate-500 dark:text-slate-400">{t('audit.periodFrom')}</span>
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={input} />
          </label>
          <label className="text-xs">
            <span className="mb-0.5 block text-slate-500 dark:text-slate-400">{t('audit.periodTo')}</span>
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className={input} />
          </label>
          <label className="text-xs">
            <span className="mb-0.5 block text-slate-500 dark:text-slate-400">{t('audit.actor')}</span>
            <input
              value={actor}
              onChange={(e) => setActor(e.target.value)}
              placeholder={t('audit.actorPlaceholder')}
              className={input}
            />
          </label>
          <label className="text-xs">
            <span className="mb-0.5 block text-slate-500 dark:text-slate-400">{t('audit.sourceIp')}</span>
            <input
              value={sourceIp}
              onChange={(e) => setSourceIp(e.target.value)}
              placeholder={t('audit.sourceIpPlaceholder')}
              className={input}
            />
          </label>
          <label className="text-xs">
            <span className="mb-0.5 block text-slate-500 dark:text-slate-400">{t('audit.category')}</span>
            <select value={category} onChange={(e) => setCategory(e.target.value)} className={selectClass}>
              <option value="">{t('audit.allCategories')}</option>
              {categories.map((value) => (
                <option key={value} value={value}>{categoryLabel(value)}</option>
              ))}
            </select>
          </label>
          <label className="text-xs">
            <span className="mb-0.5 block text-slate-500 dark:text-slate-400">{t('audit.eventType')}</span>
            <select value={eventType} onChange={(e) => setEventType(e.target.value)} className={selectClass}>
              <option value="">{t('audit.allEventTypes')}</option>
              {(meta?.event_types ?? []).map((value) => (
                <option key={value} value={value}>{eventLabel(value)}</option>
              ))}
            </select>
          </label>
          <label className="text-xs">
            <span className="mb-0.5 block text-slate-500 dark:text-slate-400">{t('audit.targetType')}</span>
            <select value={targetType} onChange={(e) => setTargetType(e.target.value)} className={selectClass}>
              <option value="">{t('audit.allTargetTypes')}</option>
              {(meta?.target_types ?? []).map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
          </label>
          <label className="text-xs">
            <span className="mb-0.5 block text-slate-500 dark:text-slate-400">{t('audit.targetId')}</span>
            <input
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
              placeholder={t('audit.targetIdPlaceholder')}
              className={input}
            />
          </label>
          <label className="text-xs">
            <span className="mb-0.5 block text-slate-500 dark:text-slate-400">{t('audit.outcome')}</span>
            <select value={outcome} onChange={(e) => setOutcome(e.target.value)} className={selectClass}>
              <option value="">{t('audit.allOutcomes')}</option>
              {outcomes.map((value) => (
                <option key={value} value={value}>{outcomeLabel(value)}</option>
              ))}
            </select>
          </label>
          <label className="text-xs sm:col-span-2 lg:col-span-3">
            <span className="mb-0.5 block text-slate-500 dark:text-slate-400">{t('audit.search')}</span>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('audit.searchPlaceholder')}
              className={input}
            />
          </label>
          <div className="flex items-end">
            <button type="button" onClick={() => void load()} className={btn}>
              {t('common.retry')}
            </button>
          </div>
        </div>
      </section>

      {loading ? (
        <Loading text={t('audit.loading')} />
      ) : failed ? (
        <LoadError onRetry={() => void load()} />
      ) : rows.length === 0 ? (
        <p className="py-10 text-center text-sm text-slate-500 dark:text-slate-400">
          {t('audit.empty')}
        </p>
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
            <table className="w-full min-w-[64rem] text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:text-slate-400">
                <tr>
                  <th className="px-3 py-2 font-medium">{t('audit.time')}</th>
                  <th className="px-3 py-2 font-medium">{t('audit.actorCol')}</th>
                  <th className="px-3 py-2 font-medium">{t('audit.source')}</th>
                  <th className="px-3 py-2 font-medium">{t('audit.event')}</th>
                  <th className="px-3 py-2 font-medium">{t('audit.destination')}</th>
                  <th className="px-3 py-2 font-medium">{t('audit.result')}</th>
                  <th className="px-3 py-2 font-medium">{t('audit.details')}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr
                    key={e.id}
                    onClick={() => setSelected(e)}
                    onKeyDown={(ev) => {
                      if (ev.key === 'Enter' || ev.key === ' ') {
                        ev.preventDefault();
                        setSelected(e);
                      }
                    }}
                    tabIndex={0}
                    className="cursor-pointer border-b border-slate-100 align-top last:border-0 hover:bg-slate-50 focus:bg-slate-50 focus:outline-none dark:border-slate-800 dark:hover:bg-slate-800/60 dark:focus:bg-slate-800/60"
                  >
                    <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-600 dark:text-slate-300">
                      {fmtTime(e.timestamp, lang)}
                    </td>
                    <td className="px-3 py-2">
                      <div className="max-w-[14rem] truncate" title={actorText(e)}>{actorText(e)}</div>
                      <Badge tone="slate">{actorTypeLabel(e.actor_type)}</Badge>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-slate-600 dark:text-slate-300">
                      {e.source_ip || '—'}
                    </td>
                    <td className="px-3 py-2">
                      <div className="font-medium">{eventLabel(e.event_type)}</div>
                      {isConnection(e) && connType(e) && (
                        <div className="text-xs text-slate-500 dark:text-slate-400">{connType(e)}</div>
                      )}
                      <Badge tone={categoryTone(e.category)}>{categoryLabel(e.category)}</Badge>
                    </td>
                    <td className="max-w-[20rem] px-3 py-2 text-xs text-slate-600 dark:text-slate-300">
                      <div
                        className={isConnection(e) ? 'truncate font-medium text-slate-800 dark:text-slate-100' : 'truncate'}
                        title={destinationText(e)}
                      >
                        {destinationText(e)}
                      </div>
                      <div className="font-mono text-[11px] text-slate-500 dark:text-slate-400">
                        {isConnection(e) ? e.target_id || '—' : e.request_id || '—'}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <Badge tone={outcomeTone(e.outcome)}>{outcomeLabel(e.outcome)}</Badge>
                      {e.status_code !== null && (
                        <div className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                          HTTP {e.status_code}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs text-blue-700 dark:text-blue-400">
                      {t('audit.details')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex justify-end">
            <Pagination page={page} total={total} size={SIZE} onPage={setPage} />
          </div>
        </>
      )}

      {selected && (
        <Modal
          title={t('audit.detailsTitle')}
          subtitle={fmtTime(selected.timestamp, lang)}
          onClose={() => setSelected(null)}
          size="lg"
          footer={
            <>
              {isConnection(selected) && RID_RE.test(detail(selected, 'from_id')) && (
                <button
                  type="button"
                  onClick={() => openDevice(detail(selected, 'from_id'))}
                  className={btnGhost}
                >
                  {t('audit.openSourceDevice')}
                </button>
              )}
              {selected.target_type === 'device' && RID_RE.test(selected.target_id) && (
                <button
                  type="button"
                  onClick={() => openDevice(selected.target_id)}
                  className={btn}
                >
                  {t('audit.openDevice')}
                </button>
              )}
              <button type="button" onClick={() => setSelected(null)} className={btnGhost}>
                {t('common.close')}
              </button>
            </>
          }
        >
          {isConnection(selected) && (
            <div className="mb-4 rounded-md border border-blue-200 bg-blue-50 p-3 dark:border-blue-900 dark:bg-blue-950/40">
              <p className="text-sm font-medium text-slate-800 dark:text-slate-100">{connSummary(selected)}</p>
              <dl className="mt-3 grid gap-3 sm:grid-cols-2">
                <Field
                  label={t('audit.connection.user')}
                  value={connUserKnown(selected) ? selected.actor_name || selected.actor_id : ''}
                />
                <Field
                  label={t('audit.connection.actorSource')}
                  value={optLabel(
                    `audit.connection.actorSource.${detail(selected, 'actor_source')}`,
                    detail(selected, 'actor_source'),
                  )}
                />
                <Field label={t('audit.connection.from')} value={connFrom(selected)} mono />
                <Field label={t('audit.connection.to')} value={connTo(selected)} mono />
                <Field label={t('audit.connection.connType')} value={connType(selected)} />
                <Field
                  label={t('audit.connection.via')}
                  value={optLabel(`audit.connection.${detail(selected, 'via')}`, detail(selected, 'via'))}
                />
              </dl>
              <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">{t('audit.connection.hint')}</p>
            </div>
          )}
          <dl className="grid gap-3 sm:grid-cols-2">
            <Field label={t('audit.event')} value={eventLabel(selected.event_type)} />
            <Field label={t('audit.category')} value={categoryLabel(selected.category)} />
            <Field label={t('audit.actorCol')} value={actorText(selected)} />
            <Field label={t('audit.source')} value={selected.source_ip} mono />
            <Field label={t('audit.destination')} value={selected.destination} />
            <Field label={t('audit.route')} value={selected.route} mono />
            <Field label={t('audit.method')} value={selected.http_method} mono />
            <Field
              label={t('audit.status')}
              value={selected.status_code === null ? '' : String(selected.status_code)}
              mono
            />
            <Field
              label={t('audit.duration')}
              value={selected.duration_ms === null ? '' : `${selected.duration_ms} ms`}
            />
            <Field
              label={t('audit.target')}
              value={selected.target_id
                ? `${selected.target_type || t('audit.target')}: ${selected.target_id}`
                : ''}
              mono
            />
            <Field label={t('audit.requestId')} value={selected.request_id} mono />
            <Field label={t('audit.result')} value={outcomeLabel(selected.outcome)} />
          </dl>
          <div className="mt-4">
            <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
              {t('audit.details')}
            </div>
            <pre className="max-h-72 overflow-auto rounded-md bg-slate-50 p-3 text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-200">
              {JSON.stringify(selected.details ?? {}, null, 2)}
            </pre>
          </div>
        </Modal>
      )}
    </Layout>
  );
}
