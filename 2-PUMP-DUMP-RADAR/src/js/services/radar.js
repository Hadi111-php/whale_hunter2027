import { readJson, writeJson } from '../core/utils.js';
import { STORAGE_KEYS } from '../core/config.js';

// توکن‌های اهرمی (UP/DOWN/3L/3S/BULL/BEAR) هیچ‌وقت پمپ واقعی حساب نمی‌شوند
const LEVERAGED_RE = /((UP|DOWN|BULL|BEAR|3L|3S)USDT)$/i;
const num = value => {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};

async function defaultFetchJson(url) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 7000);
  try {
    const response = await fetch(url, { signal: controller.signal, headers: { Accept: 'application/json' }, cache: 'no-store' });
    const body = await response.json();
    if (!response.ok) throw new Error(`${response.status}: ${body?.retMsg || response.statusText || 'HTTP error'}`);
    if (body && body.retCode !== undefined && Number(body.retCode) !== 0) {
      throw new Error(`Bybit ${body.retCode}: ${body.retMsg || 'API error'}`);
    }
    return body;
  } finally {
    clearTimeout(timeout);
  }
}

/**
 * رادار پمپ/دامپ — کل بازار در یک فراخوان (Bybit مستقیم → Binance → OKX).
 * این ماژول در این پروژه مستقل زندگی می‌کند و با اتوتریدر Futures Scalp Lab
 * هیچ runtime مشترکی ندارد؛ تنها راه ارتباط (اختیاری) پل HTTP یک‌طرفه است.
 */
export class PumpRadar {
  constructor(settings, logger, deps = {}) {
    this.s = settings;
    this.log = logger;
    this.now = deps.now || (() => Date.now());
    this.fetchJson = deps.fetchJson || defaultFetchJson;
    this.storage = deps.storage || {
      read: (key, fallback) => readJson(key, fallback),
      write: (key, value) => writeJson(key, value)
    };
    this.history = Array.isArray(this.storage.read(STORAGE_KEYS.radarHistory, null)) ? this.storage.read(STORAGE_KEYS.radarHistory, []) : [];
    this.firstSeen = this.storage.read(STORAGE_KEYS.radarFirstSeen, {}) || {};
    this.active = new Map();
    this.recentEvents = [];
    this.readdBlockedUntil = new Map();
    this.movers = [];
    this.meta = { lastPollAt: 0, universe: 0, source: '--', error: '', warmupRemainMin: null };
  }

  enabled() {
    return String(this.s.value.radarEnabled) === 'true';
  }

  shouldPoll() {
    if (!this.enabled()) return false;
    const gapMs = Math.max(10, Number(this.s.value.radarPollSec) || 30) * 1000;
    return this.now() - Number(this.meta.lastPollAt || 0) >= gapMs;
  }

  blacklist() {
    return String(this.s.value.radarBlacklist || '')
      .split(',').map(item => item.trim().toUpperCase()).filter(Boolean);
  }

  excluded(symbol) {
    const value = String(symbol || '').toUpperCase();
    return this.blacklist().includes(value) || LEVERAGED_RE.test(value);
  }

  // زنجیره ضدتحریم: هر سه منبع فقط با «یک» فراخوان — کل بازار
  async fetchUniverse() {
    // ۱) Bybit V5 مستقیم — همه فیوچرز linear در یک پاسخ
    try {
      const body = await this.fetchJson(`https://api.bybit.com/v5/market/tickers?category=${encodeURIComponent(this.s.value.bybitCategory || 'linear')}`);
      const list = body?.result?.list;
      if (Array.isArray(list) && list.length > 20) {
        const rows = [];
        for (const r of list) {
          const symbol = String(r?.symbol || '');
          const price = num(r?.lastPrice);
          if (!symbol || price === null) continue;
          const ch24 = num(r?.price24hPcnt);
          rows.push({ symbol, price, turnover24h: num(r?.turnover24h) || 0, change24hPct: ch24 === null ? null : ch24 * 100 });
        }
        if (rows.length > 20) return { rows, source: 'BYBIT LIVE' };
      }
    } catch (e) { /* زنجیره به منبع بعدی می‌رود */ }
    // ۲) Binance مستقیم
    try {
      const body = await this.fetchJson('https://api.binance.com/api/v3/ticker/24hr');
      if (Array.isArray(body) && body.length) {
        const rows = body
          .filter(r => String(r.symbol || '').endsWith('USDT') && num(r.lastPrice) !== null)
          .map(r => ({ symbol: String(r.symbol), price: Number(r.lastPrice), turnover24h: num(r.quoteVolume) || 0, change24hPct: num(r.priceChangePercent) }));
        if (rows.length) return { rows, source: 'BINANCE LIVE (DIRECT)' };
      }
    } catch (e) { /* منبع بعدی */ }
    // ۳) OKX مستقیم
    try {
      const body = await this.fetchJson('https://www.okx.com/api/v5/market/tickers?instType=SPOT');
      const data = body?.data;
      if (Array.isArray(data) && data.length) {
        const rows = data
          .filter(r => String(r.instId || '').endsWith('-USDT') && num(r.last) !== null)
          .map(r => ({ symbol: String(r.instId).replace('-', ''), price: Number(r.last), turnover24h: num(r.volCcy24h) || 0, change24hPct: null }));
        if (rows.length) return { rows, source: 'OKX LIVE (DIRECT)' };
      }
    } catch (e) { /* منبع بعدی */ }
    throw new Error('رادار: هیچ منبع زنده (Bybit/Binance/OKX) پاسخ نداد');
  }

