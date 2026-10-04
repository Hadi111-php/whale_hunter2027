/**
 * تست خودکار Pump/Dump Lab — فقط منطق خالص، بدون مرورگر و بدون دیتای فیک در LIVE.
 *   ۱) رادار: کشف پمپ/دامپ/تازه‌لیست، فیلترها، TTL، گرم‌سازی، حالت دقیق
 *   ۲) موتور Ignition: امتیازدهی، فیلتر RSI دوطرفه، استریک، پلن معامله
 *   ۳) بروکر: علت‌های رد، MaxHold، Breakeven/ترلینگ، ساعت قابل تزریق
 * اجرا:  npm test
 */
import { DEFAULT_SETTINGS } from '../src/js/core/config.js';
import { PumpRadar } from '../src/js/services/radar.js';
import { IgnitionStrategy } from '../src/js/services/ignition.js';
import { PaperBroker } from '../src/js/services/paper-broker.js';
import { SignalValidator } from '../src/js/services/signal-validator.js';
import { tfLabel, ignitionSummaryText } from '../src/js/core/utils.js';

let failures = 0;
const ok = (cond, msg) => {
  if (cond) console.log(`  ✅ ${msg}`);
  else { failures += 1; console.error(`  ❌ ${msg}`); }
};
const baseSettings = (over = {}) => ({ value: { ...DEFAULT_SETTINGS, ...over } });

console.log('\n۱) رادار — کشف، فیلترها و چرخه حیات');
{
  const MIN = 60_000;
  const memStorage = () => { const store = {}; return { read: (k, f) => (store[k] === undefined ? f : store[k]), write: (k, v) => { store[k] = v; } }; };
  const mkRadar = (over = {}, universe = null, nowFn = () => 0) => {
    let universeRows = universe;
    const settings = baseSettings(over);
    const radar = new PumpRadar(settings, { info: () => {} }, {
      now: nowFn,
      fetchJson: async () => (universeRows ? universeRows : Promise.reject(new Error('no source'))),
      storage: memStorage()
    });
    radar.__setUniverse = rows => { universeRows = rows; };
    return radar;
  };
  const row = (symbol, price, { turnover = 50e6, change24hPct = 0 } = {}) => ({
    symbol, lastPrice: String(price), quoteVolume: turnover, priceChangePercent: change24hPct
  });

  const clock = { t: 1_000_000_000_000 };
  const radar = mkRadar({}, [row('BTCUSDT', 100), row('MOVEUSDT', 0.01)], () => clock.t);
  let events = await radar.poll();
  ok(events.length === 0, 'اولین پول فقط seed — بدون رخداد کاذب');

  clock.t += 35 * MIN;
  radar.__setUniverse([
    row('BTCUSDT', 101),
    row('MOVEUSDT', 0.0178, { change24hPct: 78 }),
    row('LOWCAPUSDT', 2.4, { turnover: 1e6, change24hPct: 25 }),
    row('USDCUSDT', 1.3, { change24hPct: 30 }),
    row('BTC3LUSDT', 55, { change24hPct: 40 })
  ]);
  events = await radar.poll();
  const pump = events.filter(e => e.type === 'PUMP');
  ok(pump.length === 1 && pump[0].symbol === 'MOVEUSDT' && pump[0].changePct === 78, 'پامپ ۷۸٪ MOVE کشف شد (تقریب گرم‌سازی)');
  ok(radar.tradeableSymbols().includes('MOVEUSDT'), 'MOVE وارد لیست قابل‌ترید شد');
  ok(!radar.tradeableSymbols().some(s => ['LOWCAPUSDT', 'USDCUSDT', 'BTC3LUSDT'].includes(s)), 'کم‌نقدینگی/استیبل/اهرمی فیلتر شدند');

  clock.t += 26 * MIN;
  radar.__setUniverse([row('BTCUSDT', 101), row('MOVEUSDT', 0.0178, { change24hPct: 78 }), row('SOLUSDT', 88, { change24hPct: -12 })]);
  events = await radar.poll();
  ok(radar.active.get('MOVEUSDT').basis === 'window' && Math.abs(radar.active.get('MOVEUSDT').changePct - 78) < 0.01, 'پس از گرم‌سازی، محاسبه دقیق پنجره: 78.00٪');
  ok(events.some(e => e.type === 'DUMP' && e.symbol === 'SOLUSDT'), 'دامپ SOL کشف شد');

  clock.t += 130 * MIN;
  radar.__setUniverse([row('BTCUSDT', 101)]);
  await radar.poll();
  ok(radar.active.size === 0, 'TTL انقضا → آزاد شدن کشف‌شده‌ها');

  clock.t += 5 * MIN;
  radar.__setUniverse([row('BTCUSDT', 101), row('BRANDNEWUSDT', 3.3, { turnover: 30e6, change24hPct: 4 })]);
  events = await radar.poll();
  const newEv = events.filter(e => e.type === 'NEW');
  ok(newEv.length === 1 && newEv[0].symbol === 'BRANDNEWUSDT', 'تازه‌لیست → رخداد NEW');
  ok(radar.active.get('BRANDNEWUSDT').side === 'WATCH', 'تازه‌لیست فقط WATCH (بدون ورود)');
  ok(!radar.tradeableSymbols().includes('BRANDNEWUSDT'), 'WATCH در لیست قابل‌ترید نیست');
}

