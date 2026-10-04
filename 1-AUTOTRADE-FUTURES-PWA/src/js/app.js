import { $ } from './core/utils.js';
import { tfLabel } from './core/timeframe.js';
import { SettingsStore } from './services/settings-store.js';
import { Logger } from './services/logger.js';
import { MarketClient } from './services/market-client.js';
import { MomentumScalpStrategy } from './services/strategy.js';
import { PaperBroker } from './services/paper-broker.js';
import { RealBroker } from './services/real-broker.js';
import { PerformanceReport } from './services/performance-report.js';
import { AudioAlerts } from './services/audio-alerts.js';
import { HotBridge } from './services/hot-bridge.js';
import { DashboardView } from './ui/view.js';
import { SignalValidator } from './services/signal-validator.js';

export class ScalpLabApp {
  constructor() {
    this.settings = new SettingsStore();
    this.logger = new Logger();
    this.signals = new Map();
    this.prices = new Map();
    this.marketData = new Map();
    this.dataErrors = new Map();
    this.lastErrorLog = new Map();
    // علت شفاف «چرا معامله خودکار باز نشد» برای هر نماد — روی کارت ارز نمایش داده می‌شود
    this.blockReasons = new Map();
    this.audio = new AudioAlerts(this.settings, this.logger);
    // پل اختیاری و غیرمسدودکننده به Pump/Dump Lab (پیش‌فرض خاموش)
    this.hotBridge = new HotBridge(this.settings, this.logger);
    this.timer = null;
    this.scanInFlight = false;
    this.performance = new PerformanceReport();
    this.rebuildServices();
    // ✅ اعتبارسنج سیگنال — زمان قضاوت و آستانهٔ حرکت، زنده از Settings (v2.10.2)
    const svSet = this.settings.value;
    this.signalValidator = new SignalValidator({
      delayMs: Math.max(1, Number(svSet.signalCheckMinutes) || 15) * 60000,
      thresholdPct: Number(svSet.signalThresholdPct) > 0 ? Number(svSet.signalThresholdPct) : 1.5,
      persistKey: 'fsvp_signal_validator_v1'
    });
    this.view = new DashboardView(this);
  }

  rebuildServices() {
    this.market = new MarketClient(this.settings, this.logger);
    this.strategy = new MomentumScalpStrategy(this.settings);
    this.paper = this.paper || new PaperBroker(this.settings, this.logger);
    // Rebuilding services deliberately resets the real gate. A settings change
    // must never silently preserve permission to send an order.
    if (this.real?.enabled) this.real.kill();
    this.real = new RealBroker(this.settings, this.paper, this.logger);
    if (typeof document !== 'undefined' && $('#realAutoToggle')) $('#realAutoToggle').checked = false;
  }

  modeLabel() {
    const mode = this.settings.value.dataMode;
    if (mode === 'mock-local') return 'MOCK LOCAL';
    if (mode === 'mock-server') return 'MOCK SERVER';
    return 'LIVE'; // failover واقعی: Bybit → OKX → Binance (منبع دقیق در تب Data Feed)
  }

  timeframeLabel() {
    return tfLabel(this.settings.value.timeframe);
  }

