import { $, ignitionSummaryText } from './core/utils.js';
import { readJson, writeJson } from './core/utils.js';
import { DEFAULT_SETTINGS, STORAGE_KEYS } from './core/config.js';
import { Logger } from './services/logger.js';
import { PumpRadar } from './services/radar.js';
import { AudioAlerts } from './services/audio-alerts.js';
import { MarketClient } from './services/market-client.js';
import { IgnitionStrategy } from './services/ignition.js';
import { PaperBroker } from './services/paper-broker.js';
import { DashboardView } from './ui/view.js';
import { SignalValidator } from './services/signal-validator.js';

class SettingsStore {
  constructor() {
    this.value = { ...JSON.parse(JSON.stringify(DEFAULT_SETTINGS)), ...readJson(STORAGE_KEYS.settings, {}) };
  }
  save(next = this.value) {
    this.value = { ...JSON.parse(JSON.stringify(DEFAULT_SETTINGS)), ...next };
    writeJson(STORAGE_KEYS.settings, this.value);
  }
  reset() {
    this.save(JSON.parse(JSON.stringify(DEFAULT_SETTINGS)));
  }
}

/**
 * Pump/Dump Lab — اپ مستقل. چون اینجا فقط «یک» موتور (رادار + Ignition) دارد،
 * پول رادار همان حلقه اصلی است؛ برخلاف اتوتریدر که هیچ چیز نباید اسکنش را معطل کند.
 */
export class PumpDumpApp {
  constructor() {
    this.settings = new SettingsStore();
    this.logger = new Logger();
    this.radar = new PumpRadar(this.settings, this.logger);
    this.audio = new AudioAlerts(this.settings, this.logger);
    this.market = new MarketClient(this.settings, this.logger);
    this.strategy = new IgnitionStrategy(this.settings);
    this.paper = new PaperBroker(this.settings, this.logger);
    this.signals = new Map();
    this.marketData = new Map();
    this.blockReasons = new Map();
    this.timer = null;
    this.scanInFlight = false;
    // ✅ اعتبارسنج رادار — زمان قضاوت و آستانهٔ حرکت، زنده از Settings (v1.2.2)
    const svSet = this.settings.value;
    this.signalValidator = new SignalValidator({
      delayMs: Math.max(1, Number(svSet.radarCheckMinutes) || 10) * 60000,
      thresholdPct: Number(svSet.radarThresholdPct) > 0 ? Number(svSet.radarThresholdPct) : 1.5,
      persistKey: 'pdvp_signal_validator_v1'
    });
    this.view = new DashboardView(this);
  }