console.log('\n۲) موتور Ignition — امتیاز، فیلترها و پلن معامله');
{
  const MIN = 60_000;
  const now = Date.now();
  const mkSeries = (dir, pattern) => {
    // pattern: هر سومین کندل اصلاحی — RSI را داخل پنجره نگه می‌دارد (واقعی‌تر از رشد خالص)
    const candles = [];
    let p = dir === 'up' ? 100 : 200;
    for (let i = 42; i > 0; i -= 1) {
      const isPullback = i % 3 === 0;
      const chg = dir === 'up' ? (isPullback ? -0.005 : 0.004) : (isPullback ? 0.005 : -0.004);
      const close = p * (1 + chg);
      candles.push({
        ts: now - i * MIN,
        open: p,
        high: Math.max(p, close) * 1.001,
        low: Math.min(p, close) * 0.999,
        close,
        volume: i <= 3 ? 3000 : 600 // انفجار حجم در کندل‌های آخر
      });
      p = close;
    }
    return candles;
  };

  const strat = new IgnitionStrategy(baseSettings({}));
  const sig = strat.analyze({ symbol: 'MOVEUSDT', side: 'LONG', changePct: 24, basis: 'window' }, { candles: mkSeries('up'), source: 'TEST' }, now);
  ok(sig.side === 'LONG' && sig.score >= 70, `سیگنال LONG با امتیاز ${sig.score} ساخته شد`);
  ok(sig.stop < sig.entry && sig.take > sig.entry, `پلن معامله سالم: SL=${sig.stop.toFixed(2)} < Entry=${sig.entry.toFixed(2)} < TP=${sig.take.toFixed(2)}`);
  ok(sig.why.includes('رادار') && sig.why.includes('حجم'), `دلایل شفاف: «${sig.why}»`);

  // رشد خالص بدون اصلاح → RSI=100 → دمِ انفجاری → ورود ممنوع
  const exhaled = [];
  let p = 100;
  for (let i = 42; i > 0; i -= 1) {
    exhaled.push({ ts: now - i * MIN, open: p, high: p * 1.005, low: p * 0.999, close: p * 1.004, volume: 4000 });
    p *= 1.004;
  }
  const sig2 = strat.analyze({ symbol: 'XUSDT', side: 'LONG', changePct: 30, basis: 'window' }, { candles: exhaled, source: 'TEST' }, now);
  ok(sig2.side === 'WAIT' && sig2.why.includes('RSI'), `فیلتر RSI دم انفجاری: RSI=${sig2.rsi === undefined ? '--' : sig2.rsi.toFixed(0)} → ورود رد شد`);

  // کشف دامپ → مسیر SHORT با RSI آینه‌ای داخل پنجره
  const sig3 = strat.analyze({ symbol: 'DUMPUSDT', side: 'SHORT', changePct: -18, basis: 'window' }, { candles: mkSeries('down'), source: 'TEST' }, now);
  ok(sig3.side === 'SHORT', `کشف دامپ → SHORT با امتیاز ${sig3.score}`);
  ok(sig3.stop > sig3.entry && sig3.take < sig3.entry, 'پلن SHORT سالم (SL بالای ورود، TP پایین ورود)');

  // دیتای ناکافی → WAIT بدون خطا
  const sig4 = strat.analyze({ symbol: 'YUSDT', side: 'LONG', changePct: 20 }, { candles: mkSeries('up').slice(0, 5), source: 'TEST' }, now);
  ok(sig4.side === 'WAIT' && sig4.why.includes('کافی نیست'), 'دیتای ناکافی → WAIT شفاف');
}

