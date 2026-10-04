import { timeframeMs } from '../core/utils.js';

/**
 * فیلتر تاییدیه هم‌جهتی کندل‌های ریز (Consecutive Micro-Candle Momentum Filter)
 * ---------------------------------------------------------------------------
 * منطق کاملاً خالص (Pure) و بدون وابستگی به DOM/Network است تا هم در تست
 * خودکار (test/selftest.mjs) و هم در مرورگر بدون تغییر اجرا شود.
 *
 * ورودی: آرایه کندل‌های تایم‌فریم ریز (مثلاً 1m) به ترتیب زمانی صعودی (قدیمی → جدید).
 * فقط کندل‌های «بسته‌شده» شرکت می‌کنند؛ کندل در حال تشکیل با تلورانس ۲ ثانیه‌ای
 * ساعت، از محاسبه کنار گذاشته می‌شود.
 *
 * خروجی: جهت هم‌جهتی ('LONG' | 'SHORT' | null)، طول استریک واقعی و وضعیت داده.
 */
export function computeMicroStreak(candles, count, tfMs, now = Date.now()) {
  const result = { available: false, direction: null, streak: 0, count, closedCount: 0 };
  if (!Array.isArray(candles) || !Number.isFinite(count) || !Number.isFinite(tfMs)) return result;

  const closed = candles.filter(candle => {
    const ts = Number(candle?.ts);
    return Number.isFinite(ts) && ts + tfMs <= now + 2000;
  });
  result.closedCount = closed.length;
  if (closed.length < count) return result;
  result.available = true;

  // شمارش استریک واقعی هم‌جهت از انتهای تاریخچه (Doji یعنی close === open، استریک را می‌شکند)
  let direction = 0;
  let streak = 0;
  for (let i = closed.length - 1; i >= 0; i -= 1) {
    const open = Number(closed[i].open);
    const close = Number(closed[i].close);
    const step = close > open ? 1 : close < open ? -1 : 0;
    if (i === closed.length - 1) {
      direction = step;
      streak = step === 0 ? 0 : 1;
      if (streak === 0) break;
      continue;
    }
    if (step !== 0 && step === direction) streak += 1;
    else break;
  }
  result.streak = streak;
  if (direction === 1 && streak >= count) result.direction = 'LONG';
  else if (direction === -1 && streak >= count) result.direction = 'SHORT';
  return result;
}

/**
 * لایه سرویس فیلتر ریز‌کندل؛ همه پارامترها از SettingsStore خوانده می‌شوند:
 *   microCandleCheck   — روشن/خاموش بودن فیلتر ('true' | 'false')
 *   microCandleCount   — تعداد کندل متوالی مورد نیاز (۲ تا ۴)
 *   microCandleTf      — تایم‌فریم ریز ('1' یا '3' دقیقه)
 *   microCandleBoostPct— وزن داینامیک درصدی هنگام تایید هم‌جهتی
 *
 * اگر دیتای ریز‌کندل در دسترس نباشد، فیلتر «خنثی» می‌ماند (نه امتیاز مثبت، نه منفی)
 * و علتش در reason ثبت می‌شود تا روی کارت ارز شفاف نمایش داده شود.
 */
export class MicroCandleFilter {
  constructor(settings) {
    this.s = settings;
  }

  enabled() {
    return String(this.s.value.microCandleCheck) === 'true';
  }

  evaluate(microData, now = Date.now()) {
    const s = this.s.value;
    const count = Math.max(2, Math.min(4, Number(s.microCandleCount) || 3));
    const tf = String(s.microCandleTf || '1');
    const out = {
      active: this.enabled(),
      tf,
      count,
      direction: null,
      streak: 0,
      tag: '—',
      reason: ''
    };
    if (!out.active) return out;

    const info = computeMicroStreak(microData?.candles, count, timeframeMs(tf), now);
    if (!info.available) {
      out.tag = 'NO DATA';
      out.reason = `دیتای کندل ریز ${tf}m کافی نیست؛ فیلتر خنثی ماند`;
      return out;
    }

    out.streak = info.streak;
    if (info.direction === 'LONG') {
      out.direction = 'LONG';
      out.tag = `${info.streak}×${tf}m ↑`;
      out.reason = `${info.streak} کندل ${tf}m صعودی متوالی`;
    } else if (info.direction === 'SHORT') {
      out.direction = 'SHORT';
      out.tag = `${info.streak}×${tf}m ↓`;
      out.reason = `${info.streak} کندل ${tf}m نزولی متوالی`;
    } else {
      out.tag = `${info.streak}×${tf}m ~`;
      out.reason = `هم‌جهتی ${count} کندل ریز تایید نشد (فقط ${info.streak} کندل هم‌جهت)`;
    }
    return out;
  }
}
