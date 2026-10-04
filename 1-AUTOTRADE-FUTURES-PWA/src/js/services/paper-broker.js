import { STORAGE_KEYS } from '../core/config.js';
import { readJson, uid, writeJson } from '../core/utils.js';

// 🪜 نردبان داده (v2.6): هر معامله «رکورد پله‌هایش» را همراه خودش ذخیره می‌کند تا
// ممیزی مرحله‌ای روی وقایع واقعی (نه فقط بک‌تست) قابل اجرا باشد.
const RUNG_CAP = 160;          // حداکثر پلهٔ ثبت‌شده به‌ازای هر معامله (بیشینه حفظ می‌شود)
const RUNGS_KEEP_TRADES = 40;   // فقط آخرین معاملات رکورد کامل دارند؛ قدیمی‌ترها فقط خلاصهٔ ladder

// شمارهٔ لایهٔ خروج — همان نردبانِ ممیزی: ۱=SL سخت، ۲=بریک‌ایون، ۳=ترلینگ، ۴=برگشتی،
// ۵=محو مومنتوم، ۶=چرخش روند، ۷=MaxHold، ۸=TP ثابت، ۹=پایان داده، ۰=دستی/سایر
const EXIT_LAYER_BY_REASON = {
  SL_HARD_STOP: 1,
  PROFIT_TRAIL_REVERSED: 3,
  REVERSAL_RSI_OVERBOUGHT: 4,
  REVERSAL_RSI_OVERSOLD: 4,
  REVERSAL_EMA_CROSS: 4,
  MOMENTUM_FADE: 5,
  TREND_FLIP: 6,
  MAX_HOLD_EXIT: 7,
  TAKE_PROFIT: 8,
  END_OF_DATA: 9
};

/** استخراج شمارهٔ لایهٔ خروج از دلیل بستن (+ اینکه آخرین بار کدام لایه استاپ را تنظیم کرد) */
export function exitLayerOf(reason, stopSource = '') {
  if (reason === 'PROFIT_TRAIL_REVERSED') return stopSource === 'be' ? 2 : 3;
  return EXIT_LAYER_BY_REASON[reason] || 0;
}

