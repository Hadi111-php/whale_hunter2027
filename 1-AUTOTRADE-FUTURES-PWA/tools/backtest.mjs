#!/usr/bin/env node
/**
 * موتور بک‌تست و بهینه‌سازی — بازپخش کندل‌های واقعی از طریق «همان ماژول‌های زنده».
 * ---------------------------------------------------------------------------
 * چرا این اعتبار دارد؟ چون همان MomentumScalpStrategy و همان PaperBroker که
 * در LIVE معامله می‌کنند، اینجا کندل‌به‌کندل اجرا می‌شوند (نه یک کپی جدا).
 *
 * روش (Walk-Forward ضد Overfitting):
 *   ۱) داده به دو بخش Train (۷۰٪ اول) و Test (۳۰٪ آخر) تقسیم می‌شود
 *   ۲) گرید پارامترها فقط روی Train جستجو می‌شود
 *   ۳) ۵ ترکیب برتر Train روی Test ارزیابی می‌شوند — افت عملکرد = نشانه Overfit
 *
 * استفاده:
 *   node tools/backtest.mjs --data data/BTCUSDT-1h.jsonl
 *   node tools/backtest.mjs --data data/BTCUSDT-1h.jsonl --grid full --split 70
 *   node tools/backtest.mjs --demo   ← فقط تست خط لوله با دیتای سینتتیکِ صریح (نتیجه‌اش معتبر نیست!)
 */
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { DEFAULT_SETTINGS } from '../src/js/core/config.js';
import { MomentumScalpStrategy } from '../src/js/services/strategy.js';
import { PaperBroker } from '../src/js/services/paper-broker.js';
import { PerformanceReport } from '../src/js/services/performance-report.js';

const args = process.argv.slice(2);
const arg = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};
const DATA = arg('data', '');
const GRID = arg('grid', 'fast');
const SPLIT = Number(arg('split', 70));
const PROFILE = arg('profile', 'backtest');

// ---------- بارگذاری کندل‌ها ----------
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
    } catch { /* خط ناقص را رد کن */ }
  }
  return candles.sort((a, b) => a.ts - b.ts);
}

// ---------- دیتای سینتتیک صریح — فقط تست خط لوله، نتیجه معتبر نیست ----------
function demoCandles(n = 2400) {
  const out = [];
  let price = 50000;
  let seed = 42;
  const rnd = () => {
    seed = (seed * 1103515245 + 12345) % 2147483648;
    return seed / 2147483648;
  };
  for (let i = 0; i < n; i += 1) {
    const wave = Math.sin(i / 85) * 0.0022 + Math.sin(i / 311) * 0.0035;
    const open = price;
    price = Math.max(1000, price * (1 + wave + (rnd() - 0.5) * 0.006));
    out.push({
      ts: 1_600_000_000_000 + i * 3_600_000,
      open,
      high: Math.max(open, price) * (1 + rnd() * 0.001),
      low: Math.min(open, price) * (1 - rnd() * 0.001),
      close: price,
      volume: 800 + rnd() * 700 + (Math.abs(wave) > 0.004 ? 2200 * rnd() : 0)
    });
  }
  return out;
}

// ---------- اجرای یک بازپخش کامل ----------
const WARMUP = 60;         // همان حداقل دیتایی که LIVE هم لازم دارد
const LIVE_WINDOW = 200;   // همان پنجره‌ای که MarketClient در LIVE می‌گیرد (limit=200)

function runOnce(candles, overrides, symbol = 'BACKTEST') {
  // فاصله واقعی کندل‌ها از خود دیتا استنتاج می‌شود (1h/4h/1d — هر چیزی)
  const tfMs = candles.length > 1 ? Math.max(60_000, candles[1].ts - candles[0].ts) : 3_600_000;
  // holdBars از گرید می‌آید؛ پیش‌فرض LIVE (۱۲۰ دقیقه = ۲ کندل ۱ساعته) به همان تعداد کندل مقیاس می‌شود
  const defaultHoldBars = Math.max(1, Math.round(Number(DEFAULT_SETTINGS.maxHoldMinutes) * 3_600_000 / tfMs));
  const holdBars = Number(overrides.holdBars) || defaultHoldBars;
  const settings = {
    value: {
      ...DEFAULT_SETTINGS,
      timeframe: String(DEFAULT_SETTINGS.timeframe),
      riskProfile: PROFILE,
      customFormula: '',
      maxHoldMinutes: holdBars * (tfMs / 60_000),
      ...overrides,
      holdBars: undefined,
      profitMode: overrides.profitMode || 'float',
      fadeCandles: overrides.fadeCandles === undefined ? undefined : Number(overrides.fadeCandles),
      microCandleTf: overrides.microCandleTf || DEFAULT_SETTINGS.microCandleTf
    }
  };
  let simNow = candles[0].ts;
  const strategy = new MomentumScalpStrategy(settings);
  const paper = new PaperBroker(settings, { info: () => {} }, { now: () => simNow });
  const report = new PerformanceReport();

  const marketMap = new Map();
  const signalsMap = new Map();
  for (let i = WARMUP; i < candles.length; i += 1) {
    const candle = candles[i];
    simNow = candle.ts + tfMs; // «الان» = لحظه بسته‌شدن این کندل
    const history = candles.slice(Math.max(0, i + 1 - LIVE_WINDOW), i + 1);
    const market = {
      symbol,
      price: candle.close,
      candles: history,
      microCandles: { candles: history }, // در بک‌تست، TF ریز همان TF دیتاست
      lastCandle: candle,
      receivedAt: simNow, // ⏱ گیت کهنگی کندل با ساعت شبیه‌سازی هم‌راستا می‌شود
      tfMs,
      source: 'BACKTEST'
    };
    const signal = strategy.analyze(market);
    signalsMap.set(symbol, signal);
    marketMap.set(symbol, { symbol, price: candle.close, lastCandle: candle, atr: signal.atr });
    paper.updateStops(marketMap, signalsMap);
    if (signal.side !== 'WAIT') paper.open(signal, 'auto');
  }
  for (const position of [...paper.state.paperPositions]) {
    paper.close(position, candles.at(-1).close, 'END_OF_DATA');
  }
  return report.summarize(paper.state, settings.value.paperInitialEquity, PROFILE);
}

