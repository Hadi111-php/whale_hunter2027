export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

export const clone = value => JSON.parse(JSON.stringify(value));

export const fmt = (value, decimals = 4) => Number.isFinite(+value)
  ? (+value).toLocaleString('en-US', { maximumFractionDigits: decimals })
  : '--';

export const pct = value => Number.isFinite(+value) ? `${(+value).toFixed(2)}%` : '--';
export const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
export const uid = () => globalThis.crypto?.randomUUID?.() || Math.random().toString(36).slice(2);
export const mean = values => {
  const finite = values.map(Number).filter(Number.isFinite);
  return finite.reduce((sum, value) => sum + value, 0) / (finite.length || 1);
};

export const timeframeMs = timeframe => {
  const value = String(timeframe).toUpperCase();
  if (value === 'D') return 24 * 60 * 60 * 1000;
  return Math.max(1, Number(value) || 1) * 60 * 1000;
};

export const readJson = (key, fallback) => {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? fallback;
  } catch {
    return fallback;
  }
};

export const writeJson = (key, value) => {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage can be disabled in private/sandboxed browser contexts.
  }
};

export const escapeHtml = value => String(value ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;');

export const toBool = value => value === true || value === 'true' || value === 1 || value === '1';

/** برچسب فارسی تایم‌فریم ('1'→'1m', '60'→'1h', ...) — برای نمایش شفاف تایم کار رادار */
export const tfLabel = tf => ({ '1': '1m', '3': '3m', '5': '5m', '15': '15m', '30': '30m', '60': '1h', '120': '2h', '240': '4h', 'D': '1D' }[String(tf)] || `${tf}m`);

/** متن خلاصهٔ موتور Ignition — شفافیت کامل: چند نماد در موتور، چند کندل‌ناموفق، چند رد، چند سیگنال */
export const ignitionSummaryText = ({ targets = 0, klineFails = 0, blocked = 0, live = 0, positions = 0 } = {}) => {
  const parts = [`${targets} نماد در موتور`];
  if (klineFails) parts.push(`${klineFails} کندل‌ناموفق ⚠️`);
  parts.push(`${blocked} رد‌شده`);
  parts.push(live ? `${live} سیگنال فعال ✅` : 'بدون سیگنال');
  parts.push(`${positions} پوزیشن باز`);
  return parts.join(' • ');
};
