/** Display helpers shared by the Devices page and its dialogs. */
import type { Lang, TKey } from '../../i18n';
import { parseUtc, relTime } from '../../types';
import type { DeviceInfo } from '../../types';

export type TFn = (key: TKey, vars?: Record<string, string | number>) => string;

export function absTime(iso: string | null, lang: Lang): string {
  return iso ? parseUtc(iso).toLocaleString(lang === 'ru' ? 'ru-RU' : 'en-US') : '';
}

export function lastSeenText(iso: string | null, lang: Lang): string {
  return iso ? `${absTime(iso, lang)} (${relTime(iso, lang)})` : '';
}

export function sourceLabel(source: string): string {
  if (!source) return '';
  return source.split(',').map((s) => (s === 'tcp' ? 'TCP' : s === 'udp' ? 'UDP' : s)).join(' + ');
}

export function freshness(info: DeviceInfo | null, t: TFn, lang: Lang): { tone: 'green' | 'amber' | 'slate'; label: string; title: string } {
  if (!info || !info.collected_at) {
    return {
      tone: 'slate',
      label: t('dev.freshNo'),
      title: t('dev.freshNoTitle'),
    };
  }
  const age = Date.now() - parseUtc(info.collected_at).getTime();
  if (age > 24 * 60 * 60 * 1000) {
    return { tone: 'amber', label: t('dev.freshStale'), title: t('dev.lastUploaded', { time: absTime(info.collected_at, lang) }) };
  }
  return { tone: 'green', label: t('dev.freshFresh'), title: t('dev.lastUploaded', { time: absTime(info.collected_at, lang) }) };
}
