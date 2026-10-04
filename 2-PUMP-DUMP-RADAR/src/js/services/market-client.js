/**
 * کلاینت دیتای رادار پمپ/دامپ — فقط کندل تایم‌فریم ورود (1m/3m/5m).
 * زنجیره ضدتحریم: Bybit مستقیم → Binance مستقیم → OKX مستقیم.
 * نکته: تایم‌فریم اصلی اتوتریدر اینجا بی‌معناست؛ رادار روی تایم‌فریم ریز کار می‌کند.
 */
const OKX_BARS = Object.freeze({ '1': '1m', '3': '3m', '5': '5m', '15': '15m', '30': '30m', '60': '1H' });
const BINANCE_TFS = Object.freeze({ '1': '1m', '3': '3m', '5': '5m', '15': '15m', '30': '30m', '60': '1h' });

const parseRows = (list, newestFirst) => (list || [])
  .map(row => ({
    ts: Number(row[0]) * (String(row[0]).length === 10 ? 1000 : 1),
    open: Number(row[1]),
    high: Number(row[2]),
    low: Number(row[3]),
    close: Number(row[4]),
    volume: Number(row[5])
  }))
  .filter(c => [c.ts, c.open, c.high, c.low, c.close, c.volume].every(Number.isFinite) && c.volume >= 0)
  .sort((a, b) => a.ts - b.ts)
  .slice(-120); // فقط ۱۲۰ کندل آخر برای موتور ریز‌تایم کافی است

async function fetchJson(url, timeoutMs = 6500) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { signal: controller.signal, headers: { Accept: 'application/json' }, cache: 'no-store' });
    const body = await response.json();
    if (!response.ok) throw new Error(`${response.status}`);
    if (body && body.retCode !== undefined && Number(body.retCode) !== 0) throw new Error(`Bybit ${body.retCode}`);
    if (body && body.code !== undefined && String(body.code) !== '0') throw new Error(`OKX ${body.code}`);
    return body;
  } finally {
    clearTimeout(timeout);
  }
}

export class MarketClient {
  constructor(settings, logger) {
    this.s = settings;
    this.log = logger;
    this.cache = new Map();
  }

  async getKlines(symbol, timeframe, { ttlMs = 6000 } = {}) {
    const key = `${symbol}:${timeframe}`;
    const cached = this.cache.get(key);
    if (cached && Date.now() - cached.at < ttlMs) return cached.result;
    const result = await this.fetchKlines(symbol, timeframe);
    this.cache.set(key, { at: Date.now(), result });
    return result;
  }

  async fetchKlines(symbol, timeframe) {
    const tf = String(timeframe || this.s.value.entryTimeframe || '1');
    // ۱) Bybit مستقیم (در ایران قابل دسترس‌ترین)
    try {
      const body = await fetchJson(`https://api.bybit.com/v5/market/kline?category=linear&symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(tf)}&limit=120`);
      const rows = body?.result?.list;
      if (Array.isArray(rows) && rows.length >= 10) {
        return { candles: parseRows(rows, true), source: 'BYBIT LIVE' };
      }
    } catch (e) { /* زنجیره */ }
    // ۲) Binance مستقیم
    try {
      const interval = BINANCE_TFS[tf] || '1m';
      const data = await fetchJson(`https://api.binance.com/api/v3/klines?symbol=${encodeURIComponent(symbol)}&interval=${interval}&limit=120`);
      if (Array.isArray(data) && data.length >= 10) {
        return { candles: parseRows(data, false), source: 'BINANCE LIVE (DIRECT)' };
      }
    } catch (e) { /* زنجیره */ }
    // ۳) OKX مستقیم
    try {
      const inst = symbol.replace('USDT', '-USDT');
      const bar = OKX_BARS[tf] || '1m';
      const body = await fetchJson(`https://www.okx.com/api/v5/market/candles?instId=${encodeURIComponent(inst)}&bar=${bar}&limit=100`);
      if (body?.data?.length >= 10) {
        return { candles: parseRows(body.data, true), source: 'OKX LIVE (DIRECT)' };
      }
    } catch (e) { /* زنجیره */ }
    throw new Error(`دریافت کندل ${tf}m برای ${symbol} از Bybit/Binance/OKX ممکن نشد`);
  }
}