  windowRef(windowMs, nowT) {
    const need = nowT - windowMs;
    let ref = null;
    for (const point of this.history) {
      if (point.t <= need) ref = point;
      else break;
    }
    return ref;
  }

  persist() {
    try {
      this.storage.write(STORAGE_KEYS.radarHistory, this.history);
      this.storage.write(STORAGE_KEYS.radarFirstSeen, this.firstSeen);
    } catch (e) { /* پر شدن localStorage نباید رادار را بخواباند */ }
  }

  promote(record, maxActive) {
    if (this.active.has(record.symbol)) {
      const existing = this.active.get(record.symbol);
      existing.changePct = record.changePct;
      existing.turnover24h = record.turnover24h;
      existing.basis = record.basis;
      existing.peakChangePct = Math.max(Math.abs(existing.peakChangePct || 0), Math.abs(record.changePct));
      return false;
    }
    if (Number(this.readdBlockedUntil.get(record.symbol) || 0) > this.now()) return false;
    this.active.set(record.symbol, { ...record, peakChangePct: Math.abs(record.changePct) });
    if (this.active.size > maxActive) {
      let oldest = null;
      for (const rec of this.active.values()) if (!oldest || rec.since < oldest.since) oldest = rec;
      if (oldest) this.active.delete(oldest.symbol);
    }
    return true;
  }

  emitEvent(events, type, m, basis, extra = {}) {
    const event = {
      t: this.now(),
      type,
      symbol: m.symbol,
      price: Number(m.price) || null, // برای اعتبارسنج: قیمت لحظهٔ رخداد
      changePct: Number(m.changePct.toFixed(2)),
      basis,
      turnover24h: m.turnover24h,
      ...extra
    };
    events.push(event);
    this.recentEvents.unshift(event);
    this.recentEvents = this.recentEvents.slice(0, 60);
  }

