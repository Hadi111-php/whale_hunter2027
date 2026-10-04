#!/usr/bin/env node
/**
 * 🔬 ممیزی مرحله‌ای فرآیند (Stage Audit) — «دقیقاً کجای فرآیند سود به ضرر برمی‌گردد؟»
 * ---------------------------------------------------------------------------
 * فلسفه (خواستهٔ داداش هادی): خطا همیشه کدنویسی نیست؛ خودِ فرآیند است. پس سیستم
 * را پله‌پله می‌سازیم و در هر پله فقط «یک لایهٔ خروج» اضافه می‌کنیم. پله‌ای که
 * PF از بالای ۱ به زیر ۱ سقوط می‌کند = همان قسمتی که باید به عقب برگشت و کالبدشکافی شد.
 *
 * چرا اعتبار دارد؟ چون همان MomentumScalpStrategy و همان PaperBroker زنده اجرا
 * می‌شوند (فقط با override تنظیمات + فیلتر دلخواه روی دلیل بستن) — هیچ کپی موتور نیست.
 *
 * نردبان:
 *   R0  لبهٔ خام ورود — بدون SL/TP/ترلینگ/MaxHold؛ خروج فقط با سیگنال مخالف (TREND_FLIP)
 *   R0f همان R0 بدون کارمزد → سنجش «هزینهٔ فرآیند» (کارمزد چند درصد لبه را می‌خورد)
 *   R1  R0 + استاپ سخت ATR
 *   R2  R1 + بریک‌ایون فوری (رفتار قدیم — محل نشت: برنده‌ها تقریباً صفر بسته می‌شدند)
 *   R3  R1 + بریک‌ایون بالغ ×1ATR (فیکس v2.5: سود اول نفس می‌کشد، بعد محافظت می‌شود)
 *   R4  R3 + ترلینگ ATR (1.25×)
 *   R5  R4 + خروج برگشتی (RSI/EMA Reversal)
 *   R6  R5 + محو مومنتوم (fade=2)
 *   R7  سیستم کامل + MaxHold
 *   R8  پیش‌فرض معادل بک‌تست (کنترل sanity — باید ≈ R7 باشد)
 *
 * استفاده:
 *   node tools/stage-audit.mjs --data data/BTCUSDT-6h.jsonl
 *   node tools/stage-audit.mjs --data data/BTCUSDT-1h.jsonl
 */
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { DEFAULT_SETTINGS } from '../src/js/core/config.js';
import { MomentumScalpStrategy } from '../src/js/services/strategy.js';
import { PaperBroker } from '../src/js/services/paper-broker.js';
import { PerformanceReport, ladderRollup, LAYER_NAMES } from '../src/js/services/performance-report.js';

const args = process.argv.slice(2);
const arg = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};
const DATA = arg('data', '');
const LIVE = arg('live', '');

async function loadCandles(file) {
  const raw = await readFile(file, 'utf-8');
  const candles = [];
  for (const line of raw.split('\n')) {
    const l = line.trim();
    if (!l) continue;
    try {
      const o = JSON.parse(l);
      const c = o && typeof o === 'object' && 'open' in o
        ? o
        : Array.isArray(o) && o.length >= 6
          ? { ts: Number(o[0]) * (String(o[0]).length === 10 ? 1000 : 1), open: Number(o[1]), high: Number(o[2]), low: Number(o[3]), close: Number(o[4]), volume: Number(o[5]) }
          : null;
      if (c && [c.ts, c.open, c.high, c.low, c.close, c.volume].every(Number.isFinite)) candles.push(c);
    } catch { /* خط ناقص رد */ }
  }
  return candles.sort((a, b) => a.ts - b.ts);
}

const WARMUP = 60;
const LIVE_WINDOW = 200;
const SYMBOL = 'AUDIT';

/**
 * اجرای یک پلهٔ نردبان روی دادهٔ واقعی با همان ماژول‌های زنده.
 * blockedReasons = دلایل بستنی که در این پله «نباید» رخ دهند (مثلاً SL در R0).
 */
