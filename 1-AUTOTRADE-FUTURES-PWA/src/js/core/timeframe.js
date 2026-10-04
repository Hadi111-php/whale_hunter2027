/**
 * هم‌ترازی و اعتبارسنجی تایم‌فریم کندل‌ها — منبع واحد حقیقت برای «زمان»
 * ---------------------------------------------------------------------------
 * ریشهٔ یک اشتباه پرهزینه: تحلیل کندل ۱ساعته اما بستن معامله روی تایم ۱دقیقه.
 * این ماژول تضمین می‌کند هر کندل دقیقاً روی مرز تایم‌فریم خودش باشد، کندلِ
 * در حال تشکیل هرگز وارد تحلیل نشود و «کهنگی» آخرین کندل بسته قابل اندازه‌گیری
 * باشد — روی هر تایم‌فریمی که در Settings انتخاب شود (1m تا 1D).
 */

export const TIMEFRAMES = Object.freeze([
  { key: '1', minutes: 1, label: '1m', okx: '1m', binance: '1m' },
  { key: '3', minutes: 3, label: '3m', okx: '3m', binance: '3m' },
  { key: '5', minutes: 5, label: '5m', okx: '5m', binance: '5m' },
  { key: '15', minutes: 15, label: '15m', okx: '15m', binance: '15m' },
  { key: '30', minutes: 30, label: '30m', okx: '30m', binance: '30m' },
  { key: '60', minutes: 60, label: '1h', okx: '1H', binance: '1h' },
  { key: '120', minutes: 120, label: '2h', okx: '2H', binance: '2h' },
  { key: '240', minutes: 240, label: '4h', okx: '4H', binance: '4h' },
  { key: 'D', minutes: 1440, label: '1D', okx: '1D', binance: '1d' }
]);

const BY_KEY = new Map(TIMEFRAMES.map(tf => [tf.key, tf]));

export function tfInfo(key) {
  const k = String(key ?? '').toUpperCase();
  return BY_KEY.get(k) || { key: k, minutes: Math.max(1, Number(k) || 60), label: `${k}m`, okx: '1H', binance: '1h' };
}

export function tfMs(key) {
  return tfInfo(key).minutes * 60_000;
}

export function tfLabel(key) {
  return tfInfo(key).label;
}

/** رُند کردن timestamp به مرز تایم‌فریم (کندل ۱۲:۳۴:۵۶ در تایم ۱ساعته → ۱۲:۰۰) */
export function floorTs(ts, ms) {
  return Math.floor(Number(ts) / ms) * ms;
}

/** آیا کندل روی مرز تایم‌فریم است؟ (مثلاً 12:00 در تایم ۱ساعته) */
export function isAligned(ts, ms) {
  return Number(ts) % ms === 0;
}

/**
 * نرمال‌سازی کامل یک آرایه کندل برای تحلیل:
 *  ۱) floor کردن ts به مرز تایم‌فریم (رفع خطای هم‌ترازی)
 *  ۲) حذف کندل‌های تکراری (همان مرز زمانی)
 *  ۳) مرتب‌سازی صعودی
 *  ۴) حذف کندلِ در حال تشکیل (اگر dropForming=true)
 *  ۵) شمارش شکاف‌های زمانی (کندل گم‌شده)
 * خروجی: { candles, formingDropped, gaps, lastClosedTs, firstTs, lastClosedAgeMs }
 */
export function alignCandles(rawCandles, { ms, now = Date.now(), dropForming = true } = {}) {
  const tfMillis = Math.max(60_000, Number(ms) || 3_600_000);
  const byTs = new Map();
  for (const raw of rawCandles || []) {
    if (!raw) continue;
    const ts = floorTs(Number(raw.ts), tfMillis);
    if (![ts, raw.open, raw.high, raw.low, raw.close, raw.volume].every(Number.isFinite)) continue;
    const candle = { ...raw, ts };
    const existing = byTs.get(ts);
    // اگر تکراری بود، جدیدترین نسخه (آخرین ورودی) را نگه دار
    if (!existing || (Number(raw.volume) || 0) >= (Number(existing.volume) || 0)) byTs.set(ts, candle);
  }
  const sorted = [...byTs.values()].sort((a, b) => a.ts - b.ts);

  let formingDropped = false;
  let candles = sorted;
  if (dropForming && candles.length) {
    const last = candles.at(-1);
    // کندل در حال تشکیل: مرزش شروع شده ولی هنوز به پایان نرسیده
    if (last.ts + tfMillis > now + 2000) {
      candles = candles.slice(0, -1);
      formingDropped = true;
    }
  }

  let gaps = 0;
  for (let i = 1; i < candles.length; i += 1) {
    if (candles[i].ts - candles[i - 1].ts !== tfMillis) gaps += 1;
  }

  const lastClosedTs = candles.length ? candles.at(-1).ts : null;
  return {
    candles,
    formingDropped,
    gaps,
    lastClosedTs,
    firstTs: candles.length ? candles[0].ts : null,
    // کهنگی = مدت زمان گذشته از «بسته شدن» آخرین کندل (منفی یعنی هنوز باز است)
    lastClosedAgeMs: lastClosedTs !== null ? now - (lastClosedTs + tfMillis) : null
  };
}

/** عمر انسانی‌شدهٔ کندل بسته برای نمایش روی کارت: «۴ دقیقه پیش» */
export function describeAge(ageMs) {
  if (!Number.isFinite(ageMs)) return '--';
  const minutes = Math.max(0, Math.round(ageMs / 60_000));
  if (minutes < 1) return 'همین الان';
  if (minutes < 60) return `${minutes} دقیقه پیش`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} ساعت و ${minutes % 60} دقیقه پیش`;
  return `${Math.floor(hours / 24)} روز پیش`;
}