// ---------- گرید پارامترها ----------
// holdBars: مدت نگهداری بر حسب «کندل دیتا» — در LIVE معادل دقیقه می‌شود
const GRIDS = {
  fast: {
    minScore: [72, 85],
    atrStopMult: [1.4, 2.2],
    takeProfitR: [1.5, 2.0],
    holdBars: [2, 12],
    microCandleCheck: ['true'],
    profitMode: ['float'],
    trailAtrMult: [1.0, 1.8]
  },
  full: {
    minScore: [72, 78, 85],
    atrStopMult: [1.4, 1.8, 2.2],
    takeProfitR: [1.2, 1.5, 2.0],
    holdBars: [2, 6, 12, 24],
    microCandleCheck: ['true', 'false'],
    profitMode: ['float', 'fixed'],
    trailAtrMult: [1.0, 1.8],
    fadeCandles: [0, 2]
  }
};

function combos(grid) {
  const keys = Object.keys(grid);
  const out = [];
  const walk = (i, acc) => {
    if (i === keys.length) {
      out.push({ ...acc });
      return;
    }
    for (const v of grid[keys[i]]) walk(i + 1, { ...acc, [keys[i]]: v });
  };
  walk(0, {});
  return out;
}

const fmtN = (v, d = 2) => Number.isFinite(v) ? v.toFixed(d) : '--';
const rankKey = r => (r.count >= 8 && Number.isFinite(r.profitFactor) ? r.profitFactor : -1);