function runStage(candles, overrides, blockedReasons = new Set()) {
  const tfMs = candles.length > 1 ? Math.max(60_000, candles[1].ts - candles[0].ts) : 3_600_000;
  const settings = {
    value: {
      ...DEFAULT_SETTINGS,
      timeframe: String(DEFAULT_SETTINGS.timeframe),
      riskProfile: 'backtest',
      customFormula: '',
      ...overrides
    }
  };
  let simNow = candles[0].ts;
  const strategy = new MomentumScalpStrategy(settings);
  const paper = new PaperBroker(settings, { info: () => {} }, { now: () => simNow });
  const report = new PerformanceReport();

  // فیلتر پله: بعضی دلایل بستن در این پله مجاز نیستند (position باز می‌ماند)
  const origClose = paper.close.bind(paper);
  const exc = new Map();     // positionId → { mfePct, maePct } — بیشترین حرکت موافق/مخالف در طول نگهداری
  const extras = [];         // دادهٔ اضافهٔ هر معامله به ترتیب بسته‌شدن
  paper.close = (position, mark, reason = 'manual') => {
    if (blockedReasons.has(reason)) return false;
    const e = exc.get(position.id) || { mfePct: 0, maePct: 0 };
    const ok = origClose(position, mark, reason);
    if (ok) extras.push({ mfePct: Number(e.mfePct.toFixed(3)), maePct: Number(e.maePct.toFixed(3)) });
    return ok;
  };

  const marketMap = new Map();
  const signalsMap = new Map();
  for (let i = WARMUP; i < candles.length; i += 1) {
    const candle = candles[i];
    simNow = candle.ts + tfMs; // «الان» = لحظهٔ بسته‌شدن این کندل
    const history = candles.slice(Math.max(0, i + 1 - LIVE_WINDOW), i + 1);
    const market = {
      symbol: SYMBOL,
      price: candle.close,
      candles: history,
      microCandles: { candles: history },
      lastCandle: candle,
      receivedAt: simNow,
      tfMs,
      source: 'BACKTEST'
    };
    const signal = strategy.analyze(market);
    signalsMap.set(SYMBOL, signal);
    marketMap.set(SYMBOL, { symbol: SYMBOL, price: candle.close, lastCandle: candle, atr: signal.atr });

    // رهگیری MFE/MAE پیش از مدیریت — شامل کندلی که همین الان بسته می‌شود
    for (const p of paper.state.paperPositions) {
      const e = exc.get(p.id) || { mfePct: 0, maePct: 0 };
      const hi = (Number(candle.high) - p.entry) / p.entry * 100;
      const lo = (Number(candle.low) - p.entry) / p.entry * 100;
      const fav = p.side === 'LONG' ? hi : -lo;
      const adv = p.side === 'LONG' ? lo : -hi;
      e.mfePct = Math.max(e.mfePct, fav);
      e.maePct = Math.min(e.maePct, adv);
      exc.set(p.id, e);
    }

    paper.updateStops(marketMap, signalsMap);
    if (signal.side !== 'WAIT') paper.open(signal, 'auto');
  }
  for (const position of [...paper.state.paperPositions]) {
    paper.close(position, candles.at(-1).close, 'END_OF_DATA');
  }

  const summary = report.summarize(paper.state, settings.value.paperInitialEquity, 'backtest');
  const trades = [...paper.state.paperTrades].reverse(); // ترتیب زمانی
  trades.forEach((t, i) => { if (extras[i]) Object.assign(t, extras[i]); });
  return { summary, trades };
}

