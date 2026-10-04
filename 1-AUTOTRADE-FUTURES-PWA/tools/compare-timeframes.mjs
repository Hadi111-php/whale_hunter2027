#!/usr/bin/env node
/**
 * مقایسهٔ تایم‌فریم‌ها — «بهترین تایم‌فریم کندل برای سوددهی کدام است؟»
 * ---------------------------------------------------------------------------
 * همان موتور زنده (strategy + paper-broker) را روی چند دیتاست با تایم‌فریم‌های
 * متفاوت اجرا می‌کند: تنظیمات پیش‌فرض + بهترین ترکیب Walk-Forward هر تایم‌فریم.
 *
 * استفاده:
 *   node tools/compare-timeframes.mjs --data data/BTCUSDT-1h.jsonl --data data/BTCUSDT-4h.jsonl --data data/BTCUSDT-1d.jsonl
 *   node tools/compare-timeframes.mjs --dir data --grid fast
 */
import { readdir, readFile } from 'node:fs/promises';
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
const GRID = arg('grid', 'fast');
const SPLIT = Number(arg('split', 70));
const dataArgs = args.flatMap((a, i) => (a === '--data' && args[i + 1] && !String(args[i + 1]).startsWith('--')) ? [args[i + 1]] : []);
const DIR = arg('dir', '');

const WARMUP = 60;
const LIVE_WINDOW = 200;

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
    } catch { /* skip */ }
  }
  return candles.sort((a, b) => a.ts - b.ts);
}

function runOnce(candles, overrides) {
  const tfMs = candles.length > 1 ? Math.max(60_000, candles[1].ts - candles[0].ts) : 3_600_000;
  const defaultHoldBars = Math.max(1, Math.round(Number(DEFAULT_SETTINGS.maxHoldMinutes) * 3_600_000 / tfMs));
  const holdBars = Number(overrides.holdBars) || defaultHoldBars;
  const settings = {
    value: {
      ...DEFAULT_SETTINGS,
      timeframe: String(DEFAULT_SETTINGS.timeframe),
      riskProfile: 'backtest',
      customFormula: '',
      formulaMode: 'off',
      maxHoldMinutes: holdBars * (tfMs / 60_000),
      ...overrides,
      holdBars: undefined,
      profitMode: overrides.profitMode || 'float',
      fadeCandles: overrides.fadeCandles === undefined ? undefined : Number(overrides.fadeCandles),
      microCandleTf: DEFAULT_SETTINGS.microCandleTf
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
    simNow = candle.ts + tfMs;
    const history = candles.slice(Math.max(0, i + 1 - LIVE_WINDOW), i + 1);
    const market = {
      symbol: 'BACKTEST',
      price: candle.close,
      candles: history,
      microCandles: { candles: history },
      lastCandle: candle,
      receivedAt: simNow,
      tfMs,
      source: 'BACKTEST'
    };
    const signal = strategy.analyze(market);
    signalsMap.set('BACKTEST', signal);
    marketMap.set('BACKTEST', { symbol: 'BACKTEST', price: candle.close, lastCandle: candle, atr: signal.atr, candles: history });
    paper.updateStops(marketMap, signalsMap);
    if (signal.side !== 'WAIT') paper.open(signal, 'auto');
  }
  for (const position of [...paper.state.paperPositions]) {
    paper.close(position, candles.at(-1).close, 'END_OF_DATA');
  }
  return report.summarize(paper.state, settings.value.paperInitialEquity, 'backtest');
}

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
    if (i === keys.length) { out.push({ ...acc }); return; }
    for (const v of grid[keys[i]]) walk(i + 1, { ...acc, [keys[i]]: v });
  };
  walk(0, {});
  return out;
}

const rankKey = r => (r.count >= 5 && Number.isFinite(r.profitFactor) ? r.profitFactor : -1);
const fmtN = (v, d = 2) => Number.isFinite(v) ? v.toFixed(d) : '--';
const tfLabel = ms => ms >= 86_400_000 ? '1D' : ms >= 7_200_000 ? `${Math.round(ms / 3_600_000)}h` : `${Math.round(ms / 60_000)}m`;

