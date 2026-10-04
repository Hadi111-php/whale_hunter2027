import { clamp, mean, timeframeMs } from '../core/utils.js';

/**
 * موتور ورود Ignition — مخصوص پمپ/دامپ، متفاوت از موتور اجماع اتوتریدر.
 *
 * تفاوت‌های کلیدی با استراتژی اسکالپ معمولی:
 *  - فقط روی نمادهای «کشف‌شده توسط رادار» کار می‌کند (جهت از رادار می‌آید)
 *  - تایم‌فریم ریز (1m/3m) — پمپ/دامپ پنجره عمر کوتاهی دارد
 *  - فیلتر RSI دوطرفه: نه بازار مرده (rsi < min) نه دمِ انفجاری (rsi > max)
 *  - تاییدیه استریک ریز‌کندل هم‌جهت با جهت کشف رادار
 *  - ماکسیمم زمان نگهداری کوتاه (پیش‌فرض ۴۵ دقیقه)
 */
export class IgnitionStrategy {
  constructor(settings) {
    this.s = settings;
  }

  atr(candles, length = 14) {
    const ranges = [];
    for (let i = 1; i < candles.length; i += 1) {
      const c = candles[i];
      const p = candles[i - 1];
      ranges.push(Math.max(c.high - c.low, Math.abs(c.high - p.close), Math.abs(c.low - p.close)));
    }
    return mean(ranges.slice(-length));
  }

  rsi(candles, period = 14) {
    if (candles.length <= period) return 50;
    let gains = 0, losses = 0;
    for (let i = 1; i <= period; i += 1) {
      const diff = candles[i].close - candles[i - 1].close;
      if (diff >= 0) gains += diff; else losses -= diff;
    }
    let avgGain = gains / period;
    let avgLoss = losses / period;
    for (let i = period + 1; i < candles.length; i += 1) {
      const diff = candles[i].close - candles[i - 1].close;
      if (diff >= 0) {
        avgGain = (avgGain * (period - 1) + diff) / period;
        avgLoss = (avgLoss * (period - 1)) / period;
      } else {
        avgGain = (avgGain * (period - 1)) / period;
        avgLoss = (avgLoss * (period - 1) - diff) / period;
      }
    }
    if (avgLoss === 0) return 100;
    return 100 - (100 / (1 + avgGain / avgLoss));
  }

  ema(candles, period) {
    if (candles.length < period) return candles.at(-1)?.close || 0;
    const k = 2 / (period + 1);
    let e = candles.slice(0, period).reduce((sum, c) => sum + c.close, 0) / period;
    for (let i = period; i < candles.length; i += 1) e = candles[i].close * k + e * (1 - k);
    return e;
  }

  // استریک هم‌جهت کندل‌های بسته‌شده (مشابه فیلتر ریز‌کندل اتوتریدر)
  streak(candles, tfMs, now = Date.now()) {
    const closed = candles.filter(c => Number(c.ts) + tfMs <= now + 2000);
    let dir = 0, n = 0;
    for (let i = closed.length - 1; i >= 0; i -= 1) {
      const step = closed[i].close > closed[i].open ? 1 : closed[i].close < closed[i].open ? -1 : 0;
      if (i === closed.length - 1) {
        dir = step;
        n = step === 0 ? 0 : 1;
        if (n === 0) break;
        continue;
      }
      if (step !== 0 && step === dir) n += 1;
      else break;
    }
    return { direction: dir === 1 ? 'LONG' : dir === -1 ? 'SHORT' : null, streak: n };
  }

