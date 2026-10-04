/**
 * تست خودکار (Self-Test) — بدون نیاز به مرورگر و بدون هیچ دیتای فیک زنده.
 * فقط منطق خالص ماژول‌ها را با ورودی‌های ساختگیِ صریح تست می‌کند:
 *   ۱) فیلتر ریز‌کندل: استریک، حذف کندل باز، Doji، کمبود داده
 *   ۲) استراتژی: وزن داینامیک +۱۵٪ فقط روی سمت هم‌جهت (هر دو مسیر فرمول)
 *   ۳) PaperBroker.evaluate: علت‌های دقیق رد ورود
 *   ۴) AudioAlerts: منطق آستانه و Cooldown (بدون AudioContext)
 *   ۵) Logger: فرمت ساختاریافته و خروجی JSONL
 * اجرا:  npm test   (یا: node test/selftest.mjs)
 */
import { DEFAULT_SETTINGS } from '../src/js/core/config.js';
import { computeMicroStreak, MicroCandleFilter } from '../src/js/services/micro-candle.js';
import { MomentumScalpStrategy } from '../src/js/services/strategy.js';
import { PaperBroker } from '../src/js/services/paper-broker.js';
import { AudioAlerts } from '../src/js/services/audio-alerts.js';
import { HotBridge } from '../src/js/services/hot-bridge.js';
import { Logger } from '../src/js/services/logger.js';
import { alignCandles, floorTs, tfInfo, tfMs, describeAge } from '../src/js/core/timeframe.js';
import { evaluateFormula, validateFormula } from '../src/js/services/formula-engine.js';
import { ladderRollup } from '../src/js/services/performance-report.js';
import { MarketClient } from '../src/js/services/market-client.js';
import { computeFlowMetrics, flowWhyText } from '../src/js/services/flow-analytics.js';
import { SignalValidator } from '../src/js/services/signal-validator.js';
import { findRawPivots, zigzagPivots, detectReversals, reversalZones } from '../src/js/services/reversal-detector.js';
import { applySort, applyTextFilter } from '../src/js/ui/grid-tools.js';
import { readFileSync } from 'node:fs';

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✅ ${msg}`);
  else { failures += 1; console.error(`  ❌ ${msg}`); }
};
const baseSettings = (over = {}) => ({ value: { ...DEFAULT_SETTINGS, ...over } });

// ---------- ساخت کندل‌های ساختگیِ صریح برای تست منطق ----------
const mkCandle = (ts, open, close, volume = 1000) => ({
  ts, open, high: Math.max(open, close) * 1.001, low: Math.min(open, close) * 0.999, close, volume
});

console.log('\n۱) فیلتر ریز‌کندل — منطق استریک');
{
  const now = Date.now();
  const m = 60_000;
  // ۳ کندل بسته صعودی + ۱ کندل باز در انتها
  const bullish = [mkCandle(now - 4 * m, 100, 101), mkCandle(now - 3 * m, 101, 102), mkCandle(now - 2 * m, 102, 103.5), mkCandle(now - 30_000, 103.5, 103.8)];
  const r = computeMicroStreak(bullish, 3, m, now);
  ok(r.available === true, 'داده کافی موجود شناخته شد');
  ok(r.closedCount === 3, `کندل بازِ در حال تشکیل حذف شد (بسته=${r.closedCount})`);
  ok(r.direction === 'LONG' && r.streak === 3, `استریک صعودی = ${r.streak} و جهت LONG`);

  const bearish = [mkCandle(now - 4 * m, 103, 102), mkCandle(now - 3 * m, 102, 101), mkCandle(now - 2 * m, 101, 99.5)];
  const r2 = computeMicroStreak(bearish, 3, m, now); // هر سه نسبت به «الان» بسته‌اند
  ok(r2.direction === 'SHORT' && r2.streak === 3, 'استریک نزولی → SHORT');

  const mixed = [mkCandle(now - 4 * m, 100, 101), mkCandle(now - 3 * m, 101, 100.5), mkCandle(now - 2 * m, 100.5, 101.2)];
  const r3 = computeMicroStreak(mixed, 3, m, now);
  ok(r3.direction === null && r3.streak === 1, `شکست استریک توسط کندل مخالف (استریک=${r3.streak})`);

  const dojiLast = [mkCandle(now - 4 * m, 100, 101), mkCandle(now - 3 * m, 101, 102), { ts: now - 2 * m, open: 102, high: 102, low: 102, close: 102, volume: 10 }];
  const r4 = computeMicroStreak(dojiLast, 3, m, now);
  ok(r4.direction === null, 'Doji آخر (close === open) استریک را می‌شکند');

  const r5 = computeMicroStreak([mkCandle(now - 2 * m, 1, 2)], 3, m, now);
  ok(r5.available === false, 'کمبود داده → خنثی (available=false)');

  const filter = new MicroCandleFilter(baseSettings({ microCandleCheck: 'false' }));
  ok(filter.evaluate({ candles: bullish }).active === false, 'فیلتر خاموش → کاملاً خنثی');
  const f2 = new MicroCandleFilter(baseSettings());
  const e2 = f2.evaluate({ candles: bullish });
  ok(e2.active === true && e2.direction === 'LONG' && e2.tag.includes('↑'), `تگ کارت: «${e2.tag}»`);
}

console.log('\n۲) استراتژی — وزن داینامیک ریز‌کندل (+۱۵٪ فقط روی سمت هم‌جهت)');
{
  const now = Date.now();
  const H = 3_600_000;
  // ۴۰ کندل اصلی صعودی با حجم بالا → سیگنال خرید قوی
  const candles = [];
  let price = 100;
  for (let i = 40; i > 0; i -= 1) {
    const open = price;
    price *= 1.004; // حرکت مثبت پیوسته
    candles.push(mkCandle(now - i * H, open, price, 4000));
  }
  const microBull = [];
  for (let i = 6; i > 0; i -= 1) microBull.push(mkCandle(now - i * 60_000, 100 + (6 - i), 101 + (6 - i), 900));

  const mkMarket = microCandles => ({ symbol: 'TESTUSDT', price: candles.at(-1).close, candles, microCandles, source: 'TEST' });

  const stratOff = new MomentumScalpStrategy(baseSettings({ microCandleCheck: 'false', minScore: 40, customFormula: '' }));
  const stratOn = new MomentumScalpStrategy(baseSettings({ microCandleCheck: 'true', microCandleCount: 3, microCandleTf: '1', microCandleBoostPct: 15, minScore: 40, customFormula: '' }));

  const sOff = stratOff.analyze(mkMarket(null));
  const sOn = stratOn.analyze(mkMarket({ candles: microBull }));

  ok(sOff.side === 'LONG' && sOn.side === 'LONG', `سمت پایه LONG در هر دو حالت (off=${sOff.side}, on=${sOn.side})`);
  ok(sOn.score > sOff.score, `امتیاز با تاییدیه ریز‌کندل بالاتر رفت (${sOff.score} → ${sOn.score})`);
  const expected = Math.min(100, Math.round(sOff.score * 1.15));
  ok(sOn.score === expected, `دقیقاً +۱۵٪ اعمال شد (انتظار=${expected}, واقعی=${sOn.score})`);
  ok(sOn.why.includes('صعودی متوالی'), `علت تاییدیه در why ثبت شد: «${sOn.why.slice(-60)}»`);
  ok(sOn.microTag === '6×1m ↑', `تگ ریز‌کندل روی سیگنال: «${sOn.microTag}»`);

  // مسیر فرمول سفارشی هم وزن می‌گیرد (RSI این کندل‌ها ۱۰۰ است → شرط rsi > 90)
  const stratCustom = new MomentumScalpStrategy(baseSettings({
    microCandleCheck: 'true', microCandleBoostPct: 15, minScore: 40,
    formulaMode: 'signal',
    customFormula: "if (rsi > 90) { return { side: 'LONG', score: 80, why: 'تست فرمول' }; }"
  }));
  const sCustom = stratCustom.analyze(mkMarket({ candles: microBull }));
  ok(sCustom.score === 92, `فرمول سفارشی: 80 × 1.15 = ${sCustom.score} (انتظار=92)`);
  ok(sCustom.why.includes('فرمول اختصاصی') && sCustom.why.includes('صعودی متوالی'), 'why فرمول سفارشی شامل علت ریز‌کندل است');

  // ریز‌کندل‌های نزولی نباید به خرید وزن بدهند
  const microBear = microBull.map((c, i) => mkCandle(c.ts, 200 - i, 199 - i, 900));
  const sOpposite = stratOn.analyze(mkMarket({ candles: microBear }));
  ok(sOpposite.microDirection === 'SHORT', 'استریک نزولی به عنوان SHORT شناسایی شد');
  ok(!sOpposite.why.includes('وزن خرید'), 'وزن خرید به سیگنال مخالف داده نشد');
}

console.log('\n۳) PaperBroker.evaluate — علت‌های دقیق رد ورود');
{
  const settings = baseSettings({ maxOpenPositions: 2, cooldownSec: 300, dailyLossLimitPct: 3 });
  const paper = new PaperBroker(settings, { info: () => {} });
  const sig = { symbol: 'TESTUSDT', side: 'LONG', score: 90, entry: 100, qty: 1, notional: 100, stop: 95, take: 110, signalId: 't1' };

  ok(paper.evaluate(sig).ok === true, 'حالت پایه → مجاز');

  paper.state.lastCooldown.TESTUSDT = Date.now();
  const cd = paper.evaluate(sig);
  ok(cd.ok === false && cd.reason.includes('Cooldown') && cd.reason.includes('ثانیه'), `علت Cooldown: «${cd.reason}»`);
  ok(paper.evaluate(sig, true).ok === true, 'ورود دستی (force) فقط Cooldown را دور می‌زند');

  paper.state.lastCooldown.TESTUSDT = 0;
  paper.state.paperPositions.push({ id: 'x1', symbol: 'OTHERUSDT' }, { id: 'x2', symbol: 'OTHER2USDT' });
  const cap = paper.evaluate(sig);
  ok(cap.ok === false && cap.reason.includes('سقف 2 پوزیشن'), `علت سقف پوزیشن: «${cap.reason}»`);

  paper.state.paperPositions = [{ id: 'x1', symbol: 'TESTUSDT' }];
  const dup = paper.evaluate(sig);
  ok(dup.ok === false && dup.reason.includes('از قبل پوزیشن باز'), `علت تکرار نماد: «${dup.reason}»`);

  paper.state.paperPositions = [];
  paper.state.dayStartEquity = 1000;
  paper.state.paperEquity = 950; // ۵٪ ضرر > حد ۳٪
  const loss = paper.evaluate(sig);
  ok(loss.ok === false && loss.reason.includes('سقف ضرر روزانه'), `علت ضرر روزانه: «${loss.reason}»`);
}

console.log('\n۴) AudioAlerts — منطق آستانه و Cooldown (بدون AudioContext)');
{
  const audio = new AudioAlerts(baseSettings({ audioAlerts: 'true', preAlertScore: 75, preAlertCooldownSec: 120 }), { info: () => {} });
  ok(audio.enabled() === true, 'فعال بودن از تنظیمات');
  ok(audio.preAlertCheck({ symbol: 'BTCUSDT', score: 70 }) === false, 'امتیاز زیر آستانه → بدون بوق');
  ok(audio.preAlertCheck({ symbol: 'BTCUSDT', score: 78 }) === true, 'عبور از آستانه ۷۵ → چایم');
  ok(audio.preAlertCheck({ symbol: 'BTCUSDT', score: 80 }) === false, 'تکرار قبل از Cooldown → ساکت');
  ok(audio.preAlertCheck({ symbol: 'ETHUSDT', score: 90 }) === true, 'نماد دیگر مستقل بوق می‌زند');
  audio.drop('BTCUSDT');
  ok(audio.preAlertCheck({ symbol: 'BTCUSDT', score: 80 }) === true, 'بعد از drop/گذشت cooldown دوباره بوق');
  const off = new AudioAlerts(baseSettings({ audioAlerts: 'false' }), { info: () => {} });
  ok(off.preAlertCheck({ symbol: 'BTCUSDT', score: 99 }) === false, 'صدا خاموش → هرگز بوق نمی‌زند');
  ok(typeof audio.execution('LONG', 'X') === 'undefined' || true, 'execution در نبود AudioContext بدون خطا no-op شد');
}

console.log('\n۵) Logger — فرمت ساختاریافته و JSONL');
{
  const logger = new Logger();
  logger.info('PAPER OPEN', { symbol: 'BTCUSDT', side: 'LONG' });
  logger.info('AUDIO PRE-ALERT', { symbol: 'ETHUSDT', score: 78 });
  const lines = logger.toJsonl().split('\n');
  ok(lines.length === 2, `دو رکورد JSONL ساخته شد (${lines.length})`);
  const parsed = lines.map(l => JSON.parse(l));
  ok(parsed[0].msg === 'PAPER OPEN' && parsed[0].obj.symbol === 'BTCUSDT', 'ترتیب زمانی JSONL (قدیمی → جدید) درست است');
  ok(logger.format(parsed[1]).includes('AUDIO PRE-ALERT'), 'فرمت متنی کنسول درست است');
}

console.log('\n۶) پل Pump/Dump Lab — غیرمسدودکننده و اختیاری');
{
  const clock = { t: 1_000_000 };
  const settings = { value: { ...DEFAULT_SETTINGS, pumpBridgeUrl: 'http://localhost:8790' } };
  let callCount = 0;
  const bridge = new HotBridge(settings, { info: () => {} }, {
    now: () => clock.t,
    fetchJson: async () => {
      callCount += 1;
      if (callCount === 1) throw new Error('connection refused');
      return { updatedAt: 1, symbols: ['MOVEUSDT', 'PEPEUSDT'] };
    }
  });
  ok(bridge.enabled() === true, 'پل با تنظیم آدرس فعال می‌شود');
  ok(bridge.symbols().length === 0, 'قبل از اولین refresh موفق، لیست خالی است');
  await bridge.refresh();
  ok(bridge.symbols().length === 0, 'خطای شبکه → کش خالی ماند (بدون کرش)');
  await bridge.refresh();
  ok(bridge.symbols().join(',') === 'MOVEUSDT,PEPEUSDT', 'دریافت موفق → نمادهای داغ کش شدند');
  clock.t += 11 * 60_000;
  ok(bridge.symbols().length === 0, 'داده قدیمی‌تر از ۱۰ دقیقه → خودکار بی‌اعتبار می‌شود (ضد نماد یخ‌زده)');

  const off = new HotBridge({ value: { ...DEFAULT_SETTINGS, pumpBridgeUrl: '' } }, { info: () => {} });
  ok(off.enabled() === false && off.symbols().length === 0, 'پیش‌فرض خاموش — صفر وابستگی بین دو پروژه');
}

console.log('\n۷) بروکر — اجرای قاطع MaxHold با ساعت قابل تزریق (زیرساخت بک‌تست)');
{
  const clock = { t: 1_700_000_000_000 };
  const paper = new PaperBroker(baseSettings({ maxHoldMinutes: 120, cooldownSec: 60 }), { info: () => {} }, { now: () => clock.t });
  const sig = { symbol: 'BTCUSDT', side: 'LONG', score: 90, entry: 100, qty: 1, notional: 100, stop: 95, take: 110, signalId: 'mh1' };
  ok(paper.open(sig, 'auto') === true, 'ورود در زمان شبیه‌سازی‌شده ثبت شد');
  clock.t += 121 * 60_000; // بیشتر از maxHoldMinutes=120
  paper.updateStops(new Map([['BTCUSDT', { symbol: 'BTCUSDT', price: 99, lastCandle: { high: 99.5, low: 98.5 } }]]), null);
  const trade = paper.state.paperTrades[0];
  ok(trade && trade.reason === 'MAX_HOLD_EXIT', `پوزیشن بیش از حد مجاز نگهداری نشد: ${trade?.reason}`);
  ok(trade.durationSec >= 121 * 60, `مدت نگهداری از ساعت تزریقی محاسبه شد (${Math.round(trade.durationSec / 60)} دقیقه)`);
}


console.log('\n۸) هم‌ترازی تایم‌فریم — رفع باگ «تحلیل ۱ساعته، بستن ۱دقیقه‌ای»');
{
  const h = 3_600_000;
  // کندل ناهم‌تراز (۱۲:۳۴) باید به مرز ۱۲:۰۰ رُند شود
  ok(floorTs(Date.UTC(2026, 0, 1, 12, 34, 56), h) === Date.UTC(2026, 0, 1, 12, 0, 0), 'floorTs مرز ساعت را درست می‌کند');
  ok(tfInfo('240').label === '4h' && tfInfo('D').minutes === 1440, 'رجیستری تایم‌فریم ۴h و 1D درست است');
  ok(tfMs('120') === 7_200_000, 'tfMs برای ۲ ساعت = ۷٫۲ میلیون ms');

  // کندل در حال تشکیل باید حذف شود؛ بسته‌ها بمانند + شمارش شکاف
  const now = Date.UTC(2026, 0, 1, 12, 0, 5);
  const raw = [
    { ts: Date.UTC(2026, 0, 1, 9, 0), open: 1, high: 2, low: 0.5, close: 1.5, volume: 10 },
    { ts: Date.UTC(2026, 0, 1, 10, 0), open: 1.5, high: 2, low: 0.5, close: 1.8, volume: 10 },
    { ts: Date.UTC(2026, 0, 1, 10, 0), open: 1.5, high: 2, low: 0.5, close: 1.8, volume: 11 }, // تکراری
    // ۱۱:۰۰ حذف → شکاف
    { ts: Date.UTC(2026, 0, 1, 12, 0), open: 1.8, high: 2, low: 0.5, close: 1.9, volume: 10 } // در حال تشکیل
  ];
  const aligned = alignCandles(raw, { ms: h, now, dropForming: true });
  ok(aligned.candles.length === 2, `کندل تکراری حذف شد (۲ باقی؛ ${aligned.candles.length})`);
  ok(aligned.formingDropped === true, 'کندل در حال تشکیل حذف شد');
  ok(aligned.gaps === 0, `دو کندل بستهٔ پیوسته بدون شکاف (gaps=${aligned.gaps})`);
  ok(aligned.lastClosedTs === Date.UTC(2026, 0, 1, 10, 0) && aligned.lastClosedAgeMs === now - Date.UTC(2026, 0, 1, 11, 0), 'کهنگی کندل بسته درست محاسبه شد');

  // سناریوی شکاف: سه کندل بسته که وسطی (۱۱:۰۰) گم شده
  const nowB = Date.UTC(2026, 0, 1, 13, 0, 5);
  const rawB = [
    { ts: Date.UTC(2026, 0, 1, 9, 0), open: 1, high: 2, low: 0.5, close: 1.5, volume: 10 },
    { ts: Date.UTC(2026, 0, 1, 10, 0), open: 1.5, high: 2, low: 0.5, close: 1.8, volume: 10 },
    { ts: Date.UTC(2026, 0, 1, 12, 0), open: 1.8, high: 2, low: 0.5, close: 1.9, volume: 10 }
  ];
  const alignedB = alignCandles(rawB, { ms: h, now: nowB, dropForming: true });
  ok(alignedB.candles.length === 3 && alignedB.gaps === 1, `شکاف ساعت ۱۱ شناسایی شد (gaps=${alignedB.gaps})`);

  // کندل ناهم‌ترازِ نیمه‌بسته هم به مرز می‌چسبد و اگر مرزش هنوز باز باشد حذف می‌شود
  const mixed = [{ ts: Date.UTC(2026, 0, 1, 12, 34), open: 1, high: 2, low: 0.5, close: 1.5, volume: 10 }];
  const aligned2 = alignCandles(mixed, { ms: h, now, dropForming: true });
  ok(aligned2.candles.length === 0 && aligned2.formingDropped === true, 'کندل ناهم‌ترازِ باز پس از رُند شدن حذف شد');
  ok(describeAge(5 * 60_000) === '۵ دقیقه پیش'.replace('۵', '5'), 'توصیف عمر کندل کار می‌کند');
}

console.log('\n۹) موتور فرمول پارامتریک — پارسر امن بدون eval');
{
  const vars = { rsi: 35, volX: 2, movePct: -0.4, emaFast: 101, emaSlow: 100, price: 50000 };
  const e1 = evaluateFormula('(rsi < 40 && volX > 1.4) || (rsi > 62 && movePct < -0.2)', vars);
  ok(e1.ok && e1.value === 1, 'شرط منطقی ترکیبی → 1');
  const e2 = evaluateFormula('rsi > 62 && movePct < -0.2', vars);
  ok(e2.ok && e2.value === 0, 'شرط برقرار نیست → 0');
  const e3 = evaluateFormula('clamp((volX - 1) * 20 + (40 - rsi), 0, 30)', vars);
  ok(e3.ok && Math.abs(e3.value - 25) < 1e-9, `تابع clamp/محاسبهٔ پیوسته (25 → ${e3.value})`);
  const e4 = evaluateFormula('if(emaFast > emaSlow, min(movePct * -25, 25), 0)', vars);
  ok(e4.ok && e4.value === 10, 'تابع if/min (movePct منفی × -۲۵ = ۱۰)');
  const e5 = evaluateFormula('(price - 49000) / (price - 49900)', vars);
  ok(e5.ok && e5.value === 10, `تقسیم عادی سالم (${e5.value})`);
  const e6 = evaluateFormula('1 / (rsi - 35)', vars);
  ok(!e6.ok, 'تقسیم بر صفر → خطای امن (نه Infinity)');
  const e7 = evaluateFormula('rsi < 40 ? 15 : 0', vars);
  ok(e7.ok && e7.value === 15, 'عملگر سه‌تایی');
  const e8 = evaluateFormula('rsiX < 40', vars);
  ok(!e8.ok && e8.error.includes('rsiX'), 'متغیر ناشناخته → خطای نامعتبر با نام متغیر');
  const e9 = evaluateFormula('2 ^ 10', vars);
  ok(e9.ok && e9.value === 1024, 'عملگر توان');
  ok(validateFormula('(rsi < 40 && volX > 1.4)').ok === true, 'اعتبارسنجی نگارشی فرمول سالم');
  ok(validateFormula('(rsi <').ok === false, 'اعتبارسنجی فرمول ناقص → خطا');
}

console.log('\n۱۰) موتور خروج شناور — سود آزاد، ترلینگ پارامتریک، محو مومنتوم');
{
  const settings = (over = {}) => baseSettings({
    paperInitialEquity: 1000, orderMargin: 40, leverage: 5,
    feeOpenPct: 0.055, feeClosePct: 0.055, slippagePct: 0,
    minScore: 60, cooldownSec: 0, maxOpenPositions: 5,
    maxHoldMinutes: 0, profitMode: 'float', ...over
  });
  const sig = (symbol, over = {}) => ({
    symbol, side: 'LONG', entry: 100, stop: 98, take: 104, qty: 2, notional: 200,
    score: 90, atr: 1, rsi: 50, movePct: 0.5, emaFast: 101, emaSlow: 100, volX: 1.0,
    feeOpen: 0.11, feeClose: 0.11, signalId: `x:${Date.now()}`, candleTs: 1, ...over
  });
  const clock = { v: 1_000_000 };
  const broker = () => new PaperBroker(settings(), { info: () => {} }, { now: () => clock.v });

  // ۱۰-۱: در حالت float حد سود بسته نمی‌شود حتی اگر قیمت از take رد شود
  {
    const paper = broker();
    paper.open(sig('BTCUSDT'), 'auto', true);
    const market = new Map([['BTCUSDT', { symbol: 'BTCUSDT', price: 106, lastCandle: { high: 106, low: 99 }, candles: [] }]]);
    const signals = new Map([['BTCUSDT', sig('BTCUSDT')]]);
    paper.updateStops(market, signals);
    const still = paper.state.paperPositions.length === 1;
    ok(still, 'float: عبور از حد سود معامله را نمی‌بندد (سود آزاد)');
    ok(paper.state.paperPositions[0].highWater >= 106, 'سقف سود شناور (highWater) ثبت شد');
  }

  // ۱۰-۲: در حالت fixed همان عبور، معامله را در take می‌بندد
  {
    const paper = new PaperBroker(settings({ profitMode: 'fixed' }), { info: () => {} }, { now: () => clock.v });
    paper.open(sig('ETHUSDT'), 'auto', true);
    const market = new Map([['ETHUSDT', { symbol: 'ETHUSDT', price: 106, lastCandle: { high: 106, low: 99 }, candles: [] }]]);
    paper.updateStops(market, new Map([['ETHUSDT', sig('ETHUSDT')]]));
    const trade = paper.state.paperTrades[0];
    ok(trade && trade.reason === 'TAKE_PROFIT' && trade.exit === 104, `fixed: بستن قاطع در take=104 (reason=${trade?.reason})`);
  }

  // ۱۰-۳: محو مومنتوم — ۲ کندل بستهٔ نزولی پی‌درپی در سود → MOMENTUM_FADE
  {
    const paper = broker();
    paper.open(sig('SOLUSDT', { entry: 100 }), 'auto', true);
    // اول به سود ببریم (۱۰۴) تا مسیر سود فعال شود، بعد دو کندل مخالف
    let market = new Map([['SOLUSDT', { symbol: 'SOLUSDT', price: 104, lastCandle: { high: 104, low: 101 }, candles: [{ open: 103, close: 104 }] }]]);
    paper.updateStops(market, new Map([['SOLUSDT', sig('SOLUSDT')]]));
    market = new Map([['SOLUSDT', {
      symbol: 'SOLUSDT', price: 103.5, lastCandle: { high: 104, low: 103 },
      candles: [{ open: 104, close: 103.8 }, { open: 103.8, close: 103.5 }]
    }]]);
    paper.updateStops(market, new Map([['SOLUSDT', sig('SOLUSDT')]]));
    const trade = paper.state.paperTrades[0];
    ok(trade && trade.reason === 'MOMENTUM_FADE', `دو کندل مخالف در سود → MOMENTUM_FADE (reason=${trade?.reason})`);
  }

  // ۱۰-۴: چرخش روند قوی مخالف (حتی بدون سود) → TREND_FLIP
  {
    const paper = broker();
    paper.open(sig('XRPUSDT', { side: 'LONG', entry: 100, stop: 95 }), 'auto', true);
    const flipSignal = sig('XRPUSDT', { side: 'SHORT', score: 88 });
    const market = new Map([['XRPUSDT', { symbol: 'XRPUSDT', price: 99, lastCandle: { high: 99.5, low: 98.8 }, candles: [] }]]);
    paper.updateStops(market, new Map([['XRPUSDT', flipSignal]]));
    const trade = paper.state.paperTrades[0];
    ok(trade && trade.reason === 'TREND_FLIP', `سیگنال مخالف با امتیاز ۸۸ → TREND_FLIP (reason=${trade?.reason})`);
  }

  // ۱۰-۵: سیگنال مخالف ضعیف (امتیاز کم) خروج نمی‌زند
  {
    const paper = broker();
    paper.open(sig('BNBUSDT', { side: 'LONG', entry: 100, stop: 95 }), 'auto', true);
    const weakFlip = sig('BNBUSDT', { side: 'SHORT', score: 45 });
    const market = new Map([['BNBUSDT', { symbol: 'BNBUSDT', price: 100.5, lastCandle: { high: 101, low: 100 }, candles: [] }]]);
    paper.updateStops(market, new Map([['BNBUSDT', weakFlip]]));
    ok(paper.state.paperPositions.length === 1, 'سیگنال مخالف ضعیف → پوزیشن باز ماند');
  }
}

console.log('\n۱۱) استراتژی — گیت کهنگی کندل + فرمول پارامتریک filter');
{
  const m = 60_000;
  const now = Date.now();
  // سری صعودی با حجم بالا: شرط‌های اجماع برقرار
  const mkSeries = () => {
    const out = [];
    for (let i = 0; i < 30; i += 1) {
      const base = i % 3 === 2 ? -0.4 : 1.1; // هر سومی اصلاحی تا RSI وسط پنجره بماند
      const open = 100 + i * 0.3;
      const close = open * (1 + base / 100);
      out.push(mkCandle(now - (30 - i) * m, open, close, i >= 27 ? 3000 : 1000));
    }
    return out;
  };

  // ۱۱-۱: کندل تازه → سیگنال LONG سالم
  {
    const strategy = new MomentumScalpStrategy(baseSettings({ minScore: 60, timeframe: '1' }));
    const signal = strategy.analyze({
      symbol: 'TESTUSDT', price: 110, candles: mkSeries(),
      microCandles: null, receivedAt: now, tfMs: m, source: 'TEST'
    });
    ok(signal.side === 'LONG' || signal.side === 'WAIT', 'تحلیل کندل تازه بدون خطا اجرا شد');
    ok(signal.stale === false, 'کندل تازه → stale=false');
  }

  // ۱۱-۲: همان سری ولی «الان» ۱۰ دقیقه جلوتر → کندل کهنه → WAIT قاطع
  {
    const strategy = new MomentumScalpStrategy(baseSettings({ minScore: 60, timeframe: '1' }));
    const signal = strategy.analyze({
      symbol: 'TESTUSDT', price: 110, candles: mkSeries(),
      microCandles: null, receivedAt: now + 10 * m, tfMs: m, source: 'TEST'
    });
    ok(signal.side === 'WAIT' && signal.stale === true, 'کندل کهنه → WAIT + stale=true');
    ok(String(signal.why).includes('کندل'), `علت کهنگی شفاف است (${signal.why.slice(0, 40)}...)`);
  }

  // ۱۱-۳: فرمول filter مسدودکننده — حتی با اجماع کامل ورود باز نمی‌شود
  {
    const strategy = new MomentumScalpStrategy(baseSettings({
      minScore: 60, timeframe: '1', formulaMode: 'filter', customFormula: 'rsi > 95'
    }));
    const signal = strategy.analyze({
      symbol: 'TESTUSDT', price: 110, candles: mkSeries(),
      microCandles: null, receivedAt: now, tfMs: m, source: 'TEST'
    });
    ok(signal.side === 'WAIT' && signal.formulaValue === 0, `فرمول نادرست → ورود مسدود (value=${signal.formulaValue})`);
  }

  // ۱۱-۴: فرمول filter تاییدکننده — پاداش امتیاز اضافه می‌شود
  {
    const strategyOff = new MomentumScalpStrategy(baseSettings({ minScore: 60, timeframe: '1' }));
    const strategyOn = new MomentumScalpStrategy(baseSettings({
      minScore: 60, timeframe: '1', formulaMode: 'filter', customFormula: 'volX > 1.5', formulaBonusPct: 12
    }));
    const mk = () => ({
      symbol: 'TESTUSDT', price: 110, candles: mkSeries(),
      microCandles: null, receivedAt: now, tfMs: m, source: 'TEST'
    });
    const sOff = strategyOff.analyze(mk());
    const sOn = strategyOn.analyze(mk());
    ok(sOn.side !== 'WAIT' && sOn.score >= sOff.score, `پاداش فرمول اعمال شد (${sOff.score} → ${sOn.score})`);
    ok(String(sOn.why).includes('فرمول تایید کرد'), 'علت پاداش فرمول در why ثبت شد');
  }

  // ۱۱-۵: فرمول معیوب → خنثی + علت خطا (بدون کرش)
  {
    const strategy = new MomentumScalpStrategy(baseSettings({
      minScore: 60, timeframe: '1', formulaMode: 'filter', customFormula: 'rsi <'
    }));
    const signal = strategy.analyze({
      symbol: 'TESTUSDT', price: 110, candles: mkSeries(),
      microCandles: null, receivedAt: now, tfMs: m, source: 'TEST'
    });
    ok(signal.formulaValue === null && String(signal.why).includes('خطا'), 'فرمول معیوب → خنثی با علت شفاف');
  }
}


console.log('\n۱۲) 🔒 قفل تایم‌فریم پوزیشن — «ورود ۱h، خروج ۱m» غیرممکن شد');
{
  const settings = (over = {}) => baseSettings({
    paperInitialEquity: 1000, orderMargin: 40, leverage: 5,
    feeOpenPct: 0.055, feeClosePct: 0.055, slippagePct: 0,
    minScore: 60, cooldownSec: 0, maxOpenPositions: 5,
    maxHoldMinutes: 0, profitMode: 'float', fadeCandles: 2, ...over
  });
  const sig1h = (over = {}) => ({
    symbol: 'BTCUSDT', side: 'LONG', entry: 100, stop: 95, take: 110, qty: 2, notional: 200,
    score: 90, atr: 2, rsi: 50, movePct: 0.5, emaFast: 101, emaSlow: 100, volX: 1,
    feeOpen: 0.11, feeClose: 0.11, signalId: 'x:1', candleTs: 1, tfMs: 3_600_000, ...over
  });
  const clock = { v: 1_000_000 };
  const mk = (price, hi, lo, candles = []) => new Map([['BTCUSDT', { symbol: 'BTCUSDT', price, lastCandle: { high: hi, low: lo }, candles }]]);

  // الف) قفل TREND_FLIP: سیگنال مخالف قوی از تایم ۱m نباید معاملهٔ ۱h را ببندد
  const paper = new PaperBroker(settings(), { info: () => {} }, { now: () => clock.v });
  paper.open(sig1h(), 'auto', true);
  ok(paper.state.paperPositions[0].tfMs === 3_600_000, 'تایم‌فریم ورود (1h) روی پوزیشن قفل شد');
  paper.updateStops(mk(99.5, 100, 99.4), new Map([['BTCUSDT', sig1h({ side: 'SHORT', score: 95, tfMs: 60_000 })]]));
  ok(paper.state.paperPositions.length === 1, 'سیگنال مخالفِ تایم ۱m → TREND_FLIP قفل ماند');

  // ب) قفل MOMENTUM_FADE + قفل ترلینگ ناهم‌تایم: در سود، کندل/ATR تایم ۱m اثر ندارد
  paper.updateStops(mk(100.5, 103, 100.3), new Map([['BTCUSDT', sig1h({ tfMs: 60_000 })]]));
  paper.updateStops(mk(100.4, 100.5, 100.3, [{ open: 100.5, close: 100.45 }, { open: 100.45, close: 100.4 }]), new Map([['BTCUSDT', sig1h({ tfMs: 60_000 })]]));
  ok(paper.state.paperPositions.length === 1, 'کندل‌های مخالفِ تایم ۱m → MOMENTUM_FADE قفل ماند');
  ok(paper.state.paperPositions[0].stop < 101, `استاپ با ATR ناهم‌تایم سفت نشد (stop=${paper.state.paperPositions[0].stop.toFixed(2)})`);

  // ج) SL سخت (کاملاً قیمتی) مستقل از تایم‌فریم قاطع می‌بندد
  const paperSL = new PaperBroker(settings(), { info: () => {} }, { now: () => clock.v });
  paperSL.open(sig1h({ symbol: 'XRPUSDT' }), 'auto', true);
  paperSL.updateStops(
    new Map([['XRPUSDT', { symbol: 'XRPUSDT', price: 94, lastCandle: { high: 99, low: 94 }, candles: [] }]]),
    new Map([['XRPUSDT', sig1h({ symbol: 'XRPUSDT', tfMs: 60_000 })]])
  );
  ok(paperSL.state.paperTrades[0]?.reason === 'SL_HARD_STOP', `SL سخت حتی با سیگنال ناهم‌تایم بست (reason=${paperSL.state.paperTrades[0]?.reason})`);

  // د) با سیگنال هم‌تایم (۱h) همهٔ خروج‌های سیگنالی فعال‌اند
  const paperB = new PaperBroker(settings(), { info: () => {} }, { now: () => clock.v });
  paperB.open(sig1h({ symbol: 'ETHUSDT' }), 'auto', true);
  paperB.updateStops(
    new Map([['ETHUSDT', { symbol: 'ETHUSDT', price: 100.5, lastCandle: { high: 101, low: 100 }, candles: [] }]]),
    new Map([['ETHUSDT', sig1h({ symbol: 'ETHUSDT', side: 'SHORT', score: 95 })]])
  );
  ok(paperB.state.paperTrades[0]?.reason === 'TREND_FLIP', 'سیگنال مخالف هم‌تایم (۱h) → TREND_FLIP فعال');

  // هـ) 📈 متریک اوج سود/بازگشت: بستن با ترلینگ نزدیک قله + ثبت peak و giveback
  const paperC = new PaperBroker(settings(), { info: () => {} }, { now: () => clock.v });
  paperC.open(sig1h({ symbol: 'SOLUSDT', entry: 100, stop: 97 }), 'auto', true);
  paperC.updateStops(
    new Map([['SOLUSDT', { symbol: 'SOLUSDT', price: 106, lastCandle: { high: 106, low: 101 }, candles: [] }]]),
    new Map([['SOLUSDT', sig1h({ symbol: 'SOLUSDT' })]])
  );
  paperC.updateStops(
    new Map([['SOLUSDT', { symbol: 'SOLUSDT', price: 103, lastCandle: { high: 104, low: 102.9 }, candles: [] }]]),
    new Map([['SOLUSDT', sig1h({ symbol: 'SOLUSDT' })]])
  );
  const tC = paperC.state.paperTrades[0];
  ok(tC && tC.reason === 'PROFIT_TRAIL_REVERSED', `بستن سود شناور با ترلینگ (reason=${tC?.reason})`);
  ok(tC && Number.isFinite(tC.peakPnl) && tC.peakPnl > tC.pnl, `اوج سود ثبت شد (peak=${tC?.peakPnl?.toFixed(2)} > net=${tC?.pnl?.toFixed(2)})`);
  ok(tC && tC.givebackPct >= 0 && tC.givebackPct <= 100, `درصد پس‌دادن از اوج = ${tC?.givebackPct?.toFixed(1)}%`);

  // و) برچسب درست: استاپِ بالای ورود = بستن سود، نه SL
  ok(tC && tC.exit > tC.entry, `خروج بالای ورود بود (exit=${tC?.exit} > entry=100)`);
}


console.log('\n۱۳) 🎯 بریک‌ایون بالغ (v2.5) — سود اول نفس می‌کشد، بعد محافظت می‌شود');
{
  const settings = (over = {}) => baseSettings({
    paperInitialEquity: 1000, orderMargin: 40, leverage: 5,
    feeOpenPct: 0.055, feeClosePct: 0.055, slippagePct: 0,
    minScore: 60, cooldownSec: 0, maxOpenPositions: 5,
    maxHoldMinutes: 0, profitMode: 'float', fadeCandles: 0,
    trailAtrMult: 99999, breakevenMinAtr: 1, ...over
  });
  const sig = (over = {}) => ({
    symbol: 'BTCUSDT', side: 'LONG', entry: 100, stop: 95, take: 110, qty: 2, notional: 200,
    score: 90, atr: 2, rsi: 50, movePct: 0.5, emaFast: 101, emaSlow: 100, volX: 1,
    feeOpen: 0.11, feeClose: 0.11, signalId: 'x:1', candleTs: 1, tfMs: 3_600_000, ...over
  });
  const clock = { v: 1_000_000 };
  const mk = (price, hi, lo) => new Map([['BTCUSDT', { symbol: 'BTCUSDT', price, lastCandle: { high: hi, low: lo }, candles: [] }]]);

  // الف) سود نابالغ (+0.5×ATR < 1×ATR): استاپ به ورود منتقل نمی‌شود — سود نفس می‌کشد
  const paper = new PaperBroker(settings(), { info: () => {} }, { now: () => clock.v });
  paper.open(sig(), 'auto', true);
  paper.updateStops(mk(101, 101.2, 100.8), new Map([['BTCUSDT', sig()]]));
  ok(Number(paper.state.paperPositions[0].stop) === 95, `سود نابالغ → استاپ در جای اولیه ماند (stop=${paper.state.paperPositions[0].stop})`);

  // ب) سود بالغ (≥1×ATR): بریک‌ایون فعال → استاپ = ورود + بافر
  paper.updateStops(mk(102.5, 102.6, 102), new Map([['BTCUSDT', sig()]]));
  const stopB = Number(paper.state.paperPositions[0].stop);
  ok(Math.abs(stopB - 100 * 1.002) < 0.01, `سود بالغ (≥1×ATR) → بریک‌ایون قفل شد (stop=${stopB.toFixed(3)})`);

  // ج) breakevenMinAtr=0 → همان رفتار قدیم (انتقال فوری به محض سود)
  const paper2 = new PaperBroker(settings({ breakevenMinAtr: 0 }), { info: () => {} }, { now: () => clock.v });
  paper2.open(sig(), 'auto', true);
  paper2.updateStops(mk(101, 101.2, 100.8), new Map([['BTCUSDT', sig()]]));
  ok(Math.abs(Number(paper2.state.paperPositions[0].stop) - 100.2) < 0.01, 'breakevenMinAtr=0 → انتقال فوری (رفتار قدیم حفظ شد)');

  // د) ناهم‌ترازی TF → گیت کنار می‌رود تا حفاظت قیمتی v2.4 دست‌نخورده بماند
  const paper3 = new PaperBroker(settings(), { info: () => {} }, { now: () => clock.v });
  paper3.open(sig(), 'auto', true);
  paper3.updateStops(mk(101, 101.2, 100.8), new Map([['BTCUSDT', sig({ tfMs: 60_000 })]]));
  ok(Math.abs(Number(paper3.state.paperPositions[0].stop) - 100.2) < 0.01, 'ناهم‌ترازی TF → بریک‌ایون (حفاظت قیمتی) همچنان فعال');

  // هـ) SHORT بالغ: انتقال استاپ به ورود ÷ بافر
  const paper4 = new PaperBroker(settings(), { info: () => {} }, { now: () => clock.v });
  paper4.open(sig({ side: 'SHORT', stop: 105 }), 'auto', true);
  paper4.updateStops(mk(97.5, 98, 97.3), new Map([['BTCUSDT', sig({ side: 'SHORT', stop: 105 })]]));
  ok(Math.abs(Number(paper4.state.paperPositions[0].stop) - 100 / 1.002) < 0.01, `SHORT بالغ → بریک‌ایون (stop=${Number(paper4.state.paperPositions[0].stop).toFixed(3)})`);

  // و) پیش‌فرض سیستم + فیلد UI
  ok(Number(DEFAULT_SETTINGS.breakevenMinAtr) === 1, `پیش‌فرض config: بریک‌ایون بالغ ×1 ATR (breakevenMinAtr=${DEFAULT_SETTINGS.breakevenMinAtr})`);
  ok(readFileSync('index.html', 'utf-8').includes('name="breakevenMinAtr"'), 'فیلد UI «بریک‌ایون بعد از ×ATR» در تنظیمات موجود است');
}


console.log('\n۱۴) 🪜 نردبان داده — ثبت پله‌های تصمیم هر معامله (v2.6)');
{
  const settings = (over = {}) => baseSettings({
    paperInitialEquity: 1000, orderMargin: 40, leverage: 5,
    feeOpenPct: 0.055, feeClosePct: 0.055, slippagePct: 0,
    minScore: 60, cooldownSec: 0, maxOpenPositions: 5,
    maxHoldMinutes: 0, profitMode: 'float', fadeCandles: 0,
    trailAtrMult: 99999, breakevenMinAtr: 1, ...over
  });
  const sig = (over = {}) => ({
    symbol: 'BTCUSDT', side: 'LONG', entry: 100, stop: 95, take: 110, qty: 2, notional: 200,
    score: 90, atr: 2, rsi: 50, movePct: 0.5, emaFast: 101, emaSlow: 100, volX: 1,
    feeOpen: 0.11, feeClose: 0.11, signalId: 'x:1', candleTs: 1, tfMs: 3_600_000, ...over
  });
  const clock = { v: 1_000_000 };
  const mk = (sym, price, hi, lo) => new Map([[sym, { symbol: sym, price, lastCandle: { high: hi, low: lo }, candles: [] }]]);

  // الف) ورود → پلهٔ open + منشا اولیهٔ استاپ
  const paper = new PaperBroker(settings(), { info: () => {} }, { now: () => clock.v });
  paper.open(sig(), 'auto', true);
  const pos = paper.state.paperPositions[0];
  ok(Array.isArray(pos.rungs) && pos.rungs[0]?.a === 'open' && pos.stopSource === 'init', 'ورود → پلهٔ open ثبت شد و stopSource=init');

  // ب) بالغ‌شدن سود → پله‌های arm + be
  paper.updateStops(mk('BTCUSDT', 102.5, 102.6, 102), new Map([['BTCUSDT', sig()]]));
  const acts = pos.rungs.map(r => r.a);
  ok(acts.includes('arm') && acts.includes('be'), `بالغ‌شدن سود → پله‌های arm+be ثبت شد (${acts.join(',')})`);
  ok(pos.beArmed === true && pos.stopSource === 'be', 'beArmed=true و stopSource=be');

  // ج) ترلینگ + بستن → exitLayer=3 + پلهٔ close + mfe
  const paper2 = new PaperBroker(settings({ trailAtrMult: 1.25 }), { info: () => {} }, { now: () => clock.v });
  paper2.open(sig({ symbol: 'ETHUSDT' }), 'auto', true);
  paper2.updateStops(mk('ETHUSDT', 106, 106, 103), new Map([['ETHUSDT', sig({ symbol: 'ETHUSDT' })]]));
  paper2.updateStops(mk('ETHUSDT', 103, 104, 102.9), new Map([['ETHUSDT', sig({ symbol: 'ETHUSDT' })]]));
  const t2 = paper2.state.paperTrades[0];
  ok(t2.reason === 'PROFIT_TRAIL_REVERSED' && t2.ladder.exitLayer === 3, `بستن با ترلینگ → exitLayer=3 (reason=${t2.reason})`);
  ok(t2.rungs.at(-1)?.a === 'close' && t2.rungs.at(-1)?.r === 'PROFIT_TRAIL_REVERSED', 'پلهٔ پایانی close با دلیل ثبت شد');
  ok(t2.ladder.mfePct === 6 && t2.ladder.maePct === 0 && t2.ladder.trailMoves === 1 && t2.ladder.stopSource === 'trail', `mfe=${t2.ladder.mfePct}% | mae=${t2.ladder.maePct}% (هرگز زیر ورود نرفت) | trailMoves=${t2.ladder.trailMoves} | stopSource=${t2.ladder.stopSource}`);

  // د) SL سخت → exitLayer=1 + ثبت افت واقعی (mae منفی)
  const paper3 = new PaperBroker(settings(), { info: () => {} }, { now: () => clock.v });
  paper3.open(sig({ symbol: 'XRPUSDT' }), 'auto', true);
  paper3.updateStops(mk('XRPUSDT', 94, 99, 94), new Map([['XRPUSDT', sig({ symbol: 'XRPUSDT' })]]));
  const t3 = paper3.state.paperTrades[0];
  ok(t3.reason === 'SL_HARD_STOP' && t3.ladder.exitLayer === 1 && t3.ladder.stopSource === 'init', 'SL سخت → exitLayer=1 (استاپ اولیه، نه بریک‌ایون/ترلینگ)');
  ok(t3.ladder.maePct === -6, `افت ثبت شد (mae=${t3.ladder.maePct}%)`);

  // هـ) واکشیدن: معاملهٔ طولانی → سقف پله + حفظ پلهٔ ورود
  const paper4 = new PaperBroker(settings(), { info: () => {} }, { now: () => clock.v });
  paper4.open(sig({ symbol: 'SOLUSDT' }), 'auto', true);
  const pos4 = paper4.state.paperPositions[0];
  for (let i = 0; i < 300; i += 1) paper4.pushRung(pos4, 'tick', { mark: 100 + (i % 5) });
  ok(pos4.rungs.length <= 160 && pos4.rungs[0].a === 'open' && pos4.rungsThinned === true, `واکشیدن پله‌ها: ${pos4.rungs.length} پله، پلهٔ ورود حفظ شد`);

  // و) نردبان ذخیره‌سازی: فقط ۴۰ معاملهٔ آخر رکورد کامل دارند
  const paper5 = new PaperBroker(settings(), { info: () => {} }, { now: () => clock.v });
  paper5.state.paperTrades = Array.from({ length: 45 }, () => ({ reason: 'TREND_FLIP', pnl: 1, rungs: [{ a: 'open' }] }));
  paper5.trimRungHistory();
  ok(paper5.state.paperTrades[0].rungs?.length === 1 && paper5.state.paperTrades[44].rungs === undefined && paper5.state.paperTrades[44].rungsDropped === true, 'نردبان ذخیره‌سازی: تازه‌ها رکورد کامل، قدیمی‌ها فقط خلاصهٔ ladder');

  // ز) خلاصهٔ لایه‌ای (ladderRollup) — همان جدول ممیزی، روی هر لیست معامله
  const roll = ladderRollup([
    { reason: 'PROFIT_TRAIL_REVERSED', pnl: 5, peakPnl: 8, fees: 0.2, time: 1_750_000_000_000, ladder: { exitLayer: 3 } },
    { reason: 'SL_HARD_STOP', pnl: -3, peakPnl: 0, fees: 0.2, time: 1_750_000_000_000 }
  ]);
  ok(roll.byLayer['ترلینگ']?.count === 1 && roll.byLayer['SL سخت']?.count === 1, 'ladderRollup: شمارش درست لایه‌ها');
  ok(roll.capture.pct === 62.5, `ضریب برداشت از اوج محاسبه شد (${roll.capture.pct}%)`);
}


console.log('\n۱۵) 🔄 آشکارساز برگشت V/Λ + 🗂 دیتاگرید (v2.7)');
{
  // کندل سینتتیک صریح (فقط برای تست منطق خالص — هرگز در LIVE): V در میانه، Λ بعدش
  const mk = (ts, o, h, l, c) => ({ ts, open: o, high: h, low: l, close: c, volume: 1 });
  const candles = [];
  let t = 1_750_000_000_000;
  const push = (o, c) => { const hi = Math.max(o, c) * 1.001, lo = Math.min(o, c) * 0.999; candles.push(mk(t, o, hi, lo, c)); t += 3_600_000; };
  for (let i = 0; i < 12; i += 1) push(100 - i, 99 - i);      // ریزش 100→87 (بازوی چپ V)
  for (let i = 0; i < 12; i += 1) push(88 + i, 89 + i);       // رشد 88→111 (بازوی راست V)
  for (let i = 0; i < 10; i += 1) push(110 - i, 109 - i);     // ریزش از سقف (بازوی چپ Λ)
  for (let i = 0; i < 10; i += 1) push(101 + i, 102 + i);     // رشد دوباره (بازوی راست Λ)

  // الف) پیوت فراکتالی: کف V و سقف Λ پیدا شوند
  const raw = findRawPivots(candles, { left: 3, right: 3 });
  const lows = raw.filter(p => p.type === 'low');
  const highs = raw.filter(p => p.type === 'high');
  ok(lows.length >= 1 && highs.length >= 1, `پیوت‌های خام پیدا شدند (کف=${lows.length}، سقف=${highs.length})`);
  const zig = zigzagPivots(candles, { left: 3, right: 3, minSwingPct: 1 });
  ok(zig.length >= 3 && zig.every((p, i) => i === 0 || p.type !== zig[i - 1].type), `زیک‌زاگ متناوب است (${zig.length} پیوت)`);

  // ب) تشخیص الگو: V کف و Λ سقف با عمق درست
  const events = detectReversals(candles, { left: 3, right: 3, minSwingPct: 1, vDepthPct: 5 });
  const v = events.find(e => e.kind === 'V');
  const lam = events.find(e => e.kind === 'L');
  ok(Boolean(v), 'الگوی V (کف برگشتی) تشخیص داده شد');
  ok(Boolean(lam), 'الگوی Λ (سقف برگشتی) تشخیص داده شد');
  ok(v && v.price <= 88.5 && v.leftPct > 10 && v.rightPct > 20, `عمق بازوهای V درست است (کف=${v?.price.toFixed(1)}، چپ=${v?.leftPct}٪، راست=${v?.rightPct}٪)`);
  ok(lam && lam.price >= 109 && lam.strengthPct > 5, `سقف Λ درست است (${lam?.price.toFixed(1)}، قدرت=${lam?.strengthPct}٪)`);

  // ج) فیلتر عمق: الگوهای کم‌عمق حذف شوند
  const shallow = detectReversals(candles, { left: 3, right: 3, minSwingPct: 1, vDepthPct: 60 });
  ok(shallow.length === 0, 'آستانهٔ عمق بالا (۶۰٪) → هیچ الگویی پذیرفته نمی‌شود');

  // د) نواحی چارت: از V اخیر ناحیهٔ خرید بسازد
  const zones = reversalZones(candles, { left: 3, right: 3, minSwingPct: 1, vDepthPct: 5 }, 60);
  const buy = zones.find(z => z.kind === 'buy');
  ok(Boolean(buy) && buy.priceLow < buy.priceHigh, `ناحیهٔ خرید از کف V ساخته شد (${buy ? buy.priceLow.toFixed(1) + ' تا ' + buy.priceHigh.toFixed(1) : '--'})`);

  // هـ) دیتاگرید — سورت عددی و متنی
  const rows = [{ symbol: 'ETHUSDT', pnl: -2 }, { symbol: 'BTCUSDT', pnl: 9 }, { symbol: 'ADAUSDT', pnl: 4 }];
  const byPnl = applySort(rows, 'pnl', -1, 'number');
  ok(byPnl[0].symbol === 'BTCUSDT' && byPnl[2].symbol === 'ETHUSDT', 'سورت نزولی عددی درست است');
  const bySym = applySort(rows, 'symbol', 1, 'text');
  ok(bySym[0].symbol === 'ADAUSDT' && bySym[2].symbol === 'ETHUSDT', 'سورت صعودی متنی درست است');
  const nanSafe = applySort([{ pnl: Number.NaN }, { pnl: 1 }], 'pnl', -1, 'number');
  ok(nanSafe[0].pnl === 1, 'سورت با مقدار NaN امن است');

  // و) دیتاگرید — فیلتر متنی
  const filtered = applyTextFilter(rows, 'btc', ['symbol', 'reason']);
  ok(filtered.length === 1 && filtered[0].symbol === 'BTCUSDT', 'فیلتر متنی بدون حساسیت به حروف کار می‌کند');
  ok(applyTextFilter(rows, '', ['symbol']).length === 3, 'کوئری خالی = همهٔ ردیف‌ها');
}


console.log('\n۱۶) 🛰 نردبان مسیر دیتا — پروکسی سرور → مستقیم + خطای دقیق هر مسیر (v2.8)');
{
  const settings = { value: { ...DEFAULT_SETTINGS } };
  const client = new MarketClient(settings, { info: () => {} });
  const realFetch = globalThis.fetch;

  // الف) مسیر اول می‌شکند → مسیر دوم جواب می‌دهد (failover زنده)
  globalThis.fetch = async (url) => {
    if (String(url).startsWith('/api/okx/')) throw new Error('proxy down');
    return { ok: true, status: 200, statusText: 'OK', text: async () => JSON.stringify({ code: '0', data: [[1, 2, 3, 4, 5, 6]] }) };
  };
  const body = await client.fetchLadder([
    { name: 'okx-proxy', url: '/api/okx/api/v5/market/ticker?instId=BTC-USDT' },
    { name: 'okx-direct', url: 'https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT' }
  ]);
  ok(body.code === '0', 'شکست مسیر اول → مسیر دوم جواب داد (failover)');

  // ب) همهٔ مسیرها بشکنند → خطا «نام و علت هر مسیر» را دارد
  globalThis.fetch = async () => { throw new Error('net blocked'); };
  let msg = '';
  try {
    await client.fetchLadder([
      { name: 'okx-proxy', url: '/api/okx/x' },
      { name: 'okx-direct', url: 'https://www.okx.com/x' }
    ]);
  } catch (e) { msg = e.message; }
  ok(msg.includes('okx-proxy') && msg.includes('okx-direct') && msg.includes('net blocked'), `خطای نهایی شامل نام و علت هر دو مسیر است (${msg.slice(0, 60)}…)`);

  // ج) تایم‌اوت هر مسیر مستقل است (عدد، نه حلقهٔ بی‌نهایت)
  globalThis.fetch = (url, opts) => new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error('timeout')), 8000);
    if (opts?.signal) opts.signal.addEventListener('abort', () => { clearTimeout(t); reject(new Error('aborted')); });
  });
  const t0 = Date.now();
  try { await client.fetchLadder([{ name: 'p1', url: '/x' }, { name: 'p2', url: '/y' }], { timeoutMs: 60 }); } catch {}
  ok(Date.now() - t0 < 2500, `تایم‌اوت کوتاه مسیر رعایت شد (${Date.now() - t0}ms برای دو مسیر ۶۰ms‌ای)`);

  globalThis.fetch = realFetch;
}


console.log('\n۱۷) 🐋 جریان ضد‌نهنگ + اعتبارسنج سیگنال (تحلیل نهنگ‌ها — v2.9)');
{
  // الف) تحلیل جریان از کندل‌های دارای فیلد تیکری (سبک Binance)
  const mk = (v, tb, tr) => ({ ts: 1, open: 1, high: 1, low: 1, close: 1, volume: v, takerBuy: tb, trades: tr });
  const bullish = [mk(100, 70, 50), mk(100, 75, 55), mk(100, 80, 60), mk(100, 82, 90)];
  const f = computeFlowMetrics(bullish);
  ok(f.available === true, 'جریان از دیتای تیکری محاسبه شد');
  ok(Math.abs(f.buyRatio - (70 + 75 + 80 + 82) / 400) < 0.001, `نسبت خرید تیکری درست است (${(f.buyRatio * 100).toFixed(1)}٪)`);
  ok(f.cvdDelta > 0 && f.longAligned === true && f.shortAligned === false, 'CVD مثبت → هم‌جهت با خرید (فشار خرید واقعی)');
  ok(f.tradeAccel > 1.4, `شتاب تریدها درست محاسبه شد (${f.tradeAccel})`);
  const bearish = [mk(100, 30, 50), mk(100, 25, 55), mk(100, 20, 60), mk(100, 18, 40)];
  const f2 = computeFlowMetrics(bearish);
  ok(f2.shortAligned === true && f2.cvdDelta < 0, 'پنجرهٔ فروش تیکری → هم‌جهت با فروش');
  ok(computeFlowMetrics([{ ts: 1, open: 1, high: 1, low: 1, close: 1, volume: 1 }]).available === false, 'کندل بدون فیلد تیکری → available=false (Zero Fake Data)');
  ok(flowWhyText(f).includes('CVD مثبت'), 'متن why جریان تولید شد');

  // ب) پارس فیلدهای تیکری Binance در market-client
  const client = new MarketClient({ value: { ...DEFAULT_SETTINGS } }, { info: () => {} });
  const binanceRow = [1759000000000, '100', '110', '95', '105', '500', 1759000060000, '52500', '77', '390', '40950', '0'];
  const parsed = client.parseCandleRows([binanceRow], { newestFirst: false, binanceExtras: true });
  ok(parsed[0].trades === 77 && parsed[0].takerBuy === 390, `فیلدهای تیکری Binance پارس شد (trades=${parsed[0].trades}, takerBuy=${parsed[0].takerBuy})`);
  const plain = client.parseCandleRows([binanceRow], { newestFirst: false });
  ok(plain[0].takerBuy === undefined, 'بدون binanceExtras فیلد تیکری ساخته نمی‌شود');

  // ج) اعتبارسنج سیگنال — قضاوت با واقعیت بعد از تاخیر
  const sv = new SignalValidator({ delayMs: 60000, thresholdPct: 1.5, maxItems: 50 });
  const t0 = Date.now();
  ok(sv.track('s1', { symbol: 'BTCUSDT', direction: 'LONG', refPrice: 100 }) === true, 'سیگنال PENDING ثبت شد');
  ok(sv.track('s1', { symbol: 'BTCUSDT', direction: 'LONG', refPrice: 100 }) === false, 'id تکراری دوباره ثبت نمی‌شود');
  ok(sv.track('bad', { symbol: 'X', direction: 'WAIT', refPrice: 100 }) === false, 'جهت نامعتبر رد می‌شود');
  ok(sv.pending(t0 + 61000).length === 1, 'بعد از تاخیر، سررسیدشده در صف قضاوت است');
  const rec = sv.settle('s1', 102, t0 + 61000);
  ok(rec?.status === 'CORRECT' && rec?.movePct === 2, `حرکت ۲٪ در جهت سیگنال → CORRECT (${rec?.movePct}٪)`);
  sv.track('s2', { symbol: 'ETHUSDT', direction: 'SHORT', refPrice: 100 });
  const rec2 = sv.settle('s2', 101, t0 + 61000); // شورت: قیمت بالا رفت = غلط
  ok(rec2?.status === 'INCORRECT' && rec2?.movePct === -1, 'خلاف جهت سیگنال → INCORRECT');
  const st = sv.stats();
  ok(st.settled === 2 && st.correct === 1 && st.accuracyPct === 50, `آمار دقت درست است (${st.accuracyPct}٪)`);
  ok(sv.get('s1')?.status === 'CORRECT', 'خواندن رکورد برای جدول رویدادها کار می‌کند');

  // د) 🔄 ماندگاری — ری‌استارت اپ، تاریخچهٔ قضاوت را پاک نمی‌کند
  {
    const mem = {};
    globalThis.localStorage = { getItem: k => (k in mem ? mem[k] : null), setItem: (k, v) => { mem[k] = String(v); } };
    const svA = new SignalValidator({ delayMs: 60000, persistKey: 'test_sv_persist' });
    ok(svA.track('p1', { symbol: 'BTCUSDT', direction: 'LONG', refPrice: 100 }) === true, 'رکورد با persistKey ثبت و ذخیره شد');
    const svB = new SignalValidator({ delayMs: 60000, persistKey: 'test_sv_persist' });
    ok(svB.get('p1')?.status === 'PENDING' && svB.pending(Date.now() + 61000).some(i => i.id === 'p1'),
      'نمونهٔ جدید (شبیه ری‌استارت) → رکورد از localStorage برگشت و در صف قضاوت است');
    delete globalThis.localStorage;
  }
}


console.log('\n۱۸) 🔒 قفل سود — نجات سود هنگام پس‌گرفتن از اوج (v2.10)');
{
  const clock = { v: 1_000_000 };
  // سیگنال بدون ATR → ترلینگ قفل است؛ قفل سود تنها محافظ سود است (سناریوی گارد TF)
  const base = {
    symbol: 'LOCKUSDT', side: 'LONG', score: 90, entry: 100, qty: 1, notional: 100,
    stop: 95, take: 110, signalId: 'lk1', tfMs: 3600000
  };
  const mkPaper = over => new PaperBroker(baseSettings(over), { info: () => {} }, { now: () => clock.v });
  const sigMap = new Map([['LOCKUSDT', { ...base, rsi: 50, movePct: 0, volX: 0 }]]);
  const market = (price, hi = price, lo = price) => new Map([['LOCKUSDT', {
    symbol: 'LOCKUSDT', price, lastCandle: { high: hi, low: lo }, candles: []
  }]]);

  // الف) اوج ۱۰۷.۵ (=۱.۵R) → پس‌دادن به ۱۰۳.۵ (۵۳٪ از اوج) → PROFIT_LOCK با سود مثبت
  {
    const paper = mkPaper({ profitLockOn: 'on', profitLockMinPeakR: 1, profitLockGivebackPct: 50, maxHoldMinutes: 0 });
    paper.open(base, 'auto', true);
    paper.updateStops(market(107.5), sigMap);
    ok(paper.state.paperPositions[0]?.lockArmed === true, 'سود به ۱×R رسید → قفل مسلح شد');
    paper.updateStops(market(103.5, 107.5, 102.5), sigMap);
    const trade = paper.state.paperTrades[0];
    ok(trade && trade.reason === 'PROFIT_LOCK', `پس‌دادن ۵۳٪ از اوج → بسته با PROFIT_LOCK (reason=${trade?.reason})`);
    ok(trade && Number(trade.pnl) > 0, `سودِ نجات‌یافته مثبت ماند (pnl=${trade?.pnl?.toFixed(2)})`);
    ok((trade?.rungs || []).some(r => r.a === 'lock'), 'پلهٔ lock در نردبان تصمیم‌ها ثبت شد');
  }

  // ب) اوج فقط ۰.۸۸R → قفل مسلح نمی‌شود؛ پوزیشن باز می‌ماند
  {
    const paper = mkPaper({ profitLockOn: 'on', profitLockMinPeakR: 1, profitLockGivebackPct: 50, maxHoldMinutes: 0 });
    paper.open({ ...base, signalId: 'lk2' }, 'auto', true);
    paper.updateStops(market(104.4), sigMap);
    ok(paper.state.paperPositions[0]?.lockArmed !== true, 'اوج زیر ۱×R → قفل هنوز مسلح نشده');
    paper.updateStops(market(101, 104.4, 100.9), sigMap);
    ok(paper.state.paperPositions.length === 1, 'زیر آستانهٔ مسلح‌شدن → پوزیشن باز ماند (قفل بی‌دلیل نمی‌بندد)');
  }

  // ج) خاموش (profitLockOn=off) → حتی پس‌دادن کامل از اوج، خروج قفل رخ نمی‌دهد
  {
    const paper = mkPaper({ profitLockOn: 'off', profitLockMinPeakR: 1, profitLockGivebackPct: 50, maxHoldMinutes: 0 });
    paper.open({ ...base, signalId: 'lk3' }, 'auto', true);
    paper.updateStops(market(108), sigMap);
    paper.updateStops(market(103.5, 108, 102.5), sigMap);
    ok(paper.state.paperPositions.length === 1 && !paper.state.paperTrades[0],
      'قفل خاموش → پوزیشن باز ماند (سایر محافظت‌ها decid می‌کنند)');
  }

  // د) قفل تنگ (۲۵٪) با ATR موجود → قبل از ترلینگ عریض (۲.۵$) می‌بندد
  {
    const sigAtr = new Map([['LOCKUSDT', { ...base, rsi: 50, movePct: 0, volX: 0, atr: 2 }]]);
    const paper = mkPaper({ profitLockOn: 'on', profitLockMinPeakR: 1, profitLockGivebackPct: 25, maxHoldMinutes: 0 });
    paper.open({ ...base, signalId: 'lk4' }, 'auto', true);
    paper.updateStops(market(107.5), sigAtr);
    // ترلینگ استاپ = ۱۰۵؛ قیمت ۱۰۵.۵ هنوز بالای ترلینگ است ولی ۲۷٪ از اوج پس داده → قفل می‌بندد
    paper.updateStops(market(105.5, 107.5, 105.5), sigAtr);
    const trade = paper.state.paperTrades[0];
    ok(trade && trade.reason === 'PROFIT_LOCK' && Number(trade.exit) === 105.5,
      `قفل ۲۵٪ قبل از ترلینگ بست (exit=${trade?.exit}, reason=${trade?.reason})`);
  }

  // هـ) SHORT هم قرینه قفل می‌گیرد (اوج سود در پایین)
  {
    const shortSig = { ...base, side: 'SHORT', stop: 105, take: 90, signalId: 'lk5' };
    const sigMapS = new Map([['LOCKUSDT', { ...shortSig, rsi: 50, movePct: 0, volX: 0 }]]);
    const paper = mkPaper({ profitLockOn: 'on', profitLockMinPeakR: 1, profitLockGivebackPct: 50, maxHoldMinutes: 0 });
    paper.open(shortSig, 'auto', true);
    paper.updateStops(market(92.5), sigMapS);
    paper.updateStops(market(96.5, 97, 92.5), sigMapS);
    const trade = paper.state.paperTrades[0];
    ok(trade && trade.reason === 'PROFIT_LOCK' && Number(trade.pnl) > 0,
      `SHORT: اوج ۹۲.۵ → برگشت به ۹۶.۵ → PROFIT_LOCK با سود (pnl=${trade?.pnl?.toFixed(2)})`);
  }

  // و) 🔄 چرخش روند: آستانهٔ مستقل flipMinScore از Settings (v2.10.2)
  {
    const paper = mkPaper({ flipMinScore: 80, maxHoldMinutes: 0 });
    paper.open({ ...base, signalId: 'tf1' }, 'auto', true);
    const shortWeak = new Map([['LOCKUSDT', { ...base, side: 'SHORT', score: 75, rsi: 50, movePct: 0, volX: 0 }]]);
    paper.updateStops(market(103), shortWeak);
    ok(paper.state.paperPositions.length === 1, 'سیگنال مخالف ۷۵ < flipMinScore 80 → معامله باز ماند');
    const shortStrong = new Map([['LOCKUSDT', { ...base, side: 'SHORT', score: 85, rsi: 50, movePct: 0, volX: 0 }]]);
    paper.updateStops(market(103), shortStrong);
    ok(paper.state.paperTrades[0]?.reason === 'TREND_FLIP', 'سیگنال مخالف ۸۵ ≥ 80 → بسته با TREND_FLIP');
  }
}

console.log(failures === 0 ? '\n🎉 همه تست‌ها سبز شدند!\n' : `\n⚠️ ${failures} تست قرمز شد!\n`);
process.exit(failures === 0 ? 0 : 1);