console.log('\n۳) بروکر Paper — گیت‌ها، MaxHold و خروج سود');
{
  const clock = { t: 1_700_000_000_000 };
  const settings = baseSettings({ cooldownSec: 60, maxOpenPositions: 2, ignitionMaxHoldMin: 45, dailyLossLimitPct: 4 });
  const paper = new PaperBroker(settings, { info: () => {} }, { now: () => clock.t });
  const sig = { symbol: 'MOVEUSDT', side: 'LONG', score: 82, entry: 100, qty: 2, notional: 200, stop: 97, take: 105, signalId: 's1', radarChangePct: 22, source: 'TEST' };

  ok(paper.evaluate(sig).ok === true, 'حالت پایه → مجاز');
  ok(paper.open(sig, 'auto') === true, 'ورود خودکار ثبت شد');
  ok(paper.evaluate(sig).ok === false && paper.evaluate(sig).reason.includes('پوزیشن باز'), 'جلوی ورود تکراری گرفته شد');

  // MaxHold: بعد از ۴۶ دقیقه باید با دلیل MAX_HOLD_EXIT بسته شود
  clock.t += 46 * 60_000;
  paper.updateStops(new Map([['MOVEUSDT', { symbol: 'MOVEUSDT', price: 100.5, lastCandle: { high: 100.6, low: 100.2 }, atr: 0.8 }]]));
  const trade = paper.state.paperTrades[0];
  ok(trade && trade.reason === 'MAX_HOLD_EXIT', `خروج قاطع MaxHold: ${trade?.reason}`);
  ok(Number.isFinite(trade.pnl) && trade.fees > 0, `کارمزد دوطرفه اعمال شد (fees=${trade.fees.toFixed(3)})`);

  // Cooldown از لحظه ورود محاسبه می‌شود؛ ۴۶ دقیقه بعد از خروج، مدت‌ها گذشته است
  const again = paper.evaluate({ ...sig, signalId: 's2' });
  ok(again.ok === true, 'بعد از خروج و گذشت cooldown، ورود مجدد مجاز است');

  // حد ضرر روزانه
  paper.state.dayStartEquity = 1000;
  paper.state.paperEquity = 950;
  const lossBlocked = paper.evaluate({ ...sig, signalId: 's3' });
  ok(lossBlocked.ok === false && lossBlocked.reason.includes('سقف ضرر روزانه'), 'قفل ضرر روزانه فعال است');
}


