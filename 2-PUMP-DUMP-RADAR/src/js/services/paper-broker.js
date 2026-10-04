import { STORAGE_KEYS } from '../core/config.js';
import { readJson, uid, writeJson } from '../core/utils.js';

/**
 * بروکر مجازی مخصوص پمپ/دامپ — با ساعت قابل تزریق (برای بک‌تست) و
 * اجرای قاطع MaxHold (پنجره عمر کوتاه پمپ/دامپ).
 */
export class PaperBroker {
  constructor(settings, logger, deps = {}) {
    this.s = settings;
    this.log = logger;
    this.now = deps.now || (() => Date.now());
    const saved = readJson(STORAGE_KEYS.state, null);
    this.state = this.normalise(saved || this.initial());
    this.migrateDay();
  }

  initial() {
    const equity = Number(this.s.value.paperInitialEquity);
    return {
      paperEquity: equity,
      paperPositions: [],
      paperTrades: [],
      lastCooldown: {},
      feesPaid: 0,
      day: new Date(this.now()).toDateString(),
      dayStartEquity: equity
    };
  }

  normalise(saved) {
    const base = this.initial();
    return {
      ...base,
      ...saved,
      paperPositions: Array.isArray(saved.paperPositions) ? saved.paperPositions : [],
      paperTrades: Array.isArray(saved.paperTrades) ? saved.paperTrades.slice(0, 400) : [],
      lastCooldown: saved.lastCooldown && typeof saved.lastCooldown === 'object' ? saved.lastCooldown : {},
      feesPaid: Number.isFinite(Number(saved.feesPaid)) ? Number(saved.feesPaid) : 0
    };
  }

  save() {
    writeJson(STORAGE_KEYS.state, this.state);
  }

  reset() {
    this.state = this.initial();
    this.save();
  }

  migrateDay() {
    const today = new Date(this.now()).toDateString();
    if (this.state.day !== today) {
      this.state.day = today;
      this.state.dayStartEquity = this.state.paperEquity;
      this.save();
    }
  }

  oneWayFee(notional, percentage) {
    return Math.abs(Number(notional)) * (Number(percentage) / 100);
  }

  grossPnl(position, mark) {
    const direction = position.side === 'LONG' ? 1 : -1;
    return (Number(mark) - Number(position.entry)) * direction * Number(position.qty);
  }

  closeFee(position, mark) {
    return this.oneWayFee(Number(mark) * Number(position.qty), this.s.value.feeClosePct);
  }

  markToMarketDelta(position, mark) {
    return this.grossPnl(position, mark) - this.closeFee(position, mark);
  }

  netPnl(position, mark) {
    return this.grossPnl(position, mark) - Number(position.openFee || 0) - this.closeFee(position, mark);
  }

  dailyLossExceeded() {
    const start = Number(this.state.dayStartEquity);
    if (!(start > 0)) return true;
    return ((start - Number(this.state.paperEquity)) / start * 100) >= Number(this.s.value.dailyLossLimitPct);
  }

  evaluate(signal, force = false) {
    const s = this.s.value;
    if (!signal || signal.side === 'WAIT') {
      return { ok: false, reason: 'سیگنال WAIT — جهت کشف یا تاییدیه‌ها قطعی نیست' };
    }
    if (this.dailyLossExceeded()) {
      return { ok: false, reason: `سقف ضرر روزانه ${s.dailyLossLimitPct}٪ پر شده — قفل روزانه فعال` };
    }
    if (this.state.paperPositions.length >= Number(s.maxOpenPositions)) {
      return { ok: false, reason: `سقف ${s.maxOpenPositions} پوزیشن همزمان پر است` };
    }
    if (this.state.paperPositions.some(position => position.symbol === signal.symbol)) {
      return { ok: false, reason: `برای ${signal.symbol} پوزیشن باز داریم` };
    }
    if (!force) {
      const cooldownMs = Number(s.cooldownSec) * 1000;
      const remainSec = Math.ceil((Number(this.state.lastCooldown[signal.symbol] || 0) + cooldownMs - this.now()) / 1000);
      if (remainSec > 0) {
        return { ok: false, reason: `Cooldown فعال: ${remainSec} ثانیه دیگر` };
      }
    }
    return { ok: true, reason: '' };
  }