  /**
   * @param {Object} rec رکورد رادار { symbol, side: 'LONG'|'SHORT', changePct, basis }
   * @param {Object} klines خروجی MarketClient.getKlines { candles, source }
   */
  analyze(rec, klines, now = Date.now()) {
    const s = this.s.value;
    const out = {
      symbol: rec.symbol,
      radarSide: rec.side,
      radarChangePct: rec.changePct,
      side: 'WAIT',
      score: 0,
      why: [],
      source: klines?.source || '--'
    };
    const candles = klines?.candles;
    if (!Array.isArray(candles) || candles.length < 30) {
      out.why = ['دیتای کندل ریز کافی نیست'].join('، ');
      return out;
    }

    const tfMs = timeframeMs(s.entryTimeframe);
    const last = candles.at(-1);
    const price = Number(last.close);
    const atr = this.atr(candles);
    const rsi = this.rsi(candles);
    const emaFast = this.ema(candles, 9);
    const emaSlow = this.ema(candles, 21);
    const avgVol = mean(candles.slice(-25, -1).map(c => c.volume));
    const volumeX = avgVol > 0 ? last.volume / avgVol : 0;
    const st = this.streak(candles, tfMs, now);

    const wantLong = rec.side === 'LONG';
    let score = 0;

    // ۱) جهت رادار خودش امتیاز پایه می‌دهد — کشف پمپ/دامپ ملاک اصلی است
    score += 30;
    out.why.push(`رادار: ${rec.changePct >= 0 ? '+' : ''}${rec.changePct.toFixed(1)}٪ ${wantLong ? 'پمپ' : 'دامپ'}`);

    // ۲) ساختار روند ریز‌تایم باید با جهت کشف هم‌جهت باشد
    if (wantLong && emaFast > emaSlow) { score += 18; out.why.push('EMA ریز‌تایم صعودی'); }
    if (!wantLong && emaFast < emaSlow) { score += 18; out.why.push('EMA ریز‌تایم نزولی'); }

    // ۳) انفجار حجم — بدون حجم، ادامه‌دار بودن پمپ/دامپ نامعتبر است
    if (volumeX >= Number(s.ignitionVolumeX)) {
      score += 20;
      out.why.push(`حجم ${volumeX.toFixed(1)}x`);
    }

    // ۴) تاییدیه استریک ریز‌کندل هم‌جهت (پارامتریک)
    const needStreak = String(s.ignitionMicroCheck) === 'true' ? Math.max(1, Number(s.ignitionMicroCount) || 2) : 0;
    if (needStreak === 0) {
      score += 10;
    } else if (st.direction === rec.side && st.streak >= needStreak) {
      score += 22;
      out.why.push(`${st.streak} کندل هم‌جهت متوالی`);
    } else {
      out.why.push(`استریک هم‌جهت تایید نشد (${st.streak})`);
    }

    // ۵) فیلتر دوطرفه RSI — نه مرده، نه دم انفجاری (ورود دیرهنگام ممنوع)
    const rsiMin = Number(s.ignitionRsiMin);
    const rsiMax = Number(s.ignitionRsiMax);
    const rsiOk = wantLong ? rsi >= rsiMin && rsi <= rsiMax : rsi <= 100 - rsiMin && rsi >= 100 - rsiMax;
    if (rsiOk) {
      score += 10;
      out.why.push(`RSI ${rsi.toFixed(0)}`);
    } else {
      out.why.push(`RSI ${rsi.toFixed(0)} خارج از پنجره ورود`);
    }

    out.score = clamp(Math.round(score), 0, 100);
    if (out.score >= Number(s.ignitionMinScore) && rsiOk) {
      out.side = rec.side;
    }

    // پلن معامله فقط وقتی سمت قطعی است
    if (out.side !== 'WAIT') {
      const direction = out.side === 'LONG' ? 1 : -1;
      const stopDistance = Math.max(atr * Number(s.ignitionAtrStopMult), price * 0.002);
      const entry = price * (1 + direction * (Number(s.slippagePct) / 100));
      const stop = entry - direction * stopDistance;
      const take = entry + direction * stopDistance * Number(s.ignitionTakeProfitR);
      const notional = Number(s.orderMargin) * Number(s.leverage);
      const qty = notional / entry;
      const feeOpen = notional * (Number(s.feeOpenPct) / 100);
      const feeClose = notional * (Number(s.feeClosePct) / 100);
      out.entry = entry;
      out.stop = stop;
      out.take = take;
      out.qty = qty;
      out.notional = notional;
      out.fee = feeOpen + feeClose;
      out.atr = atr;
      out.rsi = rsi;
      out.volumeX = volumeX;
      out.signalId = `${rec.symbol}:${last.ts}:${out.side}`;
    }
    out.why = out.why.join('، ');
    return out;
  }
}