console.log('\n۸) 🖥 رندر UI با DOM فیک — هیچ استثنایی جدول‌ها را نمی‌کشد (v1.1)');
{
  class FakeEl {
    constructor(tag = 'div') {
      this.tagName = tag.toUpperCase(); this.children = []; this.style = {}; this.dataset = {};
      this._html = ''; this._text = ''; this.className = ''; this.value = ''; this.parentElement = null; this.listeners = {};
    }
    get innerHTML() { return this._html; }
    set innerHTML(v) { this._html = String(v); }
    set textContent(v) { this._text = String(v); }
    get textContent() { return this._text; }
    appendChild(child) { this.children.push(child); child.parentElement = this; return child; }
    insertBefore(el) { this.children.push(el); el.parentElement = this; return el; }
    addEventListener() {}
    closest() { return this._table ||= new FakeEl('table'); }
    querySelector() { return this._thead ||= new FakeEl('thead'); }
    querySelectorAll() { return []; }
  }
  const byId = new Map();
  globalThis.document = {
    getElementById: id => { if (!byId.has(id)) byId.set(id, new FakeEl()); return byId.get(id); },
    querySelector: sel => sel.startsWith('#') ? globalThis.document.getElementById(sel.slice(1)) : new FakeEl(),
    querySelectorAll: () => [],
    createElement: tag => new FakeEl(tag),
    head: new FakeEl('head'),
    body: new FakeEl('body')
  };
  const { DashboardView } = await import('../src/js/ui/view.js');

  const positions = Array.from({ length: 8 }, (_, i) => ({ id: 'p' + i, symbol: 'COIN' + i + 'USDT', side: i % 2 ? 'SHORT' : 'LONG', entry: 100 + i, stop: 95, take: 110, qty: 1, notional: 100, openFee: 0.055, openedAt: Date.now() - 600000 }));
  const app = {
    paper: {
      state: { paperPositions: positions, paperTrades: [{ time: Date.now() - 6e6, symbol: 'COIN0USDT', side: 'LONG', entry: 100, exit: 103, pnl: 2.5, fees: 0.11, reason: 'TP', durationSec: 3600, radarChangePct: 9.1 }], paperEquity: 1000, feesPaid: 0.4 },
      netPnl: () => 1.5
    },
    marketData: new Map(positions.map(p => [p.symbol, { symbol: p.symbol, price: p.entry * 1.01 }])),
    signals: new Map([['COIN1USDT', { side: 'WAIT', score: 50, why: 'کم' }]]),
    blockReasons: new Map([['COIN1USDT', 'سقف پوزیشن پر است']]),
    settings: { value: { audioAlerts: 'true' } },
    radar: {
      snapshot: () => ({
        enabled: true, source: 'BINANCE', lastPollAt: Date.now(), universe: 412, warmupRemainMin: 0, error: '',
        movers: [{ symbol: 'AAAUSDT', changePct: 12.3, basis: 'window', turnover24h: 5e6, isNew: false }],
        active: Array.from({ length: 8 }, (_, i) => ({ symbol: 'COIN' + i + 'USDT', side: i % 3 === 0 ? 'WATCH' : (i % 2 ? 'SHORT' : 'LONG'), changePct: 9 + i, turnover24h: 1e6, since: Date.now() - 6e5 })),
        events: [{ t: Date.now(), type: 'PUMP', symbol: 'AAAUSDT', changePct: 12.3, turnover24h: 5e6 }]
      })
    },
    logger: { info: () => {} }
  };

  let threw = null;
  try { new DashboardView(app).renderAll(); } catch (e) { threw = e; }
  ok(!threw, `renderAll بدون استثنا ${threw ? '(' + threw.message + ')' : ''}`);
  const g = id => byId.get(id)?.innerHTML || '';
  ok(g('moversRows').includes('AAAUSDT'), 'جدول برترین حرکت‌ها پر شد');
  ok(g('activeRows').includes('COIN0USDT') && g('activeRows').includes('COIN7USDT'), 'هر ۸ کشف‌شده در جدول لیست شدند');
  ok(g('eventsRows').includes('PUMP'), 'رویداد رادار در جدول رویدادها لیست شد');
  ok(g('positionsRows').includes('COIN0USDT'), 'پوزیشن‌های باز در جدول لیست شدند');
  ok(g('tradesRows').includes('COIN0USDT'), 'تاریخچهٔ معاملات در دیتاگرید لیست شد');
  ok(!/<td>[^<]*<td>/.test(g('activeRows')), 'HTML سالم است (td تو در تو ندارد — باگ رندر فعال رفع شد)');

  // مقاومت: اگر یک بخش بشکند، بقیه همچنان رندر می‌شوند
  byId.get('equityCard').textContent = () => { throw new Error('boom'); };
  let threw2 = null;
  try { new DashboardView(app).renderAll(); } catch (e) { threw2 = e; }
  ok(!threw2 && g('activeRows').length > 0, 'خطای یک بخش، رندر بقیه را نمی‌کشد (ضدگلوله)');
}


