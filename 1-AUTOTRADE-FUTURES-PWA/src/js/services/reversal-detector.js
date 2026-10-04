/**
 * 🔄 آشکارساز برگشت روند — الگوهای V (کف) و Λ (سقف)
 * ---------------------------------------------------------------------------
 * خواستهٔ داداش هادی: «از روی داده‌ها، جاهایی که بازار تغییر روند می‌دهد پیدا کن و
 * بهترین الگوریتم برای شکل‌های \/ و /\ هر ارز را بیاب» — این ماژول خالص است و هم
 * در چارت زنده (ناحیه‌های احتمالی خرید/فروش) و هم در ابزار تحلیل (reversal-lab)
 * استفاده می‌شود تا تعریف «برگشت» در همه‌جا یکی باشد.
 *
 * روش: پیوت‌های فراکتالی (high/low محلی با پنجرهٔ left/right) → زیک‌زاگ متناوب
 * با فیلتر حداقل نوسان → جفت‌کردن پیوت‌ها:
 *   V (کف برگشتی):   سقف قبل → کف (با افت ≥ vDepthPct) → سقف بعد (با رشد ≥ vDepthPct)
 *   Λ (سقف برگشتی):  کف قبل  → سقف (با رشد ≥ vDepthPct) → کف بعد (با افت ≥ vDepthPct)
 */

export const DEFAULT_REVERSAL_PARAMS = {
  left: 3,          // کندل‌های قبل از پیوت که باید از آن‌ها فرق داشته باشد
  right: 3,         // کندل‌های بعد از پیوت
  minSwingPct: 1.2, // حداقل نوسان بین پیوت‌های متوالی (٪) — زیک‌زاگ
  vDepthPct: 2.0    // حداقل عمق هر بازوی الگوی V/Λ (٪)
};

/** پیوت‌های فراکتالی خام — high/low محلی با پنجرهٔ [i-left, i+right] */
export function findRawPivots(candles, { left = 3, right = 3 } = {}) {
  const out = [];
  const n = candles.length;
  for (let i = 0; i < n; i += 1) {
    const hi = Number(candles[i].high);
    const lo = Number(candles[i].low);
    if (![hi, lo].every(Number.isFinite)) continue;
    let isHigh = true;
    let isLow = true;
    for (let j = Math.max(0, i - left); j <= Math.min(n - 1, i + right); j += 1) {
      if (j === i) continue;
      const h = Number(candles[j].high);
      const l = Number(candles[j].low);
      if (Number.isFinite(h) && h > hi) isHigh = false;
      if (Number.isFinite(l) && l < lo) isLow = false;
      if (!isHigh && !isLow) break;
    }
    if (isHigh) out.push({ i, ts: candles[i].ts, price: hi, type: 'high' });
    else if (isLow) out.push({ i, ts: candles[i].ts, price: lo, type: 'low' });
  }
  return out;
}

/**
 * زیک‌زاگ متناوب: پیوت‌های هم‌نوعِ پشت‌سرهم به экстروم‌ترِ آن‌ها فشرده می‌شوند و
 * نوسان‌های ریز (< minSwingPct) حذف می‌گردند. خروجی: پیوت‌های متناوب high/low.
 */
export function zigzagPivots(candles, params = {}) {
  const { left, right, minSwingPct } = { ...DEFAULT_REVERSAL_PARAMS, ...params };
  const raw = findRawPivots(candles, { left, right });
  const chain = [];
  for (const p of raw) {
    const last = chain.at(-1);
    if (!last) { chain.push({ ...p }); continue; }
    if (last.type === p.type) {
      // هم‌نوع: اکسترمم‌تر را نگه دار
      const better = p.type === 'high' ? p.price >= last.price : p.price <= last.price;
      if (better) chain[chain.length - 1] = { ...p };
    } else {
      const swingPct = Math.abs(p.price - last.price) / last.price * 100;
      if (swingPct >= minSwingPct) chain.push({ ...p });
    }
  }
  return chain;
}

