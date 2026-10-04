import { clamp, mean } from '../core/utils.js';
import { tfMs as tfMilliseconds, tfLabel } from '../core/timeframe.js';
import { MicroCandleFilter } from './micro-candle.js';
import { evaluateFormula } from './formula-engine.js';
import { computeFlowMetrics, flowWhyText } from './flow-analytics.js';


export class MomentumScalpStrategy {
  constructor(settings) {
    this.s = settings;
    this.micro = new MicroCandleFilter(settings);
  }

  atr(candles, length = 14) {
    const ranges = [];
    for (let i = 1; i < candles.length; i += 1) {
      const current = candles[i];
      const previous = candles[i - 1];
      ranges.push(Math.max(
        current.high - current.low,
        Math.abs(current.high - previous.close),
        Math.abs(current.low - previous.close)
      ));
    }
    return mean(ranges.slice(-length));
  }

  rsi(candles, period = 14) {
    if (candles.length <= period) return 50;
    let gains = 0, losses = 0;
    for (let i = 1; i <= period; i++) {
      const diff = candles[i].close - candles[i - 1].close;
      if (diff >= 0) gains += diff;
      else losses -= diff;
    }
    let avgGain = gains / period;
    let avgLoss = losses / period;
    for (let i = period + 1; i < candles.length; i++) {
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
    const rs = avgGain / avgLoss;
    return 100 - (100 / (1 + rs));
  }

  ema(candles, period = 20) {
    if (candles.length < period) return candles.at(-1)?.close || 0;
    const k = 2 / (period + 1);
    let emaVal = candles.slice(0, period).reduce((sum, c) => sum + c.close, 0) / period;
    for (let i = period; i < candles.length; i++) {
      emaVal = candles[i].close * k + emaVal * (1 - k);
    }
    return emaVal;
  }

  fee(notional, percentage) {
    return Math.abs(notional) * (Number(percentage) / 100);
  }

  evaluateCustomFormula(code, ctx) {
    try {
      const fn = new Function('ctx', `
        with(ctx) {
          ${code.includes('return') ? code : 'return (' + code + ');'}
        }
      `);
      return fn(ctx);
    } catch (err) {
      return { error: err.message };
    }
  }

  analyze(market) {
    const s = this.s.value;
    const candles = market.candles;
    const last = candles.at(-1);
    if (!last) {
      return {
        symbol: market.symbol, source: market.source, price: Number(market.price || 0), side: 'WAIT', score: 0,
        why: 'کندلی برای تحلیل موجود نیست', movePct: 0, oneCandlePct: 0, volX: 0, atr: 0, atrPct: 0, rsi: 50,
        emaFast: 0, emaSlow: 0, entry: 0, stop: null, take: null, qty: 0, notional: 0, fee: 0, risk: 0, reward: 0,
        candleTs: 0, signalId: `${market.symbol}:0:WAIT`, microTag: '—', stale: true, formulaValue: null,
        tfMs: Number(market.tfMs) || 0, ts: Date.now()
      };
    }
    const previous = candles.at(-2);
    const fourBack = candles.at(-4);
    const price = Number(market.price || last.close);

    // --- ⏱ گیت هم‌ترازی و تازگی کندل (رفع باگ «تحلیل کندل کهنه/باز») ---
    const ms = Number(market.tfMs) || tfMilliseconds(s.timeframe);
    const now = Number(market.receivedAt) || Date.now();
    const candleClosedAgeMs = now - (Number(last.ts) + ms);
    const staleLimitMs = ms * 3 + 60_000;
    const stale = candleClosedAgeMs > staleLimitMs;

    const movePct = ((last.close - fourBack.close) / fourBack.close) * 100;
    const oneCandlePct = ((last.close - previous.close) / previous.close) * 100;
    const averageVolume = mean(candles.slice(-28, -1).map(candle => candle.volume));
    const volumeX = last.volume / (averageVolume || last.volume || 1);
    const atr = this.atr(candles);
    const atrPct = (atr / price) * 100;
    const rsiVal = this.rsi(candles, 14);
    const emaFast = this.ema(candles, 9);
    const emaSlow = this.ema(candles, 21);
    const rangeHighs = candles.slice(-24, -2).map(candle => candle.high);
    const rangeLows = candles.slice(-24, -2).map(candle => candle.low);
    const breakoutUp = last.close > Math.max(...rangeHighs);
    const breakoutDown = last.close < Math.min(...rangeLows);
    const bodyPct = Math.abs(last.close - last.open) / (last.open || 1) * 100;
    const emaRatio = emaSlow ? emaFast / emaSlow : 1;
    const recent = candles.slice(-8);
    const trendUp = recent.filter((candle, index, array) => index > 0 && candle.close > array[index - 1].close).length >= 5;
    const trendDown = recent.filter((candle, index, array) => index > 0 && candle.close < array[index - 1].close).length >= 5;

    // --- فیلتر تاییدیه هم‌جهتی کندل‌های ریز (Micro-Candle Momentum Filter) ---
    // وزن داینامیک درصدی فقط به همان سمتِ هم‌جهت با استریک ریز‌کندل‌ها اضافه می‌شود.
    const micro = this.micro.evaluate(market.microCandles);
    // 🐋 تحلیل جریان ضد‌نهنگ (فقط وقتی منبع، فیلدهای تیکری دارد — Binance)
    const flow = computeFlowMetrics(market.candles);
    const microBoost = 1 + (Number(s.microCandleBoostPct) || 0) / 100;

    let longScore = 0;
    let shortScore = 0;
    const reasons = [];
    const minimumMove = Number(s.minMovePct);

    // --- 🧮 فرمول‌ساز پارامتریک (سه حالت: off / filter / signal) ---
    const formulaMode = String(s.formulaMode || 'off');
    const formulaCtx = {
      price,
      movePct,
      oneCandlePct,
      volX: volumeX,
      atr,
      atrPct,
      rsi: rsiVal,
      emaFast,
      emaSlow,
      emaRatio,
      bodyPct,
      breakoutUp: breakoutUp ? 1 : 0,
      breakoutDown: breakoutDown ? 1 : 0,
      trendUp: trendUp ? 1 : 0,
      trendDown: trendDown ? 1 : 0,
      microStreak: Number(micro.streak) || 0,
      microLong: micro.direction === 'LONG' ? 1 : 0,
      microShort: micro.direction === 'SHORT' ? 1 : 0,
      hourUtc: new Date(Number(last.ts)).getUTCHours(),
      buyRatio: flow.available ? flow.buyRatio : 0.5,
      cvdDelta: flow.available ? flow.cvdDelta : 0,
      tradeAccel: flow.available ? flow.tradeAccel : 1
    };
    // حالت filter: عبارت پارامتریک؛ نتیجه > 0 = اجازه ورود + پاداش امتیاز
    let formulaValue = null;
    let formulaError = null;
    let formulaBlocked = false;
    if (formulaMode === 'filter' && String(s.customFormula || '').trim()) {
      const evaluated = evaluateFormula(s.customFormula, formulaCtx);
      if (evaluated.ok) {
        formulaValue = evaluated.value;
        if (!(evaluated.value > 0)) formulaBlocked = true;
      } else {
        formulaError = evaluated.error;
        // فرمول معیوب = خنثی + علت شفاف روی کارت (هرگز کرش نمی‌کند)
      }
    }

    // حالت signal: بلوک JS کامل که {side, score, why} برمی‌گرداند (سازگار با قبل)
    if (formulaMode === 'signal' && s.customFormula && s.customFormula.trim()) {
      const customCtx = { ...formulaCtx, candles, last, symbol: market.symbol };
      const customRes = this.evaluateCustomFormula(s.customFormula, customCtx);
      if (customRes && typeof customRes === 'object' && !customRes.error) {
        if (customRes.side) {
          const side = customRes.side.toUpperCase();
          let score = clamp(Number(customRes.score) || 85, 0, 100);
          const why = customRes.why || 'فرمول سفارشی کاربر';
          // اعمال وزن داینامیک ریز‌کندل روی فرمول سفارشی — فقط در صورت هم‌جهتی با سمت سیگنال
          const microAligned = micro.active && micro.direction && micro.direction === side;
          if (microAligned) score = clamp(Math.round(score * microBoost), 0, 100);
          const whyFull = `${why}${microAligned ? ` • ${micro.reason} (+${s.microCandleBoostPct}٪)` : ''}`;
          const direction = side === 'LONG' ? 1 : side === 'SHORT' ? -1 : 0;
          const stopDistance = Math.max(atr * Number(s.atrStopMult), price * 0.0015);
          const entry = price * (1 + direction * (Number(s.slippagePct) / 100));
          const stop = direction ? entry - direction * stopDistance : null;
          const take = direction ? entry + direction * stopDistance * Number(s.takeProfitR) : null;
          const notional = Number(s.orderMargin) * Number(s.leverage);
          const qty = notional / (entry || price);
          const feeOpen = this.fee(notional, s.feeOpenPct);
          const feeClose = this.fee(notional, s.feeClosePct);
          const roundTripFee = feeOpen + feeClose;
          const risk = stopDistance * qty + roundTripFee;
          const reward = stopDistance * Number(s.takeProfitR) * qty - roundTripFee;
          const candleTs = Number(last.ts || 0);

          return {
            symbol: market.symbol,
            source: market.source,
            price,
            side,
            score,
            movePct,
            oneCandlePct,
            volX: volumeX,
            atr,
            atrPct,
            rsi: rsiVal,
            emaFast,
            emaSlow,
            why: `[فرمول اختصاصی]: ${whyFull}`,
            formulaVars: formulaCtx,
            stale,
            tfMs: ms,
            candleAgeMs: candleClosedAgeMs,
            formulaMode,
            formulaValue: null,
            microDirection: micro.direction,
            microStreak: micro.streak,
            microTag: micro.tag,
            microReason: micro.reason,
            entry,
            stop,
            take,
            qty,
            notional,
            feeOpen,
            feeClose,
            fee: roundTripFee,
            risk,
            reward,
            candleTs,
            signalId: `${market.symbol}:${candleTs}:${side}`,
            ts: Date.now()
          };
        }
      }
    }

    // --- موتور اجماع چند اندیکاتوری پیش‌فرض ---
    if (movePct >= minimumMove) {
      longScore += 24;
      reasons.push(`حرکت ${movePct.toFixed(2)}%`);
    }
    if (movePct <= -minimumMove) {
      shortScore += 24;
      reasons.push(`ریزش ${Math.abs(movePct).toFixed(2)}%`);
    }
    if (oneCandlePct >= minimumMove / 1.5) longScore += 12;
    if (oneCandlePct <= -minimumMove / 1.5) shortScore += 12;
    if (volumeX >= Number(s.volumeSpikeX)) {
      longScore += 22;
      shortScore += 22;
      reasons.push(`حجم ${volumeX.toFixed(2)}x`);
    }
    if (breakoutUp) {
      longScore += 22;
      reasons.push('Breakout سقف');
    }
    if (breakoutDown) {
      shortScore += 22;
      reasons.push('Breakout کف');
    }
    if (trendUp) longScore += 10;
    if (trendDown) shortScore += 10;
    if (rsiVal < 35) {
      longScore += 15;
      reasons.push(`RSI کف (${rsiVal.toFixed(0)})`);
    } else if (rsiVal > 65) {
      shortScore += 15;
      reasons.push(`RSI سقف (${rsiVal.toFixed(0)})`);
    }
    if (emaFast > emaSlow) longScore += 8;
    else if (emaFast < emaSlow) shortScore += 8;

    if (bodyPct > atrPct * 0.35) {
      if (last.close > last.open) longScore += 10;
      if (last.close < last.open) shortScore += 10;
    }
    if (atrPct < 0.03) {
      longScore -= 20;
      shortScore -= 20;
      reasons.push('ATR کم');
    }

    // --- تاییدیه هم‌جهتی کندل‌های ریز: وزن داینامیک فقط روی سمت هم‌جهت ---
    if (micro.active && micro.direction) {
      if (micro.direction === 'LONG') {
        longScore = Math.min(100, longScore * microBoost);
        reasons.push(`${micro.reason} (+${s.microCandleBoostPct}٪ وزن خرید)`);
      } else {
        shortScore = Math.min(100, shortScore * microBoost);
        reasons.push(`${micro.reason} (+${s.microCandleBoostPct}٪ وزن فروش)`);
      }
    } else if (micro.active && micro.reason) {
      reasons.push(micro.reason);
    }

    // پاداش فرمول پارامتریک: اگر filter تایید کرد، امتیاز سمت برنده بالا می‌رود
    if (formulaMode === 'filter' && formulaValue !== null && formulaValue > 0) {
      const bonus = Math.max(0, Number(s.formulaBonusPct) || 0);
      if (longScore >= shortScore) longScore += bonus;
      else shortScore += bonus;
      reasons.push(`🧮 فرمول تایید کرد (${formulaValue.toFixed(2)} → +${bonus} امتیاز)`);
    }

    const rawScore = Math.max(longScore, shortScore);
    const score = clamp(Math.round(rawScore), 0, 100);
    let side = score >= Number(s.minScore)
      ? (longScore >= shortScore ? 'LONG' : 'SHORT')
      : 'WAIT';

    // بلاک ورود توسط فرمول (نتیجه ≤ 0) یا کهنگی کندل — هر دو علت شفاف
    let forcedWaitWhy = '';
    if (formulaBlocked) {
      side = 'WAIT';
      forcedWaitWhy = `🧮 فرمول پارامتریک ورود را مسدود کرد (نتیجه = ${formulaValue?.toFixed?.(2) ?? formulaValue})`;
    } else if (formulaError) {
      forcedWaitWhy = `🧮 فرمول خطا دارد و خنثی ماند: ${formulaError}`;
    }
    if (stale) {
      side = 'WAIT';
      forcedWaitWhy = `⏱ آخرین کندل بسته ${Math.round(candleClosedAgeMs / 60000)} دقیقه پیش است (بیش از ${Math.round(staleLimitMs / 60000)} دقیقه برای تایم‌فریم ${tfLabel(s.timeframe)}) — صبر برای کندل تازه`;
    }
    const direction = side === 'LONG' ? 1 : side === 'SHORT' ? -1 : 0;
    const stopDistance = Math.max(atr * Number(s.atrStopMult), price * 0.0015);
    const entry = price * (1 + direction * (Number(s.slippagePct) / 100));
    const stop = direction ? entry - direction * stopDistance : null;
    const take = direction ? entry + direction * stopDistance * Number(s.takeProfitR) : null;
    const notional = Number(s.orderMargin) * Number(s.leverage);
    const qty = notional / (entry || price);
    const feeOpen = this.fee(notional, s.feeOpenPct);
    const feeClose = this.fee(notional, s.feeClosePct);
    const roundTripFee = feeOpen + feeClose;
    const risk = stopDistance * qty + roundTripFee;
    const reward = stopDistance * Number(s.takeProfitR) * qty - roundTripFee;
    const candleTs = Number(last.ts || 0);

    return {
      symbol: market.symbol,
      source: market.source,
      price,
      side,
      score,
      movePct,
      oneCandlePct,
      volX: volumeX,
      atr,
      atrPct,
      rsi: rsiVal,
      emaFast,
      emaSlow,
      why: (() => {
        const base = forcedWaitWhy || reasons.join('، ') || 'تأیید کافی ندارد';
        // 🐋 chip جریان (ضد‌نهنگ) — فقط وقتی دادهٔ تیکری واقعی موجود است
        const chip = flowWhyText(flow);
        const aligned = side === 'LONG' ? flow.longAligned : side === 'SHORT' ? flow.shortAligned : false;
        return chip ? `${base} • ${chip}${aligned ? ' ✓هم‌جهت' : ''}` : base;
      })(),
      flow,
      formulaVars: formulaCtx,
      stale,
      tfMs: ms,
      candleAgeMs: candleClosedAgeMs,
      formulaMode,
      formulaValue,
      microDirection: micro.direction,
      microStreak: micro.streak,
      microTag: micro.tag,
      microReason: micro.reason,
      entry,
      stop,
      take,
      qty,
      notional,
      feeOpen,
      feeClose,
      fee: roundTripFee,
      risk,
      reward,
      candleTs,
      signalId: `${market.symbol}:${candleTs}:${side}`,
      ts: Date.now()
    };
  }
}