// ---------- پله‌های نردبان ----------
// خاموش‌کننده‌های تمیزِ هر زیرلایه (بدون دست‌زدن به کد زنده):
const NO_TRAIL = { trailAtrMult: 99999 };                                                            // ترلینگ هرگز استاپ را جابه‌جا نمی‌کند
const NO_REVERSAL = { reversalRsiHigh: 101, reversalRsiLow: -1, reversalVolX: 99999, reversalMovePct: 99999 }; // شرط‌های برگشت هرگز برقرار نمی‌شوند
const NO_FLOAT_EXTRAS = { ...NO_TRAIL, fadeCandles: 0, ...NO_REVERSAL };

function ladderFor(tfMs) {
  // معادلِ rescale بک‌تست: پیش‌فرض LIVE (۱۲۰ دقیقه) به تعداد کندل دیتا مقیاس می‌شود
  const defaultHoldBars = Math.max(1, Math.round(Number(DEFAULT_SETTINGS.maxHoldMinutes) * 3_600_000 / tfMs));
  const maxHoldMin = defaultHoldBars * (tfMs / 60_000);
  return [
    { id: 'R0', label: 'لبهٔ خام ورود (خروج فقط با سیگنال مخالف)', ov: { profitMode: 'fixed', takeProfitR: 999, maxHoldMinutes: 0 }, block: ['SL_HARD_STOP'] },
    { id: 'R0f', label: 'R0 بدون کارمزد (سنجش هزینهٔ فرآیند)', ov: { profitMode: 'fixed', takeProfitR: 999, maxHoldMinutes: 0, feeOpenPct: 0, feeClosePct: 0 }, block: ['SL_HARD_STOP'] },
    { id: 'R1', label: 'R0 + استاپ سخت ATR', ov: { profitMode: 'fixed', takeProfitR: 999, maxHoldMinutes: 0 }, block: [] },
    { id: 'R2', label: 'R1 + بریک‌ایون فوری (رفتار قدیم ← نشت)', ov: { profitMode: 'float', maxHoldMinutes: 0, ...NO_FLOAT_EXTRAS, breakevenMinAtr: 0 }, block: [] },
    { id: 'R3', label: 'R1 + بریک‌ایون بالغ ×1ATR (فیکس v2.5)', ov: { profitMode: 'float', maxHoldMinutes: 0, ...NO_FLOAT_EXTRAS, breakevenMinAtr: 1 }, block: [] },
    { id: 'R4', label: 'R3 + ترلینگ ATR×1.25', ov: { profitMode: 'float', maxHoldMinutes: 0, fadeCandles: 0, ...NO_REVERSAL, breakevenMinAtr: 1 }, block: [] },
    { id: 'R5', label: 'R4 + خروج برگشتی RSI/EMA', ov: { profitMode: 'float', maxHoldMinutes: 0, fadeCandles: 0, breakevenMinAtr: 1 }, block: [] },
    { id: 'R6', label: 'R5 + محو مومنتوم (fade=2)', ov: { profitMode: 'float', maxHoldMinutes: 0, breakevenMinAtr: 1 }, block: [] },
    { id: 'R7', label: `سیستم کامل + MaxHold (${defaultHoldBars} کندل)`, ov: { profitMode: 'float', maxHoldMinutes: maxHoldMin, breakevenMinAtr: 1 }, block: [] },
    { id: 'R8', label: 'پیش‌فرض معادل بک‌تست (sanity ≈ R7)', ov: { profitMode: 'float', maxHoldMinutes: maxHoldMin }, block: [] }
  ];
}

