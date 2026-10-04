#!/usr/bin/env node
/**
 * کالبدشکافی دیتای چندسالهٔ واقعی معاملات (فایل‌های legacy در data/legacy/)
 * ---------------------------------------------------------------------------
 * این فایل‌ها خروجی داشبورد قدیمی داداش هادی هستند: معاملات واقعیِ شبیه‌سازی‌شدهٔ
 * BTCUSDT (۱h/4h) از ژانویه ۲۰۲۱ به بعد. این ابSTRACT baseline علمی می‌سازد:
 * «استراتژی قبلی در همین دیتا چه کار کرده؟» تا عملکرد موتور جدید با آن مقایسه شود.
 *
 * استفاده:  node tools/analyze-legacy-trades.mjs [--file data/legacy/xxx.jsonl]
 */
import { readdir, readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';

const args = process.argv.slice(2);
const fileIdx = args.indexOf('--file');
const single = fileIdx >= 0 ? args[fileIdx + 1] : null;
const DIR = path.resolve('data/legacy');

async function loadTrades(file) {
  const raw = await readFile(file, 'utf-8');
  const trades = [];
  let meta = null;
  for (const line of raw.split('\n')) {
    const l = line.trim();
    if (!l) continue;
    try {
      const o = JSON.parse(l);
      if (o.kind === 'backtest_header') meta = { strategy: o.strategyName, symbol: o.symbol, interval: o.interval };
      else if (o.kind === 'backtest_trade') trades.push(o);
    } catch { /* skip */ }
  }
  return { meta, trades };
}

function analyze(trades) {
  if (!trades.length) return null;
  const sorted = [...trades].sort((a, b) => (a.entryTime || 0) - (b.entryTime || 0));
  let net = 0, fees = 0, funding = 0;
  let grossP = 0, grossL = 0;
  let peak = 0, curve = 0, maxDD = 0;
  let wins = 0, losses = 0;
  let holdBars = 0;
  for (const t of sorted) {
    const pnl = Number(t.pnl || 0);
    net += pnl;
    fees += Number(t.fees || 0);
    funding += Number(t.funding || 0);
    if (pnl > 0) { wins += 1; grossP += pnl; }
    if (pnl < 0) { losses += 1; grossL += Math.abs(pnl); }
    curve += pnl;
    peak = Math.max(peak, curve);
    maxDD = Math.max(maxDD, peak - curve);
    holdBars += Number(t.bars || 0);
  }
  const byYear = {};
  for (const t of sorted) {
    const y = new Date(Number(t.entryTime)).getUTCFullYear();
    byYear[y] = byYear[y] || { n: 0, pnl: 0, wins: 0 };
    byYear[y].n += 1;
    byYear[y].pnl += Number(t.pnl || 0);
    if (Number(t.pnl) > 0) byYear[y].wins += 1;
  }
  const first = new Date(Number(sorted[0].entryTime));
  const last = new Date(Number(sorted.at(-1).exitTime || sorted.at(-1).entryTime));
  return {
    count: sorted.length,
    wins, losses,
    winRate: wins / sorted.length * 100,
    netPnl: net,
    fees, funding,
    profitFactor: grossL > 0 ? grossP / grossL : (grossP > 0 ? Infinity : 0),
    expectancy: net / sorted.length,
    maxDrawdown: maxDD,
    avgHoldBars: holdBars / sorted.length,
    period: { from: first.toISOString().slice(0, 10), to: last.toISOString().slice(0, 10) },
    byYear
  };
}

const fmt = (v, d = 2) => Number.isFinite(v) ? v.toFixed(d) : '--';

async function main() {
  const files = single ? [path.resolve(single)] : (await readdir(DIR)).filter(f => f.endsWith('.jsonl')).map(f => path.join(DIR, f));
  if (!files.length) {
    console.error('هیچ فایلی پیدا نشد. اول دیتای legacy را در data/legacy بگذار.');
    process.exit(1);
  }

  const all = [];
  let bestFile = null;
  for (const file of files) {
    const { meta, trades } = await loadTrades(file);
    if (!trades.length) continue;
    const stats = analyze(trades);
    all.push({ file: path.basename(file), meta, stats });
    if (!bestFile || stats.count > bestFile.stats.count) bestFile = all.at(-1);
  }

  all.sort((a, b) => b.stats.count - a.stats.count);
  console.log(`\n📜 تحلیل ${all.length} فایل دیتای چندساله معاملات (legacy)\n`);
  console.log('فایل | استراتژی | بازه | معاملات | Win% | Net PnL | PF | MaxDD');
  console.log('-'.repeat(110));
  for (const a of all) {
    console.log(
      `${a.file.slice(0, 28)} | ${(a.meta?.strategy || '--').slice(0, 22)} | ${a.stats.period.from}→${a.stats.period.to} | ${a.stats.count} | ${fmt(a.stats.winRate, 1)}% | ${fmt(a.stats.netPnl, 0)} | ${fmt(a.stats.profitFactor)} | ${fmt(a.stats.maxDrawdown, 0)}`
    );
  }

  if (bestFile) {
    const b = bestFile.stats;
    console.log(`\n🏆 پایه مقایسه (بزرگ‌ترین مجموعه): ${bestFile.file}`);
    console.log(`   استراتژی: ${bestFile.meta?.strategy || '--'} | نماد: ${bestFile.meta?.symbol} ${bestFile.meta?.interval}`);
    console.log(`   بازه: ${b.period.from} → ${b.period.to} (${b.count} معامله واقعیِ شبیه‌سازی)`);
    console.log(`   Win-rate: ${fmt(b.winRate, 1)}% | Net PnL: ${fmt(b.netPnl, 2)} | Profit Factor: ${fmt(b.profitFactor)} | Expectancy: ${fmt(b.expectancy, 3)}`);
    console.log(`   Max Drawdown: ${fmt(b.maxDrawdown, 2)} | کارمزد: ${fmt(b.fees, 2)} | فاندینگ: ${fmt(b.funding, 2)} | میانگین Hold: ${fmt(b.avgHoldBars, 1)} کندل`);
    console.log('   عملکرد سالانه:');
    for (const [year, s] of Object.entries(b.byYear)) {
      console.log(`      ${year}: ${s.n} معامله | Win ${fmt(s.wins / s.n * 100, 1)}% | PnL ${fmt(s.pnl, 2)}`);
    }
  }

  const outPath = path.resolve('results', `legacy_report_${Date.now()}.json`);
  await mkdir(path.dirname(outPath), { recursive: true });
  await writeFile(outPath, JSON.stringify({ generatedAt: new Date().toISOString(), files: all.map(a => ({ file: a.file, meta: a.meta, stats: a.stats })) }, null, 2), 'utf-8');
  console.log(`\n💾 گزارش کامل: ${outPath}`);
}

main().catch(error => {
  console.error('ANALYZE FAILED:', error);
  process.exit(1);
});
