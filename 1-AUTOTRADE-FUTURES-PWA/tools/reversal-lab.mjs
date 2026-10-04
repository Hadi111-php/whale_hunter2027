#!/usr/bin/env node
/**
 * 🔄 آزمایشگاه برگشت روند — الگوهای V (کف) و Λ (سقف) روی دادهٔ واقعی
 * ---------------------------------------------------------------------------
 * خواستهٔ داداش هادی: «با مشاهدهٔ JSON داده‌ها، جاهایی که بازار تغییر روند می‌دهد
 * پیدا کن و بهترین الگوریتم برای شکل‌های \/ و /\ هر ارز را بیاب.»
 *
 * سه حالت:
 *   ۱) گزارش الگوها:      node tools/reversal-lab.mjs --data data/BTCUSDT-6h.jsonl
 *   ۲) جستجوی بهترین پارامتر (پایداری روی دو نیمه — ضد overfit):
 *                          node tools/reversal-lab.mjs --data data/BTCUSDT-6h.jsonl --sweep
 *   ۳) سنجش بهرهٔ سیستم از برگشت‌ها (خروجی JSON واقعی + کندل‌ها):
 *                          node tools/reversal-lab.mjs --data data/BTCUSDT-6h.jsonl --live export.json
 *
 * معیار «بهترین پارامتر»: تعداد الگوهای معنادار (V/Λ) که در «هر دو نیمهٔ داده»
 * توزیع شده‌اند (min(h1,h2)) + قدرت متوسط الگوها — نه بیشینهٔ تعداد روی کل داده.
 */
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { detectReversals, DEFAULT_REVERSAL_PARAMS } from '../src/js/services/reversal-detector.js';

const args = process.argv.slice(2);
const arg = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};
const DATA = arg('data', '');
const LIVE = arg('live', '');
const SWEEP = args.includes('--sweep');
const AFTER_BARS = Number(arg('afterBars', 3)); // چند کندل بعد از کف، ورود هنوز «سوار بر V» است

async function loadCandles(file) {
  const raw = await readFile(file, 'utf-8');
  const candles = [];
  for (const line of raw.split('\n')) {
    const l = line.trim();
    if (!l) continue;
    try {
      const o = JSON.parse(l);
      const c = o && typeof o === 'object' && 'open' in o ? o : null;
      if (c && [c.ts, c.open, c.high, c.low, c.close].every(Number.isFinite)) candles.push(c);
    } catch { /* رد */ }
  }
  return candles.sort((a, b) => a.ts - b.ts);
}

const fmt = (v, d = 2) => (Number.isFinite(v) ? v.toFixed(d) : '--');
const dstr = ts => new Date(ts).toISOString().slice(0, 10);

function stats(events) {
  if (!events.length) return { count: 0 };
  const vs = events.filter(e => e.kind === 'V');
  const ls = events.filter(e => e.kind === 'L');
  const avg = arr => (arr.length ? arr.reduce((a, e) => a + e.strengthPct, 0) / arr.length : 0);
  const avgBars = arr => (arr.length ? arr.reduce((a, e) => a + e.leftBars + e.rightBars, 0) / arr.length : 0);
  return {
    count: events.length, vCount: vs.length, lCount: ls.length,
    avgStrength: avg(events), avgVStrength: avg(vs), avgLStrength: avg(ls),
    avgWidthBars: avgBars(events)
  };
}

