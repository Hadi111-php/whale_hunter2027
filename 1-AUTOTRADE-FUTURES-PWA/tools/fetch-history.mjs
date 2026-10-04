#!/usr/bin/env node
/**
 * دریافت تاریخچه واقعی کندل‌ها از صرافی‌های عمومی — برای بک‌تست.
 * ---------------------------------------------------------------------------
 * خروجی: فایل JSONL با کندل‌های {ts,open,high,low,close,volume} به ترتیب صعودی.
 *
 * استفاده:
 *   node tools/fetch-history.mjs --symbol BTCUSDT --interval 1h --days 365
 *   node tools/fetch-history.mjs --symbol ETHUSDT --interval 15m --days 90 --source gateio
 *
 * منابع (به ترتیب تلاش): gateio → binance → okx
 * همه endpointها عمومی هستند و هیچ کلید API لازم نیست.
 * توجه: در شبکه‌های تحریمی، binance/okx ممکن است خطای منطقه بدهند؛ gateio
 * معمولاً در دسترس است. VPN سیستم کافی است.
 */
import { writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';

const args = process.argv.slice(2);
const arg = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};
const SYMBOL = (arg('symbol', 'BTCUSDT') || '').toUpperCase();
const INTERVAL = arg('interval', '1h');
const DAYS = Number(arg('days', 365));
const SOURCE = arg('source', 'auto');
const OUT = arg('out', `data/${SYMBOL}-${INTERVAL}.jsonl`);

const SEC = { '1m': 60, '3m': 180, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '4h': 14400, '1d': 86400 };
const TF_SEC = SEC[INTERVAL];
if (!TF_SEC) {
  console.error(`اینتروال نامعتبر: ${INTERVAL} (مجاز: ${Object.keys(SEC).join(', ')})`);
  process.exit(1);
}

async function getJson(url) {
  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), 15000);
  try {
    const res = await fetch(url, { signal: controller.signal, headers: { Accept: 'application/json' } });
    const text = await res.text();
    if (!res.ok) throw new Error(`${res.status}: ${text.slice(0, 120)}`);
    return JSON.parse(text);
  } finally {
    clearTimeout(t);
  }
}

// --- Gate.io: [ts_sec, quote_vol, open, high, low, close, base_vol, closed] ---
async function fetchGate() {
  const pair = `${SYMBOL.replace('USDT', '_USDT')}`;
  const out = [];
  let to = Math.floor(Date.now() / 1000);
  const earliest = to - DAYS * 86400;
  for (let page = 0; page < 60; page += 1) {
    const rows = await getJson(`https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair=${pair}&interval=${INTERVAL}&limit=1000&to=${to}`);
    if (!Array.isArray(rows) || rows.length === 0) break;
    for (const r of rows) {
      out.push({ ts: Number(r[0]) * 1000, open: Number(r[2]), high: Number(r[3]), low: Number(r[4]), close: Number(r[5]), volume: Number(r[6]) });
    }
    const oldest = Number(rows.at(-1)[0]);
    if (oldest <= earliest) break;
    to = oldest - 1;
    process.stdout.write(`\r  gateio: ${out.length} کندل دریافت شد...   `);
  }
  return out;
}

// --- Binance: [open_time_ms, open, high, low, close, volume, ...] ---
async function fetchBinance() {
  const out = [];
  let endTime = Date.now();
  const earliest = endTime - DAYS * 86400 * 1000;
  const map = { '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m', '30m': '30m', '1h': '1h', '4h': '4h', '1d': '1d' };
  for (let page = 0; page < 60; page += 1) {
    const rows = await getJson(`https://api.binance.com/api/v3/klines?symbol=${SYMBOL}&interval=${map[INTERVAL]}&limit=1000&endTime=${endTime}`);
    if (!Array.isArray(rows) || rows.length === 0) break;
    for (const r of rows) {
      out.push({ ts: Number(r[0]), open: Number(r[1]), high: Number(r[2]), low: Number(r[3]), close: Number(r[4]), volume: Number(r[5]) });
    }
    const oldest = Number(rows[0][0]);
    if (oldest <= earliest) break;
    endTime = oldest - 1;
    process.stdout.write(`\r  binance: ${out.length} کندل دریافت شد...   `);
  }
  return out;
}

