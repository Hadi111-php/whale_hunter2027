/**
 * پل یک‌طرفه و کاملاً اختیاری به Pump/Dump Lab.
 * ---------------------------------------------------------------------------
 * اتوتریدر (این اپ) هرگز به خاطر رادار معطل نمی‌ماند: این ماژول در تایمر
 * خودش (۳۰ ثانیه، غیرمسدودکننده) آدرس `/api/hot` سرور Pump/Dump Lab را
 * می‌خواند و فقط «لیست نمادهای داغ» را کش می‌کند. scan() هرگز شبکه این
 * ماژول را await نمی‌کند؛ فقط از کش آماده می‌خواند. پیش‌فرض خاموش است.
 */
export class HotBridge {
  constructor(settings, logger, deps = {}) {
    this.s = settings;
    this.log = logger;
    this.fetchJson = deps.fetchJson || (async url => {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 5000);
      try {
        const response = await fetch(url, { signal: controller.signal, headers: { Accept: 'application/json' }, cache: 'no-store' });
        if (!response.ok) throw new Error(`${response.status}`);
        return await response.json();
      } finally {
        clearTimeout(timeout);
      }
    });
    this.now = deps.now || (() => Date.now());
    this.timer = null;
    this.hot = [];          // [{ symbol, side, changePct }]
    this.lastOkAt = 0;
    this.error = '';
  }

  enabled() {
    return Boolean(String(this.s.value.pumpBridgeUrl || '').trim());
  }

  symbols() {
    if (!this.enabled() || this.now() - this.lastOkAt > 10 * 60_000) return [];
    return this.hot.map(rec => rec.symbol).filter(Boolean);
  }

  async refresh() {
    if (!this.enabled()) return;
    const base = String(this.s.value.pumpBridgeUrl).trim().replace(/\/$/, '');
    try {
      const body = await this.fetchJson(`${base}/api/hot`);
      const symbols = Array.isArray(body?.symbols) ? body.symbols : [];
      this.hot = symbols.map(symbol => ({ symbol: String(symbol).toUpperCase() }));
      this.lastOkAt = this.now();
      if (this.error) this.log.info('PUMP BRIDGE RECOVERED', { symbols: this.hot.length });
      this.error = '';
    } catch (error) {
      if (this.error !== error.message) {
        this.log.info('PUMP BRIDGE ERROR', { error: error.message });
        this.error = error.message;
      }
    }
  }

  start() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    if (!this.enabled()) return;
    void this.refresh();
    this.timer = setInterval(() => void this.refresh(), 30_000);
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }
}