console.log('\n۹) 🐋 اعتبارسنج رادار — هر رویداد با واقعیت قضاوت می‌شود (v1.2)');
{
  const sv = new SignalValidator({ delayMs: 60000, thresholdPct: 1.5 });
  const t0 = Date.now();
  // PUMP با قیمت مرجع 100 → بعد از ۱۰ دقیقه قیمت 103 → CORRECT
  sv.track('ev:AAAUSDT:1000', { symbol: 'AAAUSDT', direction: 'LONG', refPrice: 100, meta: { changePct: 12 } });
  sv.track('ev:BBBUSDT:1000', { symbol: 'BBBUSDT', direction: 'SHORT', refPrice: 50, meta: { changePct: -11 } });
  ok(sv.pending(t0 + 61000).length === 2, 'دو رویداد سررسیدشده در صف قضاوت');
  sv.settle('ev:AAAUSDT:1000', 103, t0 + 61000);
  sv.settle('ev:BBBUSDT:1000', 51, t0 + 61000);
  const st = sv.stats();
  ok(st.correct === 1 && st.incorrect === 1, 'PUMP درست / DUMP غلط قضاوت شد');
  ok(st.accuracyPct === 50, `درصد دقت رادار محاسبه شد (${st.accuracyPct}٪)`);
  ok(sv.get('ev:AAAUSDT:1000')?.status === 'CORRECT' && sv.get('ev:AAAUSDT:1000')?.movePct === 3, 'رکورد برای ستون «نتیجه» جدول رویدادها قابل خواندن است');
  ok(sv.settle('ev:AAAUSDT:1000', 200, t0) === null, 'رکورد قضاوت‌شده دوباره قضاوت نمی‌شود');

  // ماندگاری — ری‌استارت اپ، دقت رادار را صفر نمی‌کند
  {
    const mem = {};
    globalThis.localStorage = { getItem: k => (k in mem ? mem[k] : null), setItem: (k, v) => { mem[k] = String(v); } };
    const svA = new SignalValidator({ delayMs: 60000, persistKey: 'test_sv_persist_pump' });
    svA.track('ev:CCCUSDT:2000', { symbol: 'CCCUSDT', direction: 'LONG', refPrice: 100 });
    const svB = new SignalValidator({ delayMs: 60000, persistKey: 'test_sv_persist_pump' });
    ok(svB.get('ev:CCCUSDT:2000')?.status === 'PENDING', 'ری‌استارت → رکورد رویداد از localStorage برگشت');
    delete globalThis.localStorage;
  }
}

console.log('\n۱۰) 🔍 شفافیت رادار — تایم‌فریم کار + خلاصهٔ Ignition (v1.3)');
{
  ok(tfLabel('1') === '1m' && tfLabel('15') === '15m' && tfLabel('60') === '1h' && tfLabel('D') === '1D', 'برچسب تایم‌فریم‌ها درست است (1m/15m/1h/1D)');
  ok(tfLabel(5) === '5m', 'ورودی عددی هم کار می‌کند');
  const empty = ignitionSummaryText({});
  ok(empty.includes('0 نماد در موتور') && empty.includes('بدون سیگنال') && !empty.includes('کندل‌ناموفق'), 'خلاصهٔ خالی: بدون سیگنال و بدون خطای کندل');
  const withFail = ignitionSummaryText({ targets: 8, klineFails: 3, blocked: 5, live: 0, positions: 0 });
  ok(withFail.includes('8 نماد در موتور') && withFail.includes('3 کندل‌ناموفق ⚠️') && withFail.includes('5 رد‌شده'), `شکست کندل در خلاصه دیده می‌شود: «${withFail}»`);
  const withSignal = ignitionSummaryText({ targets: 4, klineFails: 0, blocked: 2, live: 2, positions: 1 });
  ok(withSignal.includes('2 سیگنال فعال ✅') && withSignal.includes('1 پوزیشن باز'), `سیگنال فعال در خلاصه دیده می‌شود: «${withSignal}»`);
}

console.log(failures === 0 ? '\n🎉 همه تست‌های Pump/Dump Lab سبز شدند!\n' : `\n⚠️ ${failures} تست قرمز شد!\n`);
process.exit(failures === 0 ? 0 : 1);