async function main() {
  const isDemo = args.includes('--demo');
  let candles;
  if (isDemo) {
    candles = demoCandles();
    console.log('⚙️  حالت --demo: دیتای سینتتیک قطعی — فقط اعتبارسنجی خط لوله؛ نتیجه‌ها معتبر نیستند!\n');
  } else {
    if (!DATA) {
      console.error('استفاده: node tools/backtest.mjs --data data/BTCUSDT-1h.jsonl [--grid fast|full] [--split 70] [--demo]');
      process.exit(1);
    }
    candles = await loadCandles(DATA);
    console.log(`📊 ${candles.length} کندل واقعی بارگذاری شد از ${DATA}`);
    console.log(`   بازه: ${new Date(candles[0].ts).toISOString().slice(0, 10)} → ${new Date(candles.at(-1).ts).toISOString().slice(0, 10)}\n`);
  }
  if (candles.length < WARMUP + 100) {
    console.error('❌ داده برای بک‌تست کافی نیست (حداقل ~۱۶۰ کندل).');
    process.exit(1);
  }
  const dataTfMs = candles.length > 1 ? candles[1].ts - candles[0].ts : 3_600_000;
  const tfLabel = dataTfMs >= 86_400_000 ? `${Math.round(dataTfMs / 86_400_000)}D` : `${Math.round(dataTfMs / 3_600_000)}h`;
  console.log(`⏱ تایم‌فریم دیتا: ${tfLabel} | MaxHold به ${Math.max(1, Math.round(Number(DEFAULT_SETTINGS.maxHoldMinutes) * dataTfMs / 3_600_000))} دقیقه مقیاس شد (معادل ${DEFAULT_SETTINGS.maxHoldMinutes / 60} کندل)`);

  // ---------- ۱) وضعیت فعلی سیستم (تنظیمات پیش‌فرض) روی کل داده ----------
  console.log('━━━ ۱) سیستم با تنظیمات فعلی (DEFAULT) ━━━');
  const currentFull = runOnce(candles, {});
  console.log(`   معاملات: ${currentFull.count} | Win-rate: ${fmtN(currentFull.winRate, 1)}% | Net PnL: ${fmtN(currentFull.netPnl, 2)} | PF: ${fmtN(currentFull.profitFactor)} | MaxDD: ${fmtN(currentFull.maxDrawdown, 2)} | Expectancy: ${fmtN(currentFull.expectancy, 3)}`);

  // ---------- ۲) Walk-Forward ----------
  const cut = Math.floor(candles.length * Math.min(90, Math.max(50, SPLIT)) / 100);
  const train = candles.slice(0, cut);
  const test = candles.slice(cut);
  console.log(`\n━━━ ۲) جستجوی گرید (${GRID}) — Walk-Forward ضد Overfit ━━━`);
  console.log(`   Train: ${train.length} کندل (${new Date(train[0].ts).toISOString().slice(0, 10)} → ${new Date(train.at(-1).ts).toISOString().slice(0, 10)})`);
  console.log(`   Test:  ${test.length} کندل (${new Date(test[0].ts).toISOString().slice(0, 10)} → ${new Date(test.at(-1).ts).toISOString().slice(0, 10)})`);

  const list = combos(GRIDS[GRID] || GRIDS.fast);
  const t0 = Date.now();
  const trainResults = [];
  for (const combo of list) {
    const r = runOnce(train, combo);
    trainResults.push({ combo, r });
  }
  trainResults.sort((a, b) => rankKey(b.r) - rankKey(a.r));
  const top = trainResults.slice(0, 5);

  console.log(`\n   ${list.length} ترکیب روی Train اجرا شد (${((Date.now() - t0) / 1000).toFixed(1)}s) — ۵ ترکیب برتر:\n`);
  console.log('   # | minScore atrMult tpR  hold mode  trail fade micro | Trades  Win%    NetPnL    PF    | Test: Trades  Win%    NetPnL    PF');
  console.log('   ' + '-'.repeat(126));
  const finalRows = [];
  for (const [i, row] of top.entries()) {
    const tr = runOnce(test, row.combo);
    finalRows.push({ rank: i + 1, params: row.combo, train: row.r, test: tr });
    console.log(
      `   ${(i + 1).toString().padStart(2)} | ${String(row.combo.minScore).padEnd(8)} ${String(row.combo.atrStopMult).padEnd(6)} ${String(row.combo.takeProfitR).padEnd(4)} ${String(row.combo.holdBars || '-').padEnd(4)} ${(row.combo.profitMode || 'float').padEnd(5)} ${String(row.combo.trailAtrMult || '-').padEnd(5)} ${String(row.combo.fadeCandles ?? '-').padEnd(4)} ${row.combo.microCandleCheck === 'true' ? 'on ' : 'off'} ` +
      `| ${String(row.r.count).padEnd(6)} ${fmtN(row.r.winRate, 1).padStart(6)}% ${fmtN(row.r.netPnl, 2).padStart(9)} ${fmtN(row.r.profitFactor).padStart(6)} ` +
      `|       ${String(tr.count).padEnd(6)} ${fmtN(tr.winRate, 1).padStart(6)}% ${fmtN(tr.netPnl, 2).padStart(9)} ${fmtN(tr.profitFactor).padStart(6)}`
    );
  }

  const best = finalRows[0];
  const degradation = Number.isFinite(best.train.netPnl) && Number.isFinite(best.test.netPnl)
    ? ((best.test.netPnl - best.train.netPnl) / Math.max(1, Math.abs(best.train.netPnl)) * 100).toFixed(1)
    : '--';
  console.log(`\n   🏆 بهترین ترکیب Train: minScore=${best.params.minScore}, atrStopMult=${best.params.atrStopMult}, takeProfitR=${best.params.takeProfitR}, hold=${best.params.holdBars}کندل, mode=${best.params.profitMode || 'float'}, trail=${best.params.trailAtrMult}, fade=${best.params.fadeCandles ?? 0}, micro=${best.params.microCandleCheck}`);
  console.log(`   تغییر NetPnL از Train به Test: ${degradation}% (افت شدید = هشدار Overfitting)`);

  // ---------- ذخیره نتایج ----------
  const resultPath = path.resolve('results', `backtest_${Date.now()}.json`);
  await mkdir(path.dirname(resultPath), { recursive: true });
  await writeFile(resultPath, JSON.stringify({
    generatedAt: new Date().toISOString(),
    data: isDemo ? 'SYNTHETIC-DEMO (pipeline test only)' : path.resolve(DATA),
    candles: candles.length,
    period: { from: new Date(candles[0].ts).toISOString(), to: new Date(candles.at(-1).ts).toISOString() },
    currentDefaults: currentFull,
    walkForward: { splitPct: SPLIT, grid: GRID, top: finalRows }
  }, null, 2), 'utf-8');
  console.log(`\n💾 نتایج کامل ذخیره شد: ${resultPath}`);
  console.log('\n⚠️ یادآوری صادقانه: بک‌تست روی یک نماد/بازه، تضمین آینده نیست؛ قبل از Real حتماً چند نماد و چند بازه را جدا بسنج.');
}

main().catch(error => {
  console.error('BACKTEST FAILED:', error);
  process.exit(1);
});