export class PaperBroker {
  constructor(settings, logger, deps = {}) {
    this.s = settings;
    this.log = logger;
    // ساعت قابل تزریق — برای بک‌تست دقیق (cooldown/مدت/روز) بدون تغییر semantics زنده
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
      realOrders: [],
      lastCooldown: {},
      profileStarts: {},
      feesPaid: 0,
      day: new Date(this.now()).toDateString(),
      dayStartEquity: equity
    };
  }

  normalise(saved) {
    const base = this.initial();
    const positions = Array.isArray(saved.paperPositions)
      ? saved.paperPositions.map(position => ({ ...position, riskProfile: position.riskProfile || 'medium' }))
      : [];
    const trades = Array.isArray(saved.paperTrades)
      ? saved.paperTrades.map(trade => ({ ...trade, riskProfile: trade.riskProfile || 'medium' }))
      : [];
    const profileStarts = saved.profileStarts && typeof saved.profileStarts === 'object'
      ? { ...saved.profileStarts }
      : {};
    // Existing v3 history predates profile tags; treat it as the default medium run.
    if (trades.length && profileStarts.medium === undefined) profileStarts.medium = Number(this.s.value.paperInitialEquity);
    return {
      ...base,
      ...saved,
      paperPositions: positions,
      paperTrades: trades,
      realOrders: Array.isArray(saved.realOrders) ? saved.realOrders : [],
      lastCooldown: saved.lastCooldown && typeof saved.lastCooldown === 'object' ? saved.lastCooldown : {},
      profileStarts,
      feesPaid: Number.isFinite(Number(saved.feesPaid)) ? Number(saved.feesPaid) : 0
    };
  }

  save() {
    writeJson(STORAGE_KEYS.state, this.state);
  }

  /**
   * 🪜 ثبت یک پله (rung) از نردبانِ تصمیم‌های این معامله.
   * فقط در «رخدادهای تغییر» صدا زده می‌شود (باز شدن، بالغ‌شدن سود، جابه‌جایی استاپ،
   * گارد TF، بستن) — نه هر تیک — تا حجم داده سبک و معنادار بماند.
   * a: 'open' | 'arm' | 'be' | 'trail' | 'guard' | 'lock' | 'close'
   */
  pushRung(position, action, ctx = {}) {
    if (!position) return;
    if (!Array.isArray(position.rungs)) position.rungs = [];
    const isLong = position.side === 'LONG';
    position.rungs.push({
      t: this.now(),
      a: action,
      m: Number.isFinite(Number(ctx.mark)) ? Number(ctx.mark) : null,
      st: Number.isFinite(Number(position.stop)) ? Number(position.stop) : null,
      hw: Number(isLong ? (position.highWater ?? position.entry) : (position.lowWater ?? position.entry)),
      ...(ctx.atr ? { atr: Number(ctx.atr) } : {}),
      ...(ctx.rsi !== undefined && ctx.rsi !== null ? { rsi: Number(ctx.rsi) } : {}),
      ...(ctx.sc !== undefined && ctx.sc !== null ? { sc: Number(ctx.sc) } : {}),
      ...(ctx.sd ? { sd: String(ctx.sd) } : {}),
      ...(ctx.reason ? { r: String(ctx.reason) } : {}),
      ...(ctx.entryTfMs ? { etf: ctx.entryTfMs, ctf: ctx.curTfMs } : {})
    });
    if (position.rungs.length > RUNG_CAP) {
      // واکشیدن: پلهٔ اول (ورود) + آخرین پله‌ها حفظ می‌شوند
      position.rungs = [position.rungs[0], ...position.rungs.slice(-(RUNG_CAP - 1))];
      position.rungsThinned = true;
    }
  }

  /**
   * 🪜 نردبان ذخیره‌سازی: آخرین معاملات رکورد کامل پله‌ها را دارند (سطح ۱)؛
   * قدیمی‌ترها فقط خلاصهٔ ladder را نگه می‌دارند تا storage سبک بماند.
   */
  trimRungHistory() {
    this.state.paperTrades.forEach((trade, i) => {
      if (i >= RUNGS_KEEP_TRADES && Array.isArray(trade.rungs)) {
        trade.rungsDropped = true;
        delete trade.rungs;
      }
    });
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

  // This is the cash/equity delta at a mark. Opening fee is already removed
  // from paperEquity when the position is opened, so it is not removed twice.
  markToMarketDelta(position, mark) {
    return this.grossPnl(position, mark) - this.closeFee(position, mark);
  }

  // Net PnL shown for validation: gross movement minus both entry and exit fees.
  netPnl(position, mark) {
    return this.grossPnl(position, mark)
      - Number(position.openFee || 0)
      - this.closeFee(position, mark);
  }

  dailyLossExceeded() {
    const start = Number(this.state.dayStartEquity);
    if (!(start > 0)) return true;
    return ((start - Number(this.state.paperEquity)) / start * 100) >= Number(this.s.value.dailyLossLimitPct);
  }

  /**
   * قضاوت کامل امکان ورود + «علت دقیق رد شدن» برای نمایش شفاف روی کارت هر ارز.
   * force=true فقط Cooldown نماد را دور می‌زند (ورود دستی)؛ هرگز چک‌های
   * امنیتی سطح حساب (سقف ضرر روزانه/سقف پوزیشن/تکرار نماد) را دور نمی‌زند.
   */
  evaluate(signal, force = false) {
    const s = this.s.value;
    if (!signal || signal.side === 'WAIT') {
      return { ok: false, reason: 'سیگنال در حالت WAIT است؛ جهت قطعی تایید نشده' };
    }
    if (this.dailyLossExceeded()) {
      return { ok: false, reason: `سقف ضرر روزانه ${s.dailyLossLimitPct}٪ پر شده؛ ورود جدید تا فردا مسدود است` };
    }
    if (this.state.paperPositions.length >= Number(s.maxOpenPositions)) {
      return { ok: false, reason: `سقف ${s.maxOpenPositions} پوزیشن همزمان پر است (${this.state.paperPositions.length} پوزیشن باز)` };
    }
    if (this.state.paperPositions.some(position => position.symbol === signal.symbol)) {
      return { ok: false, reason: `برای ${signal.symbol} از قبل پوزیشن باز داریم` };
    }
    if (!force) {
      const cooldownMs = Number(s.cooldownSec) * 1000;
      const lastAt = Number(this.state.lastCooldown[signal.symbol] || 0);
      const remainSec = Math.ceil((lastAt + cooldownMs - this.now()) / 1000);
      if (remainSec > 0) {
        return { ok: false, reason: `Cooldown فعال: ${remainSec} ثانیه دیگر برای ${signal.symbol}` };
      }
    }
    return { ok: true, reason: '' };
  }

  canOpen(signal) {
    return this.evaluate(signal).ok;
  }

  open(signal, reason = 'auto', force = false) {
    if (!signal || signal.side === 'WAIT') return false;
    // Manual entry may bypass cooldown, never the account-level safety checks.
    const verdict = this.evaluate(signal, force);
    if (!verdict.ok) return false;

    const openFee = this.oneWayFee(signal.notional, this.s.value.feeOpenPct);
    const riskProfile = this.s.value.riskProfile || 'medium';
    if (!Object.prototype.hasOwnProperty.call(this.state.profileStarts, riskProfile)) {
      this.state.profileStarts[riskProfile] = this.state.paperEquity;
    }
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
      // 🔒 ریسک اولیهٔ دلاری (فاصلهٔ استاپ × تعداد) — مبنای R برای قفل سود v2.10
      risk0: Math.abs(Number(signal.entry) - Number(signal.stop)) * Number(signal.qty) || 0,
      openFee,
      openedAt: this.now(),
      reason,
      score: signal.score,
      riskProfile,
      signalId: signal.signalId,
      source: signal.source,
      candleTs: signal.candleTs,
      // 🔒 قفل تایم‌فریم: پوزیشن برای همیشه با همان تایم‌فریمی که با آن باز شد،
      // مدیریت می‌شود — حتی اگر کاربر وسط معامله timeframe تنظیمات را عوض کند.
      tfMs: Number(signal.tfMs) || 0,
      timeframe: String(this.s.value.timeframe),
      // 🪜 نردبان داده: منشا فعلی استاپ + رکورد پله‌های تصمیم این معامله
      stopSource: 'init',
      rungs: []
    });
    this.state.lastCooldown[signal.symbol] = this.now();
    this.pushRung(this.state.paperPositions.at(-1), 'open', {
      mark: signal.entry, sc: signal.score, sd: signal.side, atr: signal.atr
    });
    this.save();
    this.log.info('PAPER OPEN', {
      symbol: signal.symbol,
      side: signal.side,
      entry: signal.entry,
      qty: signal.qty,
      score: signal.score,
      feeOpen: openFee,
      source: signal.source
    });
    return true;
  }

  close(position, mark, reason = 'manual') {
    const exit = Number(mark);
    if (!Number.isFinite(exit) || exit <= 0) return false;
    // 🪜 پلهٔ پایانی نردبان: بستن + اینکه کدام لایه بست
    this.pushRung(position, 'close', { mark: exit, reason });
    const gross = this.grossPnl(position, exit);
    const feeClose = this.closeFee(position, exit);
    const feeOpen = Number(position.openFee || 0);
    const net = gross - feeOpen - feeClose;

    // 📈 متریک کیفیت خروج: سود در «اوج» (highWater/lowWater) و چقدر از اوج پس داده شد
    const isLongPos = position.side === 'LONG';
    const peakMark = isLongPos
      ? Math.max(Number(position.highWater ?? position.entry), Number(position.entry))
      : Math.min(Number(position.lowWater ?? position.entry), Number(position.entry));
    const peakGross = this.grossPnl(position, peakMark);
    const peakNet = peakGross - feeOpen - this.closeFee(position, peakMark);
    const givebackPct = peakNet > 0 ? Math.max(0, (1 - net / peakNet) * 100) : 0;

    // openFee has already been charged; here we settle gross PnL and exit fee.
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
      peakPnl: Number(peakNet.toFixed(4)),
      givebackPct: Number(givebackPct.toFixed(2)),
      reason,
      score: position.score,
      riskProfile: position.riskProfile || this.s.value.riskProfile || 'legacy',
      source: position.source,
      durationSec: Math.max(0, Math.round((this.now() - Number(position.openedAt)) / 1000)),
      // 🪜 نردبان معامله: خلاصهٔ لایه‌ها + رکورد کامل پله‌ها — برای ممیزی مرحله‌ای روی وقایع واقعی
      ladder: (() => {
        const hwN = Number(position.highWater ?? position.entry);
        const lwN = Number(position.lowWater ?? position.entry);
        const entryN = Number(position.entry) || 1;
        const heldMs = this.now() - Number(position.openedAt);
        return {
          tf: position.timeframe || null,
          bars: Number(position.tfMs) > 0 && heldMs > 0 ? Math.max(1, Math.round(heldMs / Number(position.tfMs))) : null,
          mfePct: Number(((isLongPos ? (hwN - entryN) : (entryN - lwN)) / entryN * 100).toFixed(3)),
          maePct: Number(((isLongPos ? (lwN - entryN) : (hwN - entryN)) / entryN * 100).toFixed(3)),
          beArmed: Boolean(position.beArmed),
          trailMoves: Number(position.trailMoves || 0),
          stopSource: position.stopSource || 'init',
          rungsThinned: Boolean(position.rungsThinned),
          exitLayer: exitLayerOf(reason, position.stopSource)
        };
      })(),
      rungs: Array.isArray(position.rungs) ? position.rungs : []
    });
    this.state.paperTrades = this.state.paperTrades.slice(0, 350);
    this.trimRungHistory();
    this.save();
    this.log.info('PAPER CLOSE', {
      symbol: position.symbol,
      side: position.side,
      exit,
      gross,
      fees: feeOpen + feeClose,
      net,
      reason
    });
    return true;
  }

  updateStops(marketMap, signalsMap) {
    const nowT = this.now();
    const s = this.s.value;
    // حداکثر زمان نگهداری — پارامتر maxHoldMinutes که در Settings هست، اینجا قاطع اجرا می‌شود
    const maxHoldMs = Math.max(0, Number(s.maxHoldMinutes)) * 60000;
    // 🎯 پارامترهای موتور خروج شناور — همه از Settings (پارامتریک، قابل بهینه‌سازی با بک‌تست)
    const profitMode = String(s.profitMode || 'float');
    const trailAtrMult = Number(s.trailAtrMult) > 0 ? Number(s.trailAtrMult) : 1.25;
    const breakevenBufferPct = Number(s.breakevenBufferPct) >= 0 ? Number(s.breakevenBufferPct) : 0.2;
    const reversalRsiHigh = Number(s.reversalRsiHigh) || 68;
    const reversalRsiLow = Number(s.reversalRsiLow) || 32;
    const reversalMovePct = Number(s.reversalMovePct) >= 0 ? Number(s.reversalMovePct) : 0.15;
    const reversalVolX = Number(s.reversalVolX) > 0 ? Number(s.reversalVolX) : 1.3;
    const fadeN = Math.max(0, Number(s.fadeCandles) || 0);
    // 🔒 قفل سود v2.10 — همه پارامتریک از Settings
    const lockOn = String(s.profitLockOn || 'on') !== 'off';
    const lockMinPeakR = Number(s.profitLockMinPeakR) > 0 ? Number(s.profitLockMinPeakR) : 1;
    const lockGivebackPct = (Number(s.profitLockGivebackPct) > 0 && Number(s.profitLockGivebackPct) < 100)
      ? Number(s.profitLockGivebackPct) : 50;
    // 🔄 حداقل امتیاز سیگنال مخالف برای چرخش روند — تنظیم مستقل از minScore ورود (v2.10.2)
    const minScoreForFlip = Number(s.flipMinScore) > 0 ? Number(s.flipMinScore) : (Number(s.minScore) || 72);

    for (const position of [...this.state.paperPositions]) {
      const market = marketMap.get(position.symbol);
      const signal = signalsMap ? signalsMap.get(position.symbol) : null;
      if (!market) continue;

      // 🔒 گارد قفل تایم‌فریم: خروج‌های «سیگنالی» فقط وقتی مجازند که سیگنال تازه
      // با همان تایم‌فریم ورود پوزیشن تحلیل شده باشد. اگر کاربر تنظیمات را عوض
      // کرده باشد، فقط محافظت‌های قیمتی (SL/بریک‌ایون/ترلینگ با ATR پیش‌فرض/
      // MaxHold) فعال می‌مانند — هرگز خروج با تایم‌فریم ناهم‌تراز صورت نمی‌گیرد.
      const posTfMs = Number(position.tfMs) || 0;
      const sigTfMs = signal ? (Number(signal.tfMs) || 0) : 0;
      const tfMatch = !posTfMs || !sigTfMs || posTfMs === sigTfMs;
      if (!tfMatch && !position.tfMismatchWarned) {
        position.tfMismatchWarned = true;
        this.pushRung(position, 'guard', { mark: market.price, entryTfMs: posTfMs, curTfMs: sigTfMs });
        this.log.info('TF LOCK GUARD', {
          symbol: position.symbol,
          entryTfMs: posTfMs,
          currentTfMs: sigTfMs,
          note: 'خروج‌های سیگنالی قفل شدند تا تایم‌فریم با ورود هم‌تراز شود؛ SL/بریک‌ایون/MaxHold فعال'
        });
      }

      const mark = Number(market.price);
      const candle = market.lastCandle || {};
      const high = Number.isFinite(Number(candle.high)) ? Number(candle.high) : mark;
      const low = Number.isFinite(Number(candle.low)) ? Number(candle.low) : mark;
      const isLong = position.side === 'LONG';
      const entry = Number(position.entry);
      let exit = null;
      let reason = '';

      // رهگیری بالاترین و پایین‌ترین قیمت ثبت‌شده — سود شناور (آب موافق) و
      // بیشترین افت (آب مخالف → maePct در نردبان داده v2.6)
      if (!position.highWater) position.highWater = entry;
      if (!position.lowWater) position.lowWater = entry;
      position.highWater = Math.max(position.highWater, mark, high);
      position.lowWater = Math.min(position.lowWater, mark, low);

      // ۰. خروج قاطع MaxHold — پوزیشن بیش از حد مجاز نگهداری نشود
      if (maxHoldMs > 0 && nowT - Number(position.openedAt) >= maxHoldMs) {
        this.close(position, mark, 'MAX_HOLD_EXIT');
        continue;
      }

      // ۱. استاپ قاطع (قیمتی و مستقل از تایم‌فریم):
      //    اگر استاپ بالای نقطهٔ ورود باشد (سود قفل‌شده با بریک‌ایون/ترلینگ)،
      //    برچسب خروج «بستن سود شناور» است نه SL — تا آمار واقعی سود/ضرر کدر نباشد.
      const stopLocksProfit = isLong ? Number(position.stop) >= entry : Number(position.stop) <= entry;
      if (isLong && (mark <= Number(position.stop) || low <= Number(position.stop))) {
        exit = Number(position.stop);
        reason = stopLocksProfit ? 'PROFIT_TRAIL_REVERSED' : 'SL_HARD_STOP';
      } else if (!isLong && (mark >= Number(position.stop) || high >= Number(position.stop))) {
        exit = Number(position.stop);
        reason = stopLocksProfit ? 'PROFIT_TRAIL_REVERSED' : 'SL_HARD_STOP';
      }

      // ۲. حالت TP قاطع: اگر profitMode='fixed' باشد حد سود در takeProfitR بسته می‌شود
      if (!exit && profitMode === 'fixed' && Number.isFinite(Number(position.take))) {
        if (isLong && (mark >= Number(position.take) || high >= Number(position.take))) {
          exit = Number(position.take);
          reason = 'TAKE_PROFIT';
        } else if (!isLong && (mark <= Number(position.take) || low <= Number(position.take))) {
          exit = Number(position.take);
          reason = 'TAKE_PROFIT';
        }
      }

      // ۳. 🎯 حالت سود شناور (پیش‌فرض float): حد سود باز است؛ سود با نمودار
      // بالا می‌رود و فقط برگشت روند / ترلینگ / محو مومنتوم معامله را می‌بندد.
      const gross = this.grossPnl(position, mark);
      const isInProfit = gross > (Number(position.openFee || 0) * 1.5);

      if (!exit && profitMode === 'float' && isInProfit) {
        // ATR هم‌تایم ورود — هم برای گیت بریک‌ایون و هم برای ترلینگ؛ تحت ناهم‌ترازی TF → null
        const atr = (signal && tfMatch && Number(signal.atr) > 0) ? Number(signal.atr) : null;
        const beMinAtr = Math.max(0, Number(s.breakevenMinAtr) || 0);

        // الف) بریک‌ایون «بالغ» — فقط وقتی حرکت موافق به breakevenMinAtr×ATR رسیده باشد.
        //    چرا (ممیزی مرحله‌ای v2.5): انتقال فوری استاپ به ورود، اکثر برنده‌ها را در
        //    «تقریباً بریک‌ایون» می‌بندد (ضریب برداشت از اوج فقط ~۱۰٪ در 6h). با این گیت
        //    سود اول نفس می‌کشد و بعد محافظت می‌شود. breakevenMinAtr=0 = رفتار قدیم.
        //    بدون ATR هم‌تایم (ناهم‌ترازی TF) گیت کنار می‌رود تا حفاظت قیمتی v2.4 بماند.
        const favDist = isLong ? (mark - entry) : (entry - mark);
        const beGateOk = atr === null || beMinAtr === 0 || favDist >= atr * beMinAtr;
        if (beGateOk && atr !== null && beMinAtr > 0 && !position.beArmed) {
          position.beArmed = true; // اولین باری که سود «بالغ» شد و بریک‌ایون مجاز گردید
          this.pushRung(position, 'arm', { mark, atr, rsi: signal?.rsi, sc: signal?.score, sd: signal?.side });
        }
        if (beGateOk) {
          const buffer = 1 + breakevenBufferPct / 100;
          const breakevenStop = isLong ? (entry * buffer) : (entry / buffer);
          if (isLong && Number(position.stop) < breakevenStop) {
            position.stop = breakevenStop;
            position.stopSource = 'be';
            this.pushRung(position, 'be', { mark, atr });
          } else if (!isLong && Number(position.stop) > breakevenStop) {
            position.stop = breakevenStop;
            position.stopSource = 'be';
            this.pushRung(position, 'be', { mark, atr });
          }
        }

        // ب) ترلینگ استاپ پویا — فقط با ATR سیگنالِ «هم‌تایم با ورود».
        //    اگر سیگنال ناهم‌تایم یا بدون ATR باشد، استاپ جابه‌جا نمی‌شود و همان
        //    محافظت قیمتی قبلی (بریک‌ایون/ترلینگ قبلی) فعال می‌ماند — قفل تایم‌فریم.
        if (atr !== null) {
          const trailDistance = atr * trailAtrMult;
          if (isLong) {
            const dynamicTrailStop = position.highWater - trailDistance;
            if (dynamicTrailStop > Number(position.stop)) {
              position.stop = dynamicTrailStop;
              position.stopSource = 'trail';
              position.trailMoves = Number(position.trailMoves || 0) + 1;
              this.pushRung(position, 'trail', { mark, atr });
            }
          } else {
            const dynamicTrailStop = position.lowWater + trailDistance;
            if (dynamicTrailStop < Number(position.stop)) {
              position.stop = dynamicTrailStop;
              position.stopSource = 'trail';
              position.trailMoves = Number(position.trailMoves || 0) + 1;
              this.pushRung(position, 'trail', { mark, atr });
            }
          }
        }
        if (isLong ? mark <= Number(position.stop) : mark >= Number(position.stop)) {
          exit = mark;
          reason = 'PROFIT_TRAIL_REVERSED';
        }

        // ج) خروج با تایید چرخش و بازگشت روند (RSI Reversal + EMA Cross Reversal — پارامتریک)
        if (!exit && signal && tfMatch) {
          if (isLong) {
            const rsiReversal = signal.rsi && signal.rsi > reversalRsiHigh && signal.movePct < -reversalMovePct;
            const emaBearCross = signal.emaFast && signal.emaSlow && (signal.emaFast < signal.emaSlow) && (signal.volX > reversalVolX);
            if (rsiReversal || emaBearCross) {
              exit = mark;
              reason = rsiReversal ? 'REVERSAL_RSI_OVERBOUGHT' : 'REVERSAL_EMA_CROSS';
            }
          } else {
            const rsiReversal = signal.rsi && signal.rsi < reversalRsiLow && signal.movePct > reversalMovePct;
            const emaBullCross = signal.emaFast && signal.emaSlow && (signal.emaFast > signal.emaSlow) && (signal.volX > reversalVolX);
            if (rsiReversal || emaBullCross) {
              exit = mark;
              reason = rsiReversal ? 'REVERSAL_RSI_OVERSOLD' : 'REVERSAL_EMA_CROSS';
            }
          }
        }

        // د) 🌫 محو مومنتوم: N کندلِ بستهٔ مخالف پی‌درپی روی تایم‌فریم اصلی
        //    («نمودار برای حرکت کمتر شد» → بستن معامله سودده پیش از برگشت کامل)
        if (!exit && tfMatch && fadeN > 0 && Array.isArray(market.candles) && market.candles.length >= fadeN) {
          const recentCandles = market.candles.slice(-fadeN);
          const allAgainst = recentCandles.every(candle =>
            isLong ? Number(candle.close) < Number(candle.open) : Number(candle.close) > Number(candle.open));
          if (allAgainst) {
            exit = mark;
            reason = 'MOMENTUM_FADE';
          }
        }

        // هـ) 🔒 قفل سود (v2.10 — «سود را از دست می‌دهیم»): وقتی سودِ اوج به
        //     profitLockMinPeakR برابرِ ریسک اولیهٔ معامله رسید و بعد بیش از
        //     profitLockGivebackPct٪ از اوج پس داده شد، همان‌جا ببند تا باقیماندهٔ
        //     سود نجات یابد. زیراندازِ ترلینگ: جایی که ATR هم‌تایم نیست و ترلینگ
        //     قفل شده (گارد TF)، این قفل همچنان سود را محافظت می‌کند.
        if (!exit && lockOn) {
          const risk0 = Number(position.risk0) || 0;
          if (risk0 > 0) {
            const peakMark = isLong ? Number(position.highWater) : Number(position.lowWater);
            const peakGross = this.grossPnl(position, peakMark);
            if (peakGross >= risk0 * lockMinPeakR) {
              if (!position.lockArmed) {
                position.lockArmed = true; // سود بالغ شد → قفل مسلح
                this.pushRung(position, 'lock', { mark, reason: 'ARM' });
              }
              if (gross <= peakGross * (1 - lockGivebackPct / 100)) {
                exit = mark;
                reason = 'PROFIT_LOCK';
              }
            }
          }
        }
      }

      // ۴. 🔄 چرخش روند قاطع (در هر دو حالت سود/ضرر): اگر سیگنال تازه با امتیاز
      //    کافی در جهت مخالف پوزیشن بیاید، تز معامله باطل است — حتی زیر حد ضرر هم ببند.
      if (!exit && tfMatch && signal && signal.side && signal.side !== 'WAIT' && signal.side !== position.side && Number(signal.score) >= minScoreForFlip) {
        exit = mark;
        reason = 'TREND_FLIP';
      }

      if (exit) this.close(position, exit, reason);
    }
  }
}
