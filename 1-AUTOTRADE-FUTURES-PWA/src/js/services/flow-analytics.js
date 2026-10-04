/**
 * 🐋 تحلیل جریان (Flow Analytics) — فاکتورهای «ضد‌نهنگ» از دیتای واقعی صرافی
 * ---------------------------------------------------------------------------
 * برگرفته از تحلیل نهنگ‌ها (فایل «دیپسیک تحلیل نهنگها» §۴):
 * سیگنال‌های عرفی (حجم/RSI/کندل) برای ریتیل نوشته شده‌اند و نهنگ‌ها از آن‌ها
 * سوءاستفاده می‌کنند. فاکتورهای غیرعرف — CVD (دلتای حجم خرید تیکری)، نسبت خرید
 * تیکری، شتاب تعداد معاملات — لایهٔ دوم حقیقت‌سنجی هستند.
 *
 * منبع داده: کندل‌های Binance دو فیلد اضافه دارند (تعداد ترید و حجم خریدِ تیکری).
 * بدون هیچ API key اضافه. اگر منبع این فیلدها را ندهد (Bybit/OKX)، available=false
 * می‌شود و هیچ چیز ساختگی تولید نمی‌شود (Zero Fake Data).
 */

export const FLOW_WINDOW = 6; // پنجرهٔ سنجش جریان (کندل)

/**
 * محاسبهٔ متریک‌های جریان از کندل‌های دارای فیلدهای تیکری.
 * خروجی: { available, window, buyRatio, cvdDelta, tradeAccel, longAligned, shortAligned }
 *   buyRatio   — سهم خرید تیکری از کل حجم پنجره (۰..۱)؛ ~۰.۵ = تعادل
 *   cvdDelta   — ΔCVD پنجره = حجم خرید تیکری − حجم فروش تیکری (مثبت = فشار خرید واقعی)
 *   tradeAccel — تعداد ترید کندل آخر ÷ میانگین پنجره (>۱ = شتاب‌گیری فعالیت)
 *   longAligned/shortAligned — هم‌جهتی جریان با جهت پیشنهادی (فلسفهٔ ضد‌نهنگ)
 */
export function computeFlowMetrics(candles, { window = FLOW_WINDOW } = {}) {
  const rows = (Array.isArray(candles) ? candles : []).filter(c => c
    && Number.isFinite(Number(c.takerBuy))
    && Number.isFinite(Number(c.trades))
    && Number.isFinite(Number(c.volume)));
  if (rows.length < 3) {
    return { available: false, reason: 'منبع کندل فیلد تیکری ندارد (Bybit/OKX) — فقط Binance' };
  }
  const win = rows.slice(-Math.max(3, Number(window) || FLOW_WINDOW));
  const vol = win.reduce((acc, c) => acc + Number(c.volume), 0);
  const takerBuy = win.reduce((acc, c) => acc + Number(c.takerBuy), 0);
  const cvdDelta = takerBuy - (vol - takerBuy);
  const buyRatio = vol > 0 ? takerBuy / vol : 0.5;
  const prev = win.slice(0, -1);
  const tradesAvg = prev.length ? prev.reduce((acc, c) => acc + Number(c.trades), 0) / prev.length : 0;
  const tradeAccel = tradesAvg > 0 ? Number(win.at(-1).trades) / tradesAvg : 1;
  return {
    available: true,
    window: win.length,
    buyRatio: Number(buyRatio.toFixed(4)),
    cvdDelta: Number(cvdDelta.toFixed(4)),
    tradeAccel: Number(tradeAccel.toFixed(2)),
    longAligned: buyRatio >= 0.55 && cvdDelta > 0,
    shortAligned: buyRatio <= 0.45 && cvdDelta < 0
  };
}

/** متن خلاصهٔ فارسی برای why سیگنال */
export function flowWhyText(flow) {
  if (!flow?.available) return '';
  const side = flow.longAligned ? 'خرید' : flow.shortAligned ? 'فروش' : 'تعادل';
  return `جریان: ${Math.round(flow.buyRatio * 100)}٪ خریدِ تیکری، CVD ${flow.cvdDelta > 0 ? 'مثبت' : 'منفی'} (${side} — ضد‌نهنگ)`;
}