  async scan() {
    if (this.scanInFlight) return;
    this.scanInFlight = true;
    try {
      this.paper.migrateDay();
      $('#statusText').textContent = 'رادار؛ در حال پایش کل بازار...';

      // ۱) پول رادار (هر radarPollSec ثانیه) — کشف پمپ/دامپ/تازه‌لیست
      if (this.radar.shouldPoll()) {
        try {
          const events = await this.radar.poll();
          for (const ev of events) {
            this.audio.radarAlert(ev.type);
            this.logger.info('RADAR EVENT', ev);
            // ✅ ثبت برای اعتبارسنج (PUMP→انتظار رشد، DUMP→انتظار ریزش)
            if (ev.type !== 'NEW' && Number.isFinite(Number(ev.price))) {
              this.signalValidator.track(
                `ev:${ev.symbol}:${Math.floor(ev.t / 60000)}`,
                { symbol: ev.symbol, direction: ev.type === 'PUMP' ? 'LONG' : 'SHORT', refPrice: ev.price, meta: { changePct: ev.changePct } }
              );
            }
          }
          // ✅ قضاوت رویدادهای سررسیدشده (حداکثر ۵ تا در هر اسکن — سبک)
          for (const item of this.signalValidator.pending(Date.now()).slice(0, 5)) {
            try {
              const k = await this.market.getKlines(item.symbol, '5m');
              const last = k.candles?.at(-1);
              if (last) this.signalValidator.settle(item.id, last.close, Date.now());
            } catch { /* تلاش مجدد در اسکن بعدی */ }
          }
          this.publishBridge();
        } catch (error) {
          this.radar.meta.error = error.message;
          this.logger.info('RADAR ERROR', { error: error.message });
        }
      }

      // ۲) موتور Ignition فقط روی نمادهای کشف‌شده (نه WATCH)
      this.signals.clear();
      this.marketData.clear();
      this.blockReasons.clear();
      const autoOn = $('#autoTradeToggle')?.checked ?? true;
      const targets = [...this.radar.active.values()].filter(rec => rec.side !== 'WATCH');

      const results = await Promise.allSettled(targets.map(async rec => ({
        rec,
        klines: await this.market.getKlines(rec.symbol, this.settings.value.entryTimeframe)
      })));

      for (const result of results) {
        if (result.status !== 'fulfilled') {
          const symbol = result.reason?.symbol || '?';
          continue;
        }
        const { rec, klines } = result.value;
        const signal = this.strategy.analyze(rec, klines);
        const last = klines.candles.at(-1);
        this.signals.set(rec.symbol, signal);
        this.marketData.set(rec.symbol, {
          symbol: rec.symbol,
          price: last.close,
          lastCandle: last,
          atr: signal.atr,
          source: klines.source
        });
      }

      // ۳) مدیریت خروج پوزیشن‌های باز (SL سخت / Breakeven / ترلینگ / MaxHold)
      this.paper.updateStops(this.marketData);

      // ۴) ورود خودکار بدون انتظار برای تایید دستی (Zero-Wait)
      for (const signal of this.signals.values()) {
        if (signal.side === 'WAIT') {
          this.blockReasons.set(signal.symbol, `امتیاز ورود ${signal.score} < ${this.settings.value.ignitionMinScore} یا فیلترها تایید نکردند: ${signal.why}`);
          continue;
        }
        if (!autoOn) {
          this.blockReasons.set(signal.symbol, 'اتوترید مجازی خاموش است');
          continue;
        }
        const verdict = this.paper.evaluate(signal);
        if (!verdict.ok) {
          this.blockReasons.set(signal.symbol, verdict.reason);
          continue;
        }
        if (this.paper.open(signal, 'auto')) {
          this.audio.execution(signal.side, signal.symbol);
          this.blockReasons.delete(signal.symbol);
        }
      }

      const activeCount = this.radar.active.size;
      const liveSignals = [...this.signals.values()].filter(sg => sg.side !== 'WAIT').length;
      this.ignitionSummary = ignitionSummaryText({
        targets: targets.length,
        klineFails,
        blocked: this.blockReasons.size,
        live: liveSignals,
        positions: this.paper.state.paperPositions.length
      });
      $('#statusText').textContent = `${this.radar.meta.source} • ${this.radar.meta.universe} نماد تحت پایش • ${activeCount} کشف‌شده • ${this.ignitionSummary}`;
      this.view.renderAll();
    } catch (error) {
      // 🛡 خطای اسکن هرگز رادار را خاموش نمی‌کند: ثبت + نمایش + رندر — اسکن بعدی ادامه می‌یابد
      this.logger.info('SCAN ERROR', { error: error.message });
      const st = document.getElementById('statusText');
      if (st) st.textContent = `⚠️ خطای اسکن: ${error.message} — اسکن ادامه می‌یابد`;
      try { this.view.renderAll(); } catch { /* رندر حداقلی */ }
    } finally {
      this.scanInFlight = false;
    }
  }

  // پل یک‌طرفه اختیاری: انتشار نمادهای داغ برای اتوتریدر (فقط اگر روشن باشد)
  publishBridge() {
    if (String(this.settings.value.bridgePublish) !== 'true') return;
    const payload = {
      symbols: [...this.radar.active.values()].filter(r => r.side !== 'WATCH').map(r => r.symbol),
      active: [...this.radar.active.values()].map(r => ({ symbol: r.symbol, side: r.side, changePct: r.changePct }))
    };
    fetch('/api/hot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    }).catch(() => {});
  }

  schedule() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    if ($('#autoScanToggle')?.checked ?? true) {
      const seconds = Math.max(3, Number(this.settings.value.scanIntervalSec) || 8);
      this.timer = setInterval(() => this.scan(), seconds * 1000);
    }
  }

  killAll() {
    for (const position of [...this.paper.state.paperPositions]) {
      const market = this.marketData.get(position.symbol);
      this.paper.close(position, market?.price || position.entry, 'kill-switch');
    }
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.view.renderAll();
  }

  async start() {
    this.view.bind();
    this.view.renderSettings();
    this.view.renderAll();
    this.schedule();
    this.logger.info('PUMP LAB START', { mode: this.radar.meta.source });
    await this.scan().catch(error => this.logger.info('INITIAL SCAN ERROR', { error: error.message }));
  }
}