// ---------- کالبدشکافی معاملات یک پله ----------
function forensics(trades) {
  const byReason = {};
  for (const t of trades) {
    const k = t.reason || 'UNKNOWN';
    if (!byReason[k]) byReason[k] = { count: 0, net: 0, wins: 0, losses: 0, avgPnl: 0 };
    byReason[k].count += 1;
    byReason[k].net += t.pnl;
    if (t.pnl > 0) byReason[k].wins += 1; else if (t.pnl < 0) byReason[k].losses += 1;
  }
  for (const k of Object.keys(byReason)) byReason[k].avgPnl = byReason[k].net / byReason[k].count;

  const winners = trades.filter(t => t.pnl > 0);
  const losers = trades.filter(t => t.pnl <= 0);
  const peakPos = trades.filter(t => (t.peakPnl || 0) > 0.5);          // معاملاتی که سودِ قابل‌توجهی «داشتند»
  const sumPeak = peakPos.reduce((a, t) => a + t.peakPnl, 0);          // سقف قابل‌برداشت (با کارمزد)
  const sumNetOfPeak = peakPos.reduce((a, t) => a + t.pnl, 0);         // آنچه واقعاً برداشت شد
  const gaveBackToLoss = losers.filter(t => (t.peakPnl || 0) > 0.5);   // برنده بود → ضرر شد (پس‌دادن کامل)
  const fees = trades.reduce((a, t) => a + (t.fees || 0), 0);
  const grossWin = winners.reduce((a, t) => a + t.pnl, 0);

  const givebacks = peakPos.map(t => t.givebackPct || 0).sort((a, b) => a - b);
  const median = arr => (arr.length ? arr[Math.floor(arr.length / 2)] : 0);

  // خوشهٔ زمانی: سود/ضرر در کدام ماه‌ها جمع شد؟ («کِی یکدفعه ضررده شد؟»)
  const monthly = {};
  for (const t of trades) {
    const k = new Date(t.time).toISOString().slice(0, 7);
    if (!monthly[k]) monthly[k] = { trades: 0, net: 0 };
    monthly[k].trades += 1;
    monthly[k].net += t.pnl;
  }

  return {
    byReason,
    counts: { total: trades.length, winners: winners.length, losers: losers.length, peakPositive: peakPos.length, gaveBackToLoss: gaveBackToLoss.length },
    money: { fees, grossWin, sumPeak, sumNetOfPeak, capturePct: sumPeak > 0 ? (sumNetOfPeak / sumPeak * 100) : null },
    giveback: { mean: peakPos.length ? peakPos.reduce((a, t) => a + (t.givebackPct || 0), 0) / peakPos.length : 0, median: median(givebacks) },
    monthly
  };
}

const fmt = (v, d = 2) => (Number.isFinite(v) ? v.toFixed(d) : '--');
const pf = r => (Number.isFinite(r.profitFactor) ? r.profitFactor.toFixed(2) : ' -- ');