  open(signal, reason = 'auto', force = false) {
    if (!signal || signal.side === 'WAIT') return false;
    const verdict = this.evaluate(signal, force);
    if (!verdict.ok) return false;

    const openFee = this.oneWayFee(signal.notional, this.s.value.feeOpenPct);
    this.state.paperEquity -= openFee;
    this.state.feesPaid += openFee;
    this.state.paperPositions.push({
      id: uid(),
      symbol: signal.symbol,
      side: signal.side,
      entry: signal.entry,
      qty: signal.qty,
      notional: signal.notional,
      stop: signal.stop,
      take: signal.take,
      openFee,
      openedAt: this.now(),
      reason,
      score: signal.score,
      radarChangePct: signal.radarChangePct,
      signalId: signal.signalId,
      source: signal.source
    });
    this.state.lastCooldown[signal.symbol] = this.now();
    this.save();
    this.log.info('PAPER OPEN', {
      symbol: signal.symbol,
      side: signal.side,
      entry: signal.entry,
      score: signal.score,
      radarChangePct: signal.radarChangePct,
      source: signal.source
    });
    return true;
  }

  close(position, mark, reason = 'manual') {
    const exit = Number(mark);
    if (!Number.isFinite(exit) || exit <= 0) return false;
    const gross = this.grossPnl(position, exit);
    const feeClose = this.closeFee(position, exit);
    const feeOpen = Number(position.openFee || 0);
    const net = gross - feeOpen - feeClose;
    this.state.paperEquity += gross - feeClose;
    this.state.feesPaid += feeClose;
    this.state.paperPositions = this.state.paperPositions.filter(item => item.id !== position.id);
    this.state.paperTrades.unshift({
      time: this.now(),
      symbol: position.symbol,
      side: position.side,
      entry: Number(position.entry),
      exit,
      grossPnl: gross,
      feeOpen,
      feeClose,
      fees: feeOpen + feeClose,
      pnl: net,
      reason,
      score: position.score,
      radarChangePct: position.radarChangePct,
      source: position.source,
      durationSec: Math.max(0, Math.round((this.now() - Number(position.openedAt)) / 1000))
    });
    this.state.paperTrades = this.state.paperTrades.slice(0, 400);
    this.save();
    this.log.info('PAPER CLOSE', { symbol: position.symbol, side: position.side, exit, net, reason });
    return true;
  }

  /**
   * مدیریت پوزیشن‌های باز در هر اسکن: SL سخت، Breakeven، ترلینگ ATR و
   * خروج قاطع MaxHold — چون پنجره عمر پمپ/دامپ کوتاه است.
   */
  updateStops(marketMap) {
    const maxHoldMs = Math.max(1, Number(this.s.value.ignitionMaxHoldMin)) * 60000;
    for (const position of [...this.state.paperPositions]) {
      const market = marketMap.get(position.symbol);
      if (!market) continue;
      const mark = Number(market.price);
      const high = Number.isFinite(Number(market.lastCandle?.high)) ? Number(market.lastCandle.high) : mark;
      const low = Number.isFinite(Number(market.lastCandle?.low)) ? Number(market.lastCandle.low) : mark;
      const isLong = position.side === 'LONG';
      const entry = Number(position.entry);
      let exit = null;
      let reason = '';

      if (!position.highWater) position.highWater = entry;
      if (!position.lowWater) position.lowWater = entry;
      if (isLong) position.highWater = Math.max(position.highWater, mark, high);
      else position.lowWater = Math.min(position.lowWater, mark, low);

      // ۱. استاپ سخت (اولویت با محافظت از سرمایه)
      if (isLong && (mark <= Number(position.stop) || low <= Number(position.stop))) {
        exit = Number(position.stop);
        reason = 'SL_HARD_STOP';
      } else if (!isLong && (mark >= Number(position.stop) || high >= Number(position.stop))) {
        exit = Number(position.stop);
        reason = 'SL_HARD_STOP';
      }

      // ۲. خروج قاطع MaxHold — پمپ/دامپ منتظر کسی نمی‌ماند
      if (!exit && this.now() - Number(position.openedAt) >= maxHoldMs) {
        exit = mark;
        reason = 'MAX_HOLD_EXIT';
      }

      // ۳. سود: Breakeven + ترلینگ ATR
      if (!exit) {
        const gross = this.grossPnl(position, mark);
        const atr = Number(market.atr) || mark * 0.004;
        const trail = atr * 1.2;
        if (gross > Number(position.openFee || 0) * 1.5) {
          const be = isLong ? entry * 1.002 : entry * 0.998;
          if (isLong && Number(position.stop) < be) position.stop = be;
          if (!isLong && Number(position.stop) > be) position.stop = be;
          if (isLong) {
            const t = position.highWater - trail;
            if (t > Number(position.stop)) position.stop = t;
            if (mark <= position.stop) { exit = mark; reason = 'PROFIT_TRAIL_REVERSED'; }
          } else {
            const t = position.lowWater + trail;
            if (t < Number(position.stop)) position.stop = t;
            if (mark >= position.stop) { exit = mark; reason = 'PROFIT_TRAIL_REVERSED'; }
          }
        }
      }

      if (exit) this.close(position, exit, reason);
    }
  }
}