// --- OKX: [ts_ms, o, h, l, c, vol, ...] (حداکثر ۱۰۰ در فراخوانی) ---
async function fetchOkx() {
  const inst = SYMBOL.replace('USDT', '-USDT');
  const barMap = { '1m': '1m', '3m': '3m', '5m': '5m', '15m': '15m', '30m': '30m', '1h': '1H', '4h': '4H', '1d': '1D' };
  const out = [];
  let after = Date.now();
  const earliest = after - DAYS * 86400 * 1000;
  for (let page = 0; page < 400; page += 1) {
    const body = await getJson(`https://www.okx.com/api/v5/market/history-candles?instId=${inst}&bar=${barMap[INTERVAL]}&limit=100&after=${after}`);
    const rows = body?.data;
    if (!Array.isArray(rows) || rows.length === 0) break;
    for (const r of rows) {
      out.push({ ts: Number(r[0]), open: Number(r[1]), high: Number(r[2]), low: Number(r[3]), close: Number(r[4]), volume: Number(r[5]) });
    }
    const oldest = Number(rows.at(-1)[0]);
    if (oldest <= earliest) break;
    after = oldest;
    if (page % 10 === 0) process.stdout.write(`\r  okx: ${out.length} کندل دریافت شد...   `);
  }
  return out;
}

const sources = SOURCE === 'auto'
  ? [['gateio', fetchGate], ['binance', fetchBinance], ['okx', fetchOkx]]
  : [[SOURCE, { gateio: fetchGate, binance: fetchBinance, okx: fetchOkx }[SOURCE]]];

if (!sources[0][1]) {
  console.error(`منبع نامعتبر: ${SOURCE}`);
  process.exit(1);
}

let candles = [];
let usedSource = '';
for (const [name, fn] of sources) {
  process.stdout.write(`\n📡 تلاش با ${name} برای ${SYMBOL} ${INTERVAL} (${DAYS} روز)...\n`);
  try {
    const rows = await fn();
    if (rows.length > 100) {
      candles = rows;
      usedSource = name;
      break;
    }
    console.log(`  ${name} فقط ${rows.length} کندل داد؛ منبع بعدی...`);
  } catch (error) {
    console.log(`  ${name} خطا داد: ${error.message.slice(0, 120)}`);
  }
}

if (candles.length < 100) {
  console.error('\n❌ هیچ منبعی دیتای کافی نداد. با VPN امتحان کن یا source را عوض کن.');
  process.exit(1);
}

// نرمال‌سازی: حذف تکراری‌ها، مرتب صعودی، اعتبارسنجی
const seen = new Map();
for (const c of candles) {
  if (![c.ts, c.open, c.high, c.low, c.close, c.volume].every(Number.isFinite)) continue;
  if (c.high < c.low || c.open <= 0 || c.close <= 0) continue;
  seen.set(c.ts, c);
}
const sorted = [...seen.values()].sort((a, b) => a.ts - b.ts);
const gaps = sorted.slice(1).filter((c, i) => c.ts - sorted[i].ts !== TF_SEC * 1000).length;

const lines = sorted.map(c => JSON.stringify(c)).join('\n');
await mkdir(path.dirname(path.resolve(OUT)), { recursive: true });
await writeFile(OUT, lines + '\n', 'utf-8');

const first = new Date(sorted[0].ts).toISOString().slice(0, 10);
const last = new Date(sorted.at(-1).ts).toISOString().slice(0, 10);
console.log(`\n✅ ${sorted.length} کندل واقعی از ${usedSource} ذخیره شد: ${OUT}`);
console.log(`   بازه: ${first} → ${last} (${(sorted.length * TF_SEC / 86400).toFixed(1)} روز) | شکاف‌های زمانی: ${gaps}`);
console.log(`\n▶ حالا بک‌تست را اجرا کن:`);
console.log(`  node tools/backtest.mjs --data ${OUT}`);