  async scan() {
    if (this.scanInFlight) return;
    this.scanInFlight = true;
    this.paper.migrateDay();

    // لیست اسکن = نمادهای ثابت کاربر ∪ نمادهای داغ پل Pump/Dump Lab (فقط از کش؛ بدون await شبکه)
    const discovered = this.hotBridge.symbols();
    const symbols = [...new Set([...new Set(this.settings.value.symbols).filter(Boolean), ...discovered])];
    const s = this.settings.value;
    const minScore = Number(s.minScore);
    const microOn = String(s.microCandleCheck) === 'true';
    const microTf = String(s.microCandleTf || '1');
    $('#statusText').textContent = `${this.modeLabel()}؛ در حال دریافت دیتا...`;

    // Clear old values first. If Bybit is unavailable, stale prices/signals are
    // not presented as if they were current and no synthetic fallback is used.
    this.signals.clear();
    this.prices.clear();
    this.marketData.clear();
    this.dataErrors.clear();
    this.blockReasons.clear();

    try {
      const results = await Promise.allSettled(symbols.map(async symbol => {
        const market = await this.market.get(symbol);
        // کندل‌های ریز تاییدیه: اگر تایم‌فریم ریز همان تایم‌فریم اصلی باشد،
        // بدون درخواست اضافه از همان کندل‌ها استفاده می‌شود (صرفه‌جویی API).
        if (microOn) {
          market.microCandles = String(microTf) === String(s.timeframe)
            ? { candles: market.candles, source: `${market.source} (همان TF)` }
            : await this.market.getKlines(symbol, microTf).catch(() => null);
        }
        return market;
      }));
      let ok = 0;

      results.forEach((result, index) => {
        const symbol = symbols[index];
        if (result.status !== 'fulfilled') {
          const message = result.reason?.message || 'خطای ناشناخته دیتا';
          this.dataErrors.set(symbol, message);
          this.blockReasons.set(symbol, 'دیتای زنده دریافت نشد؛ ساخت سیگنال و ورود خودکار مسدود است');
          this.audio.drop(symbol);
          if (this.lastErrorLog.get(symbol) !== message) {
            this.logger.info('DATA ERROR', { symbol, error: message });
            this.lastErrorLog.set(symbol, message);
          }
          return;
        }
        ok += 1;
        this.lastErrorLog.delete(symbol);
        const market = result.value;
        const signal = this.strategy.analyze(market);
        this.marketData.set(symbol, market);
        this.signals.set(symbol, signal);
        this.prices.set(symbol, market.price);

        // ✅ اعتبارسنج: ثبت سیگنال‌های قوی (یک بار به‌ازای هر نماد در هر ۳۰ دقیقه)
        if (signal.side !== 'WAIT' && Number(signal.score) >= 60) {
          this.signalValidator.track(
            `sig:${symbol}:${signal.side}:${Math.floor(Date.now() / (30 * 60000))}`,
            { symbol, direction: signal.side, refPrice: market.price, meta: { score: signal.score } }
          );
        }
      });

      // ✅ قضاوت سیگنال‌های سررسیدشده با قیمت زندهٔ همین اسکن
      for (const item of this.signalValidator.pending(Date.now())) {
        const price = this.prices.get(item.symbol) ?? this.marketData.get(item.symbol)?.price;
        if (Number.isFinite(price)) this.signalValidator.settle(item.id, price, Date.now());
      }

      // Process exits before new entries. Closed-candle OHLC is used only as an
      // evidence that a stop/target was touched; with both touched, SL wins.
      this.paper.updateStops(this.marketData, this.signals);

      const paperToggle = $('#paperAutoToggle');
      const paperEnabled = !!paperToggle?.checked || this.real.enabled;
      for (const [symbol, signal] of this.signals.entries()) {
        // هشدار صوتی سطح ۱ — نزدیکی به آستانه ورود (Pre-Alert / Soft Chime)
        this.audio.preAlertCheck(signal);

        if (signal.side === 'WAIT') {
          const alreadyOpen = this.paper.state.paperPositions.some(position => position.symbol === symbol);
          const gateReason = signal.stale || signal.formulaMode === 'filter'
            ? signal.why
            : null;
          this.blockReasons.set(symbol, alreadyOpen
            ? `پوزیشن باز ${symbol} داریم؛ ورود جدید تا خروج مسدود است`
            : (gateReason || `امتیاز ${signal.score} کمتر از حد نصاب ${minScore} است (تایم‌فریم ${this.timeframeLabel()})`));
          continue;
        }

        if (paperEnabled) {
          const verdict = this.paper.evaluate(signal);
          if (!verdict.ok) {
            this.blockReasons.set(symbol, verdict.reason);
          } else if (this.paper.open(signal, 'auto')) {
            // هشدار صوتی سطح ۲ — معامله به صورت خودکار باز شد (Execution Beep)
            this.audio.execution(signal.side, symbol);
            this.blockReasons.delete(symbol);
          } else {
            this.blockReasons.set(symbol, 'باز شدن پوزیشن در PaperBroker رد شد');
          }
        } else {
          this.blockReasons.set(symbol, 'اتوترید مجازی (Paper Auto) خاموش است؛ سوییچ آن را در داشبورد روشن کن');
        }

        // Real is a second, explicit gate. It is never enabled by default and
        // requires BYBIT LIVE data plus a user-configured secure backend.
        if (this.real.enabled && signal.side !== 'WAIT' && signal.score >= minScore) {
          await this.real.send(signal);
        }
      }

      const update = new Date().toLocaleTimeString();
      const radarTail = discovered.length ? ` • 🚀+${discovered.length} کشف‌شده` : '';
      $('#lastUpdate').textContent = `آخرین اسکن: ${update} • ${ok}/${symbols.length}${radarTail}`;
      if (ok > 0) {
        $('#statusText').textContent = `${this.modeLabel()} • ${ok}/${symbols.length} بازار • ${this.timeframeLabel()}${radarTail}`;
      } else {
        $('#statusText').textContent = 'دیتای بازار در دسترس نیست؛ هیچ fallback ساختگی استفاده نشد';
      }
      this.view.renderAll();
    } finally {
      this.scanInFlight = false;
    }
  }

  applyRiskProfile(profile) {
    this.settings.applyRiskProfile(profile);
    this.rebuildServices();
    this.view.renderSettings();
    this.schedule();
    this.logger.info('RISK PROFILE APPLIED', { profile: this.settings.value.riskProfile });
    this.view.renderAll();
    void this.scan();
  }

  schedule() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    if ($('#autoScanToggle')?.checked) {
      const seconds = Math.max(3, Number(this.settings.value.scanIntervalSec) || 5);
      this.timer = setInterval(() => this.scan(), seconds * 1000);
    }
  }

  closeAllPaper() {
    for (const position of [...this.paper.state.paperPositions]) {
      this.paper.close(position, this.prices.get(position.symbol) || position.entry, 'close-all');
    }
    this.view.renderAll();
  }

  resetPaper() {
    this.paper.reset();
    this.view.renderAll();
  }

  async start() {
    this.view.bind();
    this.view.renderSettings();
    this.view.renderAll();
    this.schedule();
    this.hotBridge.start();
    this.logger.info('APP START', { mode: this.modeLabel(), paperDefault: this.settings.value.paperAutoDefault, bridge: this.hotBridge.enabled() ? 'ON' : 'OFF' });
    await this.scan().catch(error => this.logger.info('INITIAL SCAN ERROR', { error: error.message }));
    if ('serviceWorker' in navigator) navigator.serviceWorker.register('./sw.js').catch(() => {});
  }
}