  async poll() {
    const s = this.s.value;
    const nowT = this.now();
    const { rows, source } = await this.fetchUniverse();
    this.meta = { ...this.meta, lastPollAt: nowT, universe: rows.length, source, error: '' };

    const windowMs = Math.max(5, Number(s.radarWindowMin) || 60) * 60000;
    const resMs = Math.max(
      Math.max(60, Number(s.radarHistoryResolutionSec) || 300) * 1000,
      Math.ceil(windowMs / 20)
    );
    const prices = {};
    for (const r of rows) prices[r.symbol] = r.price;
    const lastPoint = this.history.at(-1);
    if (!lastPoint || nowT - lastPoint.t >= resMs) {
      this.history.push({ t: nowT, p: prices });
      const maxPoints = Math.ceil(windowMs / resMs) + 6;
      this.history = this.history.slice(-Math.max(6, maxPoints));
      this.persist();
    } else {
      lastPoint.p = prices;
    }

    const warmed = !!this.windowRef(windowMs, nowT);
    const warmupFallback = String(s.radarWarmupFallback) === 'true';
    this.meta.warmupRemainMin = warmed ? 0 : Math.max(1, Math.ceil((windowMs - (nowT - (this.history[0]?.t || nowT))) / 60000));

    const firstRun = Object.keys(this.firstSeen).length === 0;
    const newListingMin = Number(s.radarNewListingMin) || 720;
    let newSymbols = 0;
    for (const r of rows) {
      if (this.firstSeen[r.symbol] === undefined) {
        this.firstSeen[r.symbol] = nowT;
        newSymbols += 1;
      }
    }
    if (newSymbols > 0) this.persist();

    const movers = [];
    for (const r of rows) {
      if (this.excluded(r.symbol)) continue;
      let changePct = null;
      let basis = 'window';
      const refPrice = warmed ? this.windowRef(windowMs, nowT)?.p?.[r.symbol] : undefined;
      if (warmed && Number.isFinite(Number(refPrice)) && Number(refPrice) > 0) {
        changePct = (r.price / Number(refPrice) - 1) * 100;
      } else if (warmupFallback && r.change24hPct !== null && r.change24hPct !== undefined) {
        changePct = r.change24hPct;
        basis = '24h-proxy';
      }
      if (changePct === null || !Number.isFinite(changePct)) continue;
      const ageMin = (nowT - Number(this.firstSeen[r.symbol] ?? nowT)) / 60000;
      movers.push({ symbol: r.symbol, price: r.price, changePct, basis, turnover24h: r.turnover24h, change24hPct: r.change24hPct, isNew: ageMin <= newListingMin, ageMin });
    }
    movers.sort((a, b) => Math.abs(b.changePct) - Math.abs(a.changePct));
    this.movers = movers.slice(0, 40);

    const events = [];
    const pumpThr = Number(s.radarPumpThresholdPct);
    const dumpThr = Number(s.radarDumpThresholdPct);
    const minTurnover = Number(s.radarMinTurnover24h);
    const maxActive = Math.max(1, Number(s.radarMaxSymbols) || 8);
    const alertNew = String(s.radarNewListingAlert) === 'true';

    for (const m of movers) {
      if (m.turnover24h < minTurnover) continue;
      const isPump = m.changePct >= pumpThr;
      const isDump = m.changePct <= dumpThr;
      const freshListing = !firstRun && m.isNew && m.ageMin <= 5;

      if (isPump || isDump) {
        const side = isPump ? 'LONG' : 'SHORT';
        const added = this.promote({ symbol: m.symbol, side, changePct: m.changePct, basis: m.basis, since: nowT, turnover24h: m.turnover24h, isNew: m.isNew }, maxActive);
        if (added) this.emitEvent(events, isPump ? 'PUMP' : 'DUMP', m, m.basis, { side });
      } else if (freshListing && alertNew) {
        const added = this.promote({ symbol: m.symbol, side: 'WATCH', changePct: m.changePct, basis: m.basis, since: nowT, turnover24h: m.turnover24h, isNew: true }, maxActive);
        if (added) this.emitEvent(events, 'NEW', m, m.basis, { side: 'WATCH' });
      }
    }

    const ttlMs = Math.max(5, Number(s.radarTtlMin) || 120) * 60000;
    const readdBlockMs = 30 * 60000;
    for (const [symbol, rec] of [...this.active.entries()]) {
      const faded = rec.side !== 'WATCH' && Math.abs(rec.changePct) < Math.min(Math.abs(pumpThr), Math.abs(dumpThr)) * 0.5;
      const expired = nowT - rec.since >= ttlMs;
      if (faded || expired) {
        this.active.delete(symbol);
        this.readdBlockedUntil.set(symbol, nowT + readdBlockMs);
      }
    }
    for (const symbol of [...this.readdBlockedUntil.keys()]) {
      if (this.readdBlockedUntil.get(symbol) <= nowT) this.readdBlockedUntil.delete(symbol);
    }
    return events;
  }

  tradeableSymbols() {
    return [...this.active.values()].filter(rec => rec.side !== 'WATCH').map(rec => rec.symbol);
  }

  snapshot() {
    const s = this.s.value;
    const nowT = this.now();
    const ttlMs = Math.max(5, Number(s.radarTtlMin) || 120) * 60000;
    const active = [...this.active.values()].map(rec => ({ ...rec, ttlRemainMin: Math.max(0, Math.round((rec.since + ttlMs - nowT) / 60000)) }));
    return {
      enabled: this.enabled(),
      source: this.meta.source,
      lastPollAt: this.meta.lastPollAt,
      universe: this.meta.universe,
      warmupRemainMin: this.meta.warmupRemainMin,
      error: this.meta.error,
      movers: this.movers.slice(0, 12),
      active,
      events: this.recentEvents.slice(0, 20)
    };
  }
}