/**
 * تشخیص الگوهای V (کف برگشتی) و Λ (سقف برگشتی) از روی زیک‌زاگ.
 * هر رویداد: نوع، زمان/قیمت نقطهٔ برگشت، عمق هر بازو (٪)، طول هر بازو (کندل)،
 * قدرت الگو (می‌نیمم عمق دو بازو) و تقارن (نسبت بازوها).
 */
export function detectReversals(candles, params = {}) {
  const p = { ...DEFAULT_REVERSAL_PARAMS, ...params };
  const chain = zigzagPivots(candles, p);
  const events = [];
  for (let k = 1; k < chain.length - 1; k += 1) {
    const prev = chain[k - 1];
    const tip = chain[k];
    const next = chain[k + 1];
    if (tip.type === 'low') {
      // سقف → کف → سقف = V (کف برگشتی، فرصت خرید)
      const dropPct = (prev.price - tip.price) / prev.price * 100;
      const risePct = (next.price - tip.price) / tip.price * 100;
      if (dropPct >= p.vDepthPct && risePct >= p.vDepthPct) {
        events.push({
          kind: 'V', i: tip.i, ts: tip.ts, price: tip.price,
          leftPct: Number(dropPct.toFixed(2)), rightPct: Number(risePct.toFixed(2)),
          strengthPct: Number(Math.min(dropPct, risePct).toFixed(2)),
          leftBars: tip.i - prev.i, rightBars: next.i - tip.i,
          symmetry: Number((Math.min(dropPct, risePct) / Math.max(dropPct, risePct)).toFixed(2))
        });
      }
    } else {
      // کف → سقف → کف = Λ (سقف برگشتی، فرصت فروش/خروج)
      const risePct = (tip.price - prev.price) / prev.price * 100;
      const dropPct = (tip.price - next.price) / tip.price * 100;
      if (risePct >= p.vDepthPct && dropPct >= p.vDepthPct) {
        events.push({
          kind: 'L', i: tip.i, ts: tip.ts, price: tip.price,
          leftPct: Number(risePct.toFixed(2)), rightPct: Number(dropPct.toFixed(2)),
          strengthPct: Number(Math.min(risePct, dropPct).toFixed(2)),
          leftBars: tip.i - prev.i, rightBars: next.i - tip.i,
          symmetry: Number((Math.min(risePct, dropPct) / Math.max(risePct, dropPct)).toFixed(2))
        });
      }
    }
  }
  return events;
}

/**
 * ناحیه‌های احتمالی خرید/فروش برای چارت — از V/Λهای اخیر، باندهای قیمتی
 * (حمایت/مقاومت) می‌سازد. خروجی: { kind:'buy'|'sell', priceLow, priceHigh, ts, strengthPct }
 */
export function reversalZones(candles, params = {}, lookback = 60) {
  const events = detectReversals(candles, params);
  const recent = events.filter(e => e.i >= candles.length - lookback);
  const pad = (candles, pct) => {
    const prices = candles.slice(-lookback).flatMap(c => [Number(c.high), Number(c.low)]).filter(Number.isFinite);
    const mid = prices.length ? (Math.max(...prices) + Math.min(...prices)) / 2 : 0;
    return mid > 0 ? mid * pct / 100 : 0;
  };
  const padAbs = Math.max(pad(candles, 0.25), 1e-9);
  return recent.map(e => ({
    kind: e.kind === 'V' ? 'buy' : 'sell',
    priceLow: e.kind === 'V' ? e.price - padAbs * 1.6 : e.price - padAbs * 0.6,
    priceHigh: e.kind === 'V' ? e.price + padAbs * 0.6 : e.price + padAbs * 1.6,
    ts: e.ts, i: e.i,
    strengthPct: e.strengthPct, symmetry: e.symmetry
  }));
}