async function main() {
  let files = dataArgs;
  if (!files.length && DIR) {
    const all = await readdir(DIR);
    files = all.filter(f => /\.jsonl$/i.test(f) && !f.includes('legacy')).map(f => path.join(DIR, f));
  }
  if (!files.length) {
    console.error('استفاده: node tools/compare-timeframes.mjs --data data/BTCUSDT-1h.jsonl --data data/BTCUSDT-4h.jsonl ... یا --dir data');
    process.exit(1);
  }

  const results = [];
  for (const file of files) {
    const candles = await loadCandles(file);
    if (candles.length < WARMUP + 100) {
      console.log(`⏭ ${file}: داده کافی نیست (${candles.length} کندل) — رد شد`);
      continue;
    }
    const tf = candles[1].ts - candles[0].ts;
    const cut = Math.floor(candles.length * Math.min(90, Math.max(50, SPLIT)) / 100);
    const train = candles.slice(0, cut);
    const test = candles.slice(cut);

    const defaults = runOnce(candles, {});
    const list = combos(GRIDS[GRID] || GRIDS.fast);
    let best = null;
    for (const combo of list) {
      const r = runOnce(train, combo);
      if (!best || rankKey(r) > rankKey(best.r)) best = { combo, r };
    }
    const bestTest = best ? runOnce(test, best.combo) : null;
    results.push({
      file: path.basename(file), tf, tfText: tfLabel(tf), candles: candles.length,
      windowDays: (candles.at(-1).ts - candles[0].ts) / 86_400_000,
      defaults, bestCombo: best?.combo, bestTrain: best?.r, bestTest
    });
  }

  results.sort((a, b) => (b.bestTest ? rankKey(b.bestTest) : -1) - (a.bestTest ? rankKey(a.bestTest) : -1));

  console.log('\n🔬 مقایسهٔ تایم‌فریم‌ها — همان موتور زنده، همان گرید، دیتای واقعی Coinbase/Gate');
  console.log('   (هر ردیف: تنظیمات پیش‌فرض روی کل بازه + بهترین ترکیب Walk-Forward آن تایم‌فریم)\n');
  console.log('TF   | بازه (روز) | کندل | پیش‌فرض: معامله Win%  PF    NetPnL  | بهینه Test: معامله Win%  PF    NetPnL');
  console.log('-'.repeat(118));
  for (const r of results) {
    const d = r.defaults;
    const t = r.bestTest;
    console.log(
      `${r.tfText.padEnd(4)} | ${String(Math.round(r.windowDays)).padStart(6)}      | ${String(r.candles).padStart(4)} | ` +
      `${String(d.count).padStart(4)}  ${fmtN(d.winRate, 1).padStart(5)}% ${fmtN(d.profitFactor).padStart(5)} ${fmtN(d.netPnl, 1).padStart(8)} | ` +
      `${t ? `${String(t.count).padStart(4)}  ${fmtN(t.winRate, 1).padStart(5)}% ${fmtN(t.profitFactor).padStart(5)} ${fmtN(t.netPnl, 1).padStart(8)}` : '--'}`
    );
  }

  if (results.length && results[0].bestCombo) {
    const winner = results[0];
    console.log(`\n🏆 بهترین تایم‌فریم (بر اساس Test PF): ${winner.tfText}`);
    console.log(`   بهترین ترکیب: minScore=${winner.bestCombo.minScore}, atrStopMult=${winner.bestCombo.atrStopMult}, takeProfitR=${winner.bestCombo.takeProfitR}, hold=${winner.bestCombo.holdBars}کندل, mode=${winner.bestCombo.profitMode}, trail=${winner.bestCombo.trailAtrMult}`);
  }

  console.log('\n⚠️ تذکر صادقانه: بازهٔ هر تایم‌فریم متفاوت است (هر چه دیتای بیشتری در دسترس بوده).');
  console.log('   برای حکم قطعی، روی سیستم خودت با fetch-history چند سال دیتای هر تایم‌فریم را بگیر و همین ابزار را اجرا کن.');
}

main().catch(error => {
  console.error('COMPARE FAILED:', error);
  process.exit(1);
});