// ---------- سنجش بهرهٔ سیستم از برگشت‌ها ----------
function captureAnalysis(candles, events, trades, afterBars = 3) {
  const tfMs = candles.length > 1 ? candles[1].ts - candles[0].ts : 3_600_000;
  const idxOfTs = ts => {
    // نزدیک‌ترین کندل به این زمان
    let lo = 0, hi = candles.length - 1, best = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (candles[mid].ts <= ts) { best = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return best;
  };
  const rows = [];
  let vCaught = 0, vTotal = 0, lCaught = 0, lTotal = 0;
  for (const e of events) {
    if (e.kind === 'V') {
      vTotal += 1;
      // ورود LONG در پنجرهٔ [کف، کف+afterBars] = سوار شدن روی برگشت صعودی
      const winEnd = e.ts + afterBars * tfMs;
      const entry = trades.find(t => t.side === 'LONG' && t.time >= e.ts - tfMs && t.time <= winEnd);
      if (entry) vCaught += 1;
      rows.push({ kind: 'V', ts: e.ts, price: e.price, strengthPct: e.strengthPct, caught: Boolean(entry), trade: entry ? { time: entry.time, pnl: entry.pnl, reason: entry.reason } : null });
    } else {
      lTotal += 1;
      // خروج LONG یا ورود SHORT نزدیک سقف = استفاده از برگشت نزولی
      const winStart = e.ts - afterBars * tfMs;
      const exit = trades.find(t => t.time >= winStart && t.time <= e.ts + tfMs && ((t.side === 'LONG' && t.time > t.entryTimeIfAny) || t.side === 'SHORT'));
      const exitLong = trades.find(t => t.side === 'LONG' && t.time >= winStart && t.time <= e.ts + tfMs);
      const entryShort = trades.find(t => t.side === 'SHORT' && t.time >= winStart && t.time <= e.ts + tfMs);
      if (exitLong || entryShort) lCaught += 1;
      rows.push({ kind: 'L', ts: e.ts, price: e.price, strengthPct: e.strengthPct, caught: Boolean(exitLong || entryShort), trade: (exitLong || entryShort) ? { time: (exitLong || entryShort).time, pnl: (exitLong || entryShort).pnl, reason: (exitLong || entryShort).reason } : null });
    }
  }
  return {
    rows,
    vCaught, vTotal, vRate: vTotal ? (vCaught / vTotal * 100) : null,
    lCaught, lTotal, lRate: lTotal ? (lCaught / lTotal * 100) : null
  };
}

async function main() {
  if (!DATA) {
    console.error('استفاده: node tools/reversal-lab.mjs --data data/BTCUSDT-6h.jsonl [--sweep] [--live export.json]');
    process.exit(1);
  }
  const candles = await loadCandles(DATA);
  if (candles.length < 60) {
    console.error('❌ داده کافی نیست (حداقل ~۶۰ کندل).');
    process.exit(1);
  }
  const tfMs = candles[1].ts - candles[0].ts;
  const tfName = tfMs >= 86_400_000 ? `${Math.round(tfMs / 86_400_000)}D` : `${Math.round(tfMs / 3_600_000)}h`;
  console.log(`🔄 آزمایشگاه برگشت روند — ${candles.length} کندل ${tfName} | ${dstr(candles[0].ts)} → ${dstr(candles.at(-1).ts)}\n`);

  // ---------- ۱) گزارش با پارامتر پیش‌فرض ----------
  const base = detectReversals(candles, DEFAULT_REVERSAL_PARAMS);
  const st = stats(base);
  console.log('━━━ ۱) الگوهای V/Λ (پارامتر پیش‌فرض) ━━━');
  console.log(`   کف‌های برگشتی V (\\/): ${st.vCount} | سقف‌های برگشتی Λ (/\\): ${st.lCount}`);
  console.log(`   قدرت متوسط الگو: ${fmt(st.avgStrength)}٪ (V: ${fmt(st.avgVStrength)}٪ | Λ: ${fmt(st.avgLStrength)}٪) | عرض متوسط: ${fmt(st.avgWidthBars, 1)} کندل`);
  const strongest = [...base].sort((a, b) => b.strengthPct - a.strengthPct).slice(0, 8);
  console.log('   قوی‌ترین‌ها:');
  for (const e of strongest) {
    console.log(`     ${e.kind === 'V' ? '\\/ کف' : '/\\ سقف'} ${dstr(e.ts)} @ ${fmt(e.price, 2)} | قدرت ${fmt(e.strengthPct)}٪ | بازوها ${e.leftBars}+${e.rightBars} کندل | تقارن ${fmt(e.symmetry)}`);
  }

  // ---------- ۲) جستجوی بهترین پارامتر (پایداری دو نیمه) ----------
  let bestSweep = null;
  if (SWEEP) {
    const half = Math.floor(candles.length / 2);
    const h1 = candles.slice(0, half);
    const h2 = candles.slice(half);
    const grid = [];
    for (const left of [2, 3, 5]) {
      for (const minSwingPct of [0.8, 1.2, 2.0]) {
        for (const vDepthPct of [1.5, 2.5, 4.0]) {
          grid.push({ left, right: left, minSwingPct, vDepthPct });
        }
      }
    }
    const scored = grid.map(params => {
      const full = detectReversals(candles, params);
      const s1 = stats(detectReversals(h1, params));
      const s2 = stats(detectReversals(h2, params));
      const stability = Math.min(s1.count, s2.count) / Math.max(1, Math.max(s1.count, s2.count));
      // امتیاز: الگوهای معنادارِ پایدار + قدرت متوسط (بدون عبوس به الگوهای کم‌عمق)
      const score = Math.min(s1.count, s2.count) * 2 + stats(full).avgStrength * 0.5 + stability * 5;
      return { params, full: stats(full), h1: s1, h2: s2, stability, score };
    }).sort((a, b) => b.score - a.score);
    bestSweep = scored[0];
    console.log('\n━━━ ۲) بهترین پارامتر (پایداری روی دو نیمه — ضد overfit) ━━━');
    for (const r of scored.slice(0, 5)) {
      const p = r.params;
      console.log(`   L/R=${p.left} swing≥${p.minSwingPct}٪ depth≥${p.vDepthPct}٪ | کل ${String(r.full.count).padStart(3)} الگو (V:${r.full.vCount}/Λ:${r.full.lCount}) قدرت ${fmt(r.full.avgStrength, 1)}٪ | نیمه‌ها ${r.h1.count}/${r.h2.count} | پایداری ${fmt(r.stability * 100, 0)}٪ | امتیاز ${fmt(r.score, 1)}`);
    }
    console.log(`\n   🏆 پیشنهاد برای این ارز/بازه: left/right=${bestSweep.params.left}, minSwingPct=${bestSweep.params.minSwingPct}, vDepthPct=${bestSweep.params.vDepthPct}`);
  }

  // ---------- ۳) سنجش بهرهٔ سیستم از برگشت‌ها ----------
  let capture = null;
  if (LIVE) {
    const j = JSON.parse(await readFile(LIVE, 'utf-8'));
    const trades = (j.tradesHistory || j.paperTrades || (Array.isArray(j) ? j : []))
      .map(t => ({ ...t, time: Number(t.time) })).filter(t => Number.isFinite(t.time));
    const events = detectReversals(candles, (bestSweep || {}).params || DEFAULT_REVERSAL_PARAMS);
    capture = captureAnalysis(candles, events, trades, AFTER_BARS);
    console.log(`\n━━━ ۳) بهرهٔ سیستم از برگشت‌ها (${trades.length} معاملهٔ واقعی از خروجی JSON) ━━━`);
    console.log(`   ورود LONG نزدیک کف V: ${capture.vCaught}/${capture.vTotal} (${capture.vRate !== null ? fmt(capture.vRate, 0) : '--'}٪)`);
    console.log(`   خروج/SHORT نزدیک سقف Λ: ${capture.lCaught}/${capture.lTotal} (${capture.lRate !== null ? fmt(capture.lRate, 0) : '--'}٪)`);
    const missed = capture.rows.filter(r => !r.caught).sort((a, b) => b.strengthPct - a.strengthPct).slice(0, 6);
    if (missed.length) {
      console.log('   بزرگ‌ترین برگشت‌های ازدست‌رفته (فرصت‌های سوخته):');
      for (const m of missed) {
        console.log(`     ${m.kind === 'V' ? '\\/ کف' : '/\\ سقف'} ${dstr(m.ts)} @ ${fmt(m.price, 2)} | قدرت ${fmt(m.strengthPct)}٪ ← سیستم آنجا نداشت`);
      }
    }
  }

  // ---------- ذخیره ----------
  const outPath = path.resolve('results', `reversal_lab_${Date.now()}.json`);
  await mkdir(path.dirname(outPath), { recursive: true });
  await writeFile(outPath, JSON.stringify({
    generatedAt: new Date().toISOString(),
    data: path.resolve(DATA),
    timeframe: tfName,
    candles: candles.length,
    params: (bestSweep || {}).params || DEFAULT_REVERSAL_PARAMS,
    summary: st,
    events: base,
    sweep: SWEEP ? { best: bestSweep.params } : null,
    capture: capture ? { vRate: capture.vRate, lRate: capture.lRate, rows: capture.rows } : null
  }, null, 2), 'utf-8');
  console.log(`\n💾 خروجی JSON: ${outPath}`);
  console.log('\n⚠️ صداقت کامل: «بهترین پارامتر» مخصوص همین ارز/بازه است؛ قبل از اعتماد، روی نمادها و بازه‌های دیگر هم بسنج.');
}

main().catch(error => {
  console.error('REVERSAL LAB FAILED:', error);
  process.exit(1);
});