async function main() {
  // 📡 حالت ممیزی زنده: خروجی JSON واقعی سیستم (گوشی/دسکتاپ) را کالبدشکافی می‌کند —
  //   node tools/stage-audit.mjs --live ~/Downloads/trading_export_hadi_123.json
  if (LIVE) {
    const j = JSON.parse(await readFile(LIVE, 'utf-8'));
    const tradesRaw = j.tradesHistory || j.paperTrades || (Array.isArray(j) ? j : null);
    if (!Array.isArray(tradesRaw) || !tradesRaw.length) {
      console.error('❌ در فایل، آرایهٔ معاملات (tradesHistory/paperTrades) پیدا نشد.');
      process.exit(1);
    }
    const trades = [...tradesRaw].reverse(); // ترتیب زمانی
    const net = trades.reduce((a, t) => a + Number(t.pnl || 0), 0);
    const wins = trades.filter(t => Number(t.pnl) > 0).length;
    const withRungs = trades.filter(t => Array.isArray(t.rungs) && t.rungs.length).length;
    const withLadder = trades.filter(t => t.ladder).length;
    console.log(`📡 ممیزی زنده — ${LIVE}`);
    console.log(`   ${trades.length} معاملهٔ واقعی | ${new Date(trades[0].time).toISOString().slice(0, 10)} → ${new Date(trades.at(-1).time).toISOString().slice(0, 10)}`);
    console.log(`   Win-rate: ${(wins / trades.length * 100).toFixed(1)}% | Net: ${net.toFixed(2)} | رکورد نردبان کامل: ${withRungs} | خلاصهٔ ladder: ${withLadder}\n`);

    const roll = ladderRollup(trades);
    console.log('━━━ نردبان لایه‌های خروج (از وقایع واقعی) ━━━');
    for (const [name, st] of Object.entries(roll.byLayer).sort((a, b) => a[1].net - b[1].net)) {
      console.log(`   ${name.padEnd(20)} تعداد ${String(st.count).padStart(3)} | برد ${String(st.wins).padStart(3)} | جمع Net ${st.net.toFixed(2).padStart(9)}`);
    }
    console.log(`\n   💰 کارمزد کل: ${roll.fees.toFixed(2)} | سود ناخالص برنده‌ها: ${roll.grossWin.toFixed(2)}`);
    console.log(`   🏔 سقف قابل‌برداشت: ${roll.capture.sumPeak.toFixed(2)} | برداشت‌شده: ${roll.capture.netOfPeakTrades.toFixed(2)} | ضریب برداشت: ${roll.capture.pct !== null ? roll.capture.pct + '%' : '--'}`);
    console.log(`   🎁 برنده→ضرر: ${roll.gaveBackToLoss}/${roll.capture.peakPositiveTrades}`);
    const nearBE = trades.filter(t => Number(t.pnl) > 0 && Number(t.pnl) < 0.5).length;
    console.log(`   🧾 خروج‌های تقریباً بریک‌ایون (۰ < سود < $0.5): ${nearBE}`);

    console.log('\n━━━ خوشهٔ زمانی — «کِی یکدفعه ضررده شد؟» ━━━');
    for (const [month, st] of Object.entries(roll.monthly)) {
      const bar = '█'.repeat(Math.min(30, Math.max(0, Math.round(Math.abs(st.net) / 10)))) + (st.net < 0 ? ' ◄ ضرر' : '');
      console.log(`   ${month} | ${String(st.count).padStart(2)} معامله | ${st.net.toFixed(2).padStart(9)} ${bar}`);
    }

    if (withRungs) {
      console.log('\n━━━ نمونهٔ نردبان آخرین معاملهٔ دارای رکورد کامل ━━━');
      const t = [...trades].reverse().find(x => Array.isArray(x.rungs) && x.rungs.length);
      console.log(`   ${t.symbol} ${t.side} | ${LAYER_NAMES[t.ladder?.exitLayer] || t.reason} | pnl=${t.pnl} | mfe=${t.ladder?.mfePct}% mae=${t.ladder?.maePct}%`);
      for (const r of t.rungs.slice(0, 12)) {
        console.log(`     ${new Date(r.t).toISOString().slice(11, 19)} ${String(r.a).padEnd(6)} mark=${r.m} stop=${r.st}${r.atr ? ' atr=' + r.atr : ''}${r.r ? ' → ' + r.r : ''}`);
      }
      if (t.rungs.length > 12) console.log(`     … (+${t.rungs.length - 12} پلهٔ دیگر)`);
    } else {
      console.log('\n⚠️ هیچ معامله‌ای رکورد کامل پله‌ها (rungs) ندارد — یا قدیمی‌تر از v2.6 هستند یا rungs واکشیده شده‌اند.');
    }
    console.log('\n⚠️ صداقت کامل: اینها وقایع واقعی سیستم شماست؛ حکم نهایی نیازمند تعداد معاملهٔ کافی (حداقل ~۳۰) است.');
    return;
  }
  if (!DATA) {
    console.error('استفاده: node tools/stage-audit.mjs --data data/BTCUSDT-6h.jsonl');
    console.error('       node tools/stage-audit.mjs --live trading_export_hadi_123.json');
    process.exit(1);
  }
  const candles = await loadCandles(DATA);
  if (candles.length < WARMUP + 100) {
    console.error('❌ داده کافی نیست (حداقل ~۱۶۰ کندل).');
    process.exit(1);
  }
  const tfMs = candles[1].ts - candles[0].ts;
  const tfName = tfMs >= 86_400_000 ? `${Math.round(tfMs / 86_400_000)}D` : `${Math.round(tfMs / 3_600_000)}h`;
  console.log(`🔬 ممیزی مرحله‌ای — ${candles.length} کندل واقعی ${tfName} | ${new Date(candles[0].ts).toISOString().slice(0, 10)} → ${new Date(candles.at(-1).ts).toISOString().slice(0, 10)}\n`);
  console.log('پله | توضیح                                        | معاملات  Win%    NetPnL     PF    | میانگین MFE   میانگین MAE');
  console.log('-'.repeat(130));

  const rows = [];
  const ladder = ladderFor(tfMs);
  // پروب تعاملی: یک پلهٔ اضافه با override دلخواه روی پایهٔ R6 —
  //   node tools/stage-audit.mjs --data ... --probe trailAtrMult=2.5
  //   node tools/stage-audit.mjs --data ... --probe trailAtrMult=3,fadeCandles=0
  const PROBE = arg('probe', '');
  if (PROBE) {
    const ov = {};
    for (const kv of PROBE.split(',')) {
      const [k, v] = kv.split('=');
      if (k && v !== undefined) ov[k.trim()] = Number.isFinite(Number(v)) ? Number(v) : v.trim();
    }
    ladder.push({
      id: 'P1',
      label: `پروب: ${PROBE}`,
      ov: { ...ladder.find(r => r.id === 'R7').ov, ...ov },
      block: []
    });
  }
  for (const stage of ladder) {
    const { summary, trades } = runStage(candles, stage.ov, new Set(stage.block));
    const avgMfe = trades.length ? trades.reduce((a, t) => a + (t.mfePct || 0), 0) / trades.length : 0;
    const avgMae = trades.length ? trades.reduce((a, t) => a + (t.maePct || 0), 0) / trades.length : 0;
    rows.push({ id: stage.id, label: stage.label, blocked: stage.block, summary, trades, forensics: forensics(trades) });
    console.log(
      `${stage.id.padEnd(4)}| ${stage.label.padEnd(46)}| ${String(summary.count).padStart(5)}  ${fmt(summary.winRate, 1).padStart(6)}% ${fmt(summary.netPnl, 2).padStart(9)} ${pf(summary).padStart(7)} | ${fmt(avgMfe, 2).padStart(6)}%     ${fmt(avgMae, 2).padStart(6)}%`
    );
  }

  // ---------- گزارش کالبدشکافی پلهٔ کامل (R6) ----------
  const full = rows.find(r => r.id === 'R7');
  const raw = rows.find(r => r.id === 'R0');
  console.log('\n━━━ کالبدشکافی سیستم کامل (R7) — سود/ضرر به تفکیک «دلیل خروج» ━━━');
  for (const [reason, st] of Object.entries(full.forensics.byReason).sort((a, b) => a[1].net - b[1].net)) {
    console.log(`   ${reason.padEnd(24)} تعداد ${String(st.count).padStart(3)} | برد/باخت ${st.wins}/${st.losses} | جمع Net ${fmt(st.net, 2).padStart(9)} | میانگین ${fmt(st.avgPnl, 2)}`);
  }
  const f = full.forensics;
  console.log(`\n   💰 کارمزد کل: ${fmt(f.money.fees)} | سودِ ناخالص برنده‌ها: ${fmt(f.money.grossWin)} | سهم کارمزد از سود ناخالص: ${f.money.grossWin > 0 ? fmt(f.money.fees / f.money.grossWin * 100, 1) : '--'}%`);
  console.log(`   🏔 سقف قابل‌برداشت (Σ اوج معاملات سودده): ${fmt(f.money.sumPeak)} | برداشت‌شده: ${fmt(f.money.sumNetOfPeak)} | ضریب برداشت: ${f.money.capturePct !== null ? fmt(f.money.capturePct, 1) + '%' : '--'}`);
  console.log(`   🎁 میانگین پس‌دادن از اوج: ${fmt(f.giveback.mean, 1)}% | میانه: ${fmt(f.giveback.median, 1)}% | معاملاتی که برنده بودند و به ضرر رسیدند: ${f.counts.gaveBackToLoss}/${f.counts.total}`);
  const nearBE = full.trades.filter(t => t.reason === 'PROFIT_TRAIL_REVERSED' && t.pnl > 0 && t.pnl < 0.5).length;
  const realTrail = full.trades.filter(t => t.reason === 'PROFIT_TRAIL_REVERSED' && t.pnl >= 0.5).length;
  console.log(`   🧾 خروج‌های «تقریباً بریک‌ایون» (۰ < سود < $0.5): ${nearBE} از ${full.trades.filter(t => t.reason === 'PROFIT_TRAIL_REVERSED').length} | ترلینگ واقعاً سود قفل کرد: ${realTrail}`);
  const r1 = rows.find(r => r.id === 'R1');
  const ceilR1 = r1.forensics.money.sumPeak;
  console.log(`   📈 سقف تئوری همین ورودها (Σ اوج R1): ${fmt(ceilR1)} → سیستم کامل فقط ${ceilR1 > 0 ? fmt(full.summary.netPnl / ceilR1 * 100, 1) : '--'}% را نقد کرد | R1 بدون موتور شناور: ${fmt(r1.summary.netPnl)}`);
  console.log(`   📌 R0 (نگهداری تا سیگنال مخالف): فقط ${raw.summary.count} معامله — بدون استاپ، پوزیشن ماه‌ها باز می‌ماند و کل ظرفیت را قفل می‌کند (MAE میانگین ${fmt(raw.trades[0]?.maePct ?? 0, 1)}%!)`);

  console.log('\n━━━ خوشهٔ زمانی ضرر (R7) — «کِی یکدفعه ضررده شد؟» ━━━');
  for (const [month, st] of Object.entries(full.forensics.monthly)) {
    const bar = '█'.repeat(Math.min(30, Math.max(0, Math.round(Math.abs(st.net) / 10)))) + (st.net < 0 ? ' ◄ ضرر' : '');
    console.log(`   ${month} | ${String(st.trades).padStart(2)} معامله | ${fmt(st.net, 2).padStart(9)} ${bar}`);
  }

  // ---------- ذخیرهٔ JSON برای بررسی دقیق مشترک ----------
  const outPath = path.resolve('results', `stage_audit_${Date.now()}.json`);
  await mkdir(path.dirname(outPath), { recursive: true });
  await writeFile(outPath, JSON.stringify({
    generatedAt: new Date().toISOString(),
    data: path.resolve(DATA),
    timeframe: tfName,
    candles: candles.length,
    period: { from: new Date(candles[0].ts).toISOString(), to: new Date(candles.at(-1).ts).toISOString() },
    ladder: rows.map(r => ({
      id: r.id, label: r.label, blockedReasons: r.blocked,
      summary: r.summary,
      forensics: r.forensics,
      trades: r.trades.map(t => ({
        time: new Date(t.time).toISOString(), side: t.side, entry: t.entry, exit: t.exit,
        pnl: t.pnl, peakPnl: t.peakPnl, givebackPct: t.givebackPct, fees: t.fees,
        reason: t.reason, score: t.score, mfePct: t.mfePct, maePct: t.maePct,
        durationBars: t.durationSec ? Math.round(t.durationSec / (tfMs / 1000)) : null
      }))
    }))
  }, null, 2), 'utf-8');
  console.log(`\n💾 خروجی کامل JSON: ${outPath}`);
  console.log('\n⚠️ صداقت کامل: این ممیزی روی یک نماد/یک بازه است؛ نتیجه‌اش «محل نشت» را نشان می‌دهد، نه تضمین آینده.');
}

main().catch(error => {
  console.error('STAGE AUDIT FAILED:', error);
  process.exit(1);
});
