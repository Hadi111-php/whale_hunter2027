import { $, $$, escapeHtml, fmt, pct, toBool } from '../core/utils.js';
import { describeAge, tfLabel, tfMs as tfMsOf } from '../core/timeframe.js';
import { evaluateFormula, FORMULA_VARIABLES } from '../services/formula-engine.js';
import { ladderRollup } from '../services/performance-report.js';
import { SimpleGrid } from './grid-tools.js';
import { PriceChart } from './price-chart.js';

export class DashboardView {
  constructor(app) {
    this.app = app;
    this.chart = $('#priceChart') ? new PriceChart($('#priceChart')) : null;
  }

  activateTab(tabName) {
    $$('.tab, .panel').forEach(element => element.classList.remove('active'));
    const tab = $(`.tab[data-tab="${tabName}"]`);
    const panel = $(`#${tabName}`);
    if (tab) tab.classList.add('active');
    if (panel) panel.classList.add('active');
    if (tabName === 'dashboard') this.renderChart();
  }

  bind() {
    $$('.tab').forEach(button => {
      button.onclick = () => this.activateTab(button.dataset.tab);
    });
    $$('[data-tab-jump]').forEach(button => {
      button.onclick = () => this.activateTab(button.dataset.tabJump);
    });

    $('#refreshBtn').onclick = () => void this.app.scan();
    $('#autoScanToggle').onchange = () => this.app.schedule();

    // 🔊 سوییچ سریع هشدار صوتی (کلیک = تعامل کاربر → AudioContext هم unlock می‌شود)
    const audioBtn = $('#audioToggleBtn');
    if (audioBtn) {
      audioBtn.onclick = () => {
        const next = String(this.app.settings.value.audioAlerts) === 'true' ? 'false' : 'true';
        this.app.settings.save({ ...this.app.settings.value, audioAlerts: next });
        if (next === 'true') {
          this.app.audio.unlock();
          this.app.audio.preAlert(); // بازخورد فوری روشن شدن صدا
        }
        this.renderStats();
        this.app.logger.info('AUDIO ALERTS', { enabled: next === 'true' });
      };
    }
    const testAudioBtn = $('#testAudioBtn');
    if (testAudioBtn) {
      testAudioBtn.onclick = () => {
        this.app.audio.unlock();
        this.app.audio.preAlert();
        this.app.audio.execution('LONG', 'TEST');
        this.app.logger.info('AUDIO TEST', { chime: true, executionBeep: 'LONG' });
      };
    }
    // اولین تعامل کاربر در هر جای صفحه، AudioContext را از حالت suspended خارج می‌کند
    document.addEventListener('pointerdown', () => this.app.audio?.unlock?.(), { once: true });

    // Quick toggle between LIVE Bybit and MOCK Offline
    const modeBtn = $('#modeToggleBtn');
    if (modeBtn) {
      modeBtn.onclick = () => {
        const cur = this.app.settings.value.dataMode;
        const next = cur === 'live' ? 'mock-local' : 'live';
        this.app.settings.save({ ...this.app.settings.value, dataMode: next });
        this.app.rebuildServices();
        this.renderAll();
        void this.app.scan();
      };
    }
    // Quick Account Selector (حساب هادی / حساب پسر)
    const accountSelect = $('#accountSelector');
    if (accountSelect) {
      accountSelect.value = this.app.settings.value.activeAccount || 'hadi';
      accountSelect.onchange = (e) => {
        const acc = e.target.value;
        const newSettings = { ...this.app.settings.value, activeAccount: acc };
        this.app.settings.save(newSettings);
        this.app.rebuildServices();
        this.renderSettings();
        this.renderAll();
        void this.app.scan();
        alert(`👤 حساب فعال به [${acc === 'hadi' ? 'حساب داداش هادی' : 'حساب آقا پسر'}] تغییر یافت و سیگنال‌ها رفرش شدند.`);
      };
    }

    // 1-Click Save Full System JSON to Phone Downloads
    const saveFullBtn = $('#saveFullJsonBtn');
    if (saveFullBtn) {
      saveFullBtn.onclick = () => {
        const fullPayload = {
          exportedAt: new Date().toISOString(),
          activeAccount: this.app.settings.value.activeAccount || 'hadi',
          initialEquity: this.app.settings.value.paperInitialEquity,
          currentEquity: this.app.paper.state.paperEquity,
          feesPaid: this.app.paper.state.feesPaid,
          openPositions: this.app.paper.state.paperPositions,
          tradesHistory: this.app.paper.state.paperTrades,
          ladderRollup: ladderRollup(this.app.paper.state.paperTrades),
          settings: this.app.settings.value,
          signals: Array.from(this.app.signals.entries()).reduce((acc, [k, v]) => { acc[k] = v; return acc; }, {})
        };
        const raw = JSON.stringify(fullPayload, null, 2);
        const blob = new Blob([raw], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `trading_export_${this.app.settings.value.activeAccount || 'hadi'}_${Date.now()}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        alert('💾 فایل کامل JSON سیستم در پوشه Downloads گوشی/سیستم ذخیره شد!');
      };
    }

    $('#quickRiskProfile').onchange = event => this.app.applyRiskProfile(event.target.value);
    $('#chartSymbolSelect').onchange = () => this.renderChart();
    if ($('#netFishingSymbolSelect')) $('#netFishingSymbolSelect').onchange = () => this.renderNetFishing();
    if ($('#netFishingLayersSelect')) $('#netFishingLayersSelect').onchange = () => this.renderNetFishing();
    if ($('#redeployNetBtn')) {
      $('#redeployNetBtn').onclick = () => {
        this.renderNetFishing();
        alert('🕸️ تور ماهیگیری با موفقیت در قیمت فعلی مارکت پهن و به‌روزرسانی شد!');
      };
    }
    $('#paperAutoToggle').checked = toBool(this.app.settings.value.paperAutoDefault);
    if ($('#exportTradesJsonBtn')) {
      $('#exportTradesJsonBtn').onclick = async () => {
        const exportData = {
          exportedAt: new Date().toISOString(),
          initialEquity: this.app.settings.value.paperInitialEquity,
          currentEquity: this.app.paper.state.paperEquity,
          feesPaid: this.app.paper.state.feesPaid,
          openPositions: this.app.paper.state.paperPositions,
          tradesHistory: this.app.paper.state.paperTrades,
          ladderRollup: ladderRollup(this.app.paper.state.paperTrades),
          settings: this.app.settings.value
        };
        const raw = JSON.stringify(exportData, null, 2);
        try {
          await navigator.clipboard.writeText(raw);
          alert('✅ فایل JSON تمام معاملات با موفقیت کپی شد! می‌توانی آن را مستقیماً در چت Paste کنی تا با هم تحلیلش کنیم.');
        } catch {
          prompt('JSON تاریخچه معاملات (کپی کن و در چت بفرست):', raw);
        }
      };
    }
    $('#closeAllPaperBtn').onclick = () => this.app.closeAllPaper();
    $('#resetPaperBtn').onclick = () => {
      if (confirm('ریست کامل حساب مجازی و تاریخچه؟')) this.app.resetPaper();
    };
    $('#panicBtn').onclick = () => {
      // 1. Emergency kill real orders
      this.app.real.kill();
      if ($('#realAutoToggle')) $('#realAutoToggle').checked = false;
      
      // 2. Stop auto-scanner timer completely
      if ($('#autoScanToggle')) $('#autoScanToggle').checked = false;
      if (this.app.timer) clearInterval(this.app.timer);
      this.app.timer = null;
      
      // 3. Close all open positions immediately
      this.app.closeAllPaper();
      
      // 4. Update status banner
      $('#statusText').textContent = '🛑 KILL SWITCH فعال شد — اسکن متوقف و تمام پوزیشن‌ها بسته شدند';
      this.renderAll();
      alert('🛑 کلید قطع اضطراری (Kill Switch) فعال شد:\n• تمام معاملات بسته شدند\n• اسکن خودکار کاملاً متوقف شد\n• سیستم در حالت امن فریز شد.');
    };
    $('#realAutoToggle').onchange = event => {
      if (event.target.checked && this.app.settings.value.dataMode !== 'live') {
        alert('ارسال واقعی فقط وقتی مجاز است که Data Mode روی LIVE (دیتای زنده) باشد.');
        event.target.checked = false;
        return;
      }
      if (event.target.checked && $('#confirmText').value.trim() !== 'I ACCEPT RISK') {
        alert('برای فعال‌سازی عبارت دقیق I ACCEPT RISK را وارد کن.');
        event.target.checked = false;
        return;
      }
      if (event.target.checked) $('#paperAutoToggle').checked = true;
      this.app.real.setEnabled(event.target.checked);
      this.renderAll();
    };
    $('#settingsForm').onsubmit = event => this.saveSettings(event);

    // 🧮 تست زندهٔ فرمول پارامتریک روی آخرین دیتای واقعی اسکن‌شده
    const formulaTestBtn = $('#formulaTestBtn');
    if (formulaTestBtn) {
      formulaTestBtn.onclick = () => {
        const form = $('#settingsForm');
        const code = form.elements.customFormula?.value || '';
        const resultEl = $('#formulaTestResult');
        const signal = [...this.app.signals.values()].find(entry => entry.formulaVars);
        if (!signal) {
          resultEl.textContent = '⏳ هنوز دیتای اسکن‌شده‌ای نیست؛ اول یک اسکن بزن';
          return;
        }
        const verdict = evaluateFormula(code, signal.formulaVars);
        resultEl.textContent = verdict.ok
          ? `✅ ${signal.symbol} → نتیجه = ${verdict.value.toFixed(4)} ${verdict.value > 0 ? '(ورود آزاد ✓)' : '(ورود مسدود ✗)'}`
          : `❌ ${signal.symbol} → ${verdict.error}`;
        resultEl.style.color = verdict.ok ? '#10b981' : '#ef4444';
      };
    }
    const formulaVarsList = $('#formulaVarsList');
    if (formulaVarsList) {
      formulaVarsList.innerHTML = FORMULA_VARIABLES
        .map(variable => `<span style="display:block; margin-bottom:2px;"><code>${variable.name}</code> — ${variable.desc}</span>`)
        .join('');
    }
    $('#settingsForm').elements.riskProfile.onchange = event => this.app.applyRiskProfile(event.target.value);
    $('#defaultsBtn').onclick = () => {
      if (!confirm('Settings به حالت امن پیش‌فرض برگردد؟')) return;
      this.app.settings.reset();
      this.app.rebuildServices();
      this.renderSettings();
      this.app.schedule();
      this.renderAll();
      void this.app.scan();
    };
    $('#exportSettingsBtn').onclick = async () => {
      const raw = JSON.stringify(this.app.settings.value, null, 2);
      try {
        await navigator.clipboard.writeText(raw);
        alert('JSON تنظیمات کپی شد');
      } catch {
        prompt('JSON تنظیمات', raw);
      }
    };
    $('#importSettingsBtn').onclick = () => {
      const raw = prompt('JSON Settings');
      if (!raw) return;
      try {
        const parsed = JSON.parse(raw);
        this.app.settings.save(parsed);
        this.app.rebuildServices();
        this.renderSettings();
        this.app.schedule();
        this.renderAll();
        void this.app.scan();
      } catch {
        alert('JSON نامعتبر است');
      }
    };
    $('#clearLogsBtn').onclick = () => this.app.logger.clear();
    this.app.logger.onChange(entries => {
      $('#logBox').textContent = entries.map(entry => this.app.logger.format(entry)).join('\n');
    });
    // 📥 دانلود لاگ‌های ساختاریافته به صورت JSONL برای کالبدشکافی آفلاین
    const jsonlBtn = $('#downloadLogsJsonlBtn');
    if (jsonlBtn) {
      jsonlBtn.onclick = () => {
        const account = this.app.settings.value.activeAccount || 'hadi';
        const blob = new Blob([this.app.logger.toJsonl() || ''], { type: 'application/x-ndjson' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `trading_logs_${account}_${Date.now()}.jsonl`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        this.app.logger.info('LOGS EXPORTED (JSONL)', { account, entries: this.app.logger.lines.length });
      };
    }
  }

  saveSettings(event) {
    event.preventDefault();
    const form = event.target;
    const old = this.app.settings.value;
    const next = { ...old };

    for (const key of Object.keys(old)) {
      const element = form.elements[key];
      if (!element) continue;
      if (key === 'symbols') {
        const raw = element.value.replace(/[\r\n]+/g, ',').split(',');
        next[key] = raw.map(v => v.trim().toUpperCase()).filter(Boolean);
        if (next[key].length === 0) next[key] = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'];
      } else if (key === 'symbolMap') {
        try {
          const val = element.value.trim();
          next[key] = val ? JSON.parse(val) : {};
        } catch {
          next[key] = {};
        }
      } else if (typeof old[key] === 'number') {
        const number = Number(element.value);
        if (Number.isFinite(number)) {
          next[key] = number;
        }
      } else {
        next[key] = element.value || '';
      }
    }

    // همگام‌سازی حساب فعال با هدر
    const accSel = $('#accountSelector');
    if (accSel && accSel.value) {
      next.activeAccount = accSel.value;
    }

    this.app.settings.save(next);
    this.app.rebuildServices();
    this.app.schedule();
    this.app.logger.info('SETTINGS SAVED', { activeAccount: next.activeAccount, dataMode: next.dataMode, symbols: next.symbols.length });
    this.renderSettings();
    this.renderAll();
    void this.app.scan();
    alert('✅ تنظیمات با موفقیت ذخیره و روی بازار اعمال شد!');
  }

  renderSettings() {
    const form = $('#settingsForm');
    const settings = this.app.settings.value;
    for (const [key, value] of Object.entries(settings)) {
      const element = form.elements[key];
      if (!element) continue;
      element.value = key === 'symbols'
        ? value.join(',')
        : key === 'symbolMap'
          ? JSON.stringify(value, null, 2)
          : value;
    }
  }

  renderStats() {
    const paper = this.app.paper;
    let equityDelta = 0;
    let openNet = 0;
    for (const position of paper.state.paperPositions) {
      const mark = this.app.prices.get(position.symbol);
      if (!Number.isFinite(Number(mark))) continue;
      equityDelta += paper.markToMarketDelta(position, mark);
      openNet += paper.netPnl(position, mark);
    }

    const totalEquity = Number(paper.state.paperEquity) + equityDelta;
    const profile = this.app.settings.value.riskProfile || 'medium';
    const report = this.app.performance.summarize(paper.state, this.app.settings.value.paperInitialEquity, profile);
    const closedWinRate = report.count ? `${report.winRate.toFixed(1)}% (${report.wins}/${report.count})` : '--';
    const realizedNet = report.netPnl;

    $('#paperEquity').textContent = `${fmt(totalEquity, 2)} USDT`;
    
    // سود و ضرر شناور با رنگ زنده سبز و قرمز و علامت مثبت/منفی
    const openPnlEl = $('#openPnl');
    if (openNet > 0.001) {
      openPnlEl.textContent = `+${fmt(openNet, 3)} USDT`;
      openPnlEl.style.color = '#10b981';
      openPnlEl.style.fontWeight = 'bold';
    } else if (openNet < -0.001) {
      openPnlEl.textContent = `${fmt(openNet, 3)} USDT`;
      openPnlEl.style.color = '#ef4444';
      openPnlEl.style.fontWeight = 'bold';
    } else {
      openPnlEl.textContent = `0.000 USDT`;
      openPnlEl.style.color = '#94a3b8';
      openPnlEl.style.fontWeight = 'normal';
    }

    $('#winRate').textContent = closedWinRate;
    $('#feesPaid').textContent = `${fmt(paper.state.feesPaid, 3)} USDT`;
    $('#closedTrades').textContent = `${report.count} • ${fmt(realizedNet, 3)} USDT`;
    $('#reportScope').textContent = `پروفایل ${profile} • معاملات بسته‌شده Paper، خالص بعد از کارمزد`;
    $('#dashReportScope').textContent = `پروفایل ${profile} • معاملات بسته‌شده Paper، خالص بعد از کارمزد`;

    $('#reportCount').textContent = report.count ? `${report.count} (${report.wins}W/${report.losses}L)` : '--';
    $('#reportWinRate').textContent = report.count ? `${report.winRate.toFixed(1)}%` : '--';
    $('#reportProfitFactor').textContent = Number.isFinite(report.profitFactor) ? report.profitFactor.toFixed(2) : report.grossProfit > 0 ? '∞' : '--';
    $('#reportExpectancy').textContent = report.expectancy === null ? '--' : `${fmt(report.expectancy, 3)} USDT`;
    $('#reportNetPnl').textContent = `${fmt(report.netPnl, 3)} USDT`;
    $('#reportFees').textContent = `${fmt(report.fees, 3)} USDT`;
    $('#reportDrawdown').textContent = report.count ? `${fmt(report.maxDrawdown, 3)} USDT (${report.maxDrawdownPct.toFixed(2)}%)` : '--';
    $('#reportHold').textContent = report.averageHoldSec === null ? '--' : `${Math.round(report.averageHoldSec)}s`;
    $('#dashReportWinRate').textContent = report.count ? `${report.winRate.toFixed(1)}%` : '--';
    const sv = this.app.signalValidator?.stats();
    const accEl = $('#dashReportSignalAcc');
    if (accEl) accEl.textContent = sv?.settled ? `${sv.accuracyPct}% (${sv.settled})` : '--';
    $('#dashReportNetPnl').textContent = `${fmt(report.netPnl, 3)} USDT`;
    $('#dashReportFees').textContent = `${fmt(report.fees, 3)} USDT`;
    $('#dashReportProfitFactor').textContent = Number.isFinite(report.profitFactor) ? report.profitFactor.toFixed(2) : report.grossProfit > 0 ? '∞' : '--';
    $('#dashReportDrawdown').textContent = report.count ? `${fmt(report.maxDrawdown, 3)} USDT` : '--';
    $('#dashReportCount').textContent = report.count ? `${report.count} (${report.wins}W/${report.losses}L)` : '--';
    $('#quickRiskProfile').value = this.app.settings.value.riskProfile;

    const mode = this.app.modeLabel();
    const badge = $('#dataSourceBadge');
    const modeBtn = $('#modeToggleBtn');
    const isLive = this.app.settings.value.dataMode === 'live';
    
    if (modeBtn) {
      modeBtn.textContent = isLive ? '🟢 دیتای زنده Bybit' : '🟠 شبیه‌ساز آفلاین (Mock)';
      modeBtn.style.borderColor = isLive ? '#10b981' : '#f59e0b';
      modeBtn.style.color = isLive ? '#10b981' : '#f59e0b';
    }

    const audioBtn = $('#audioToggleBtn');
    if (audioBtn) {
      const audioOn = String(this.app.settings.value.audioAlerts) === 'true';
      audioBtn.textContent = audioOn ? '🔊 صدا: روشن' : '🔇 صدا: خاموش';
      audioBtn.style.borderColor = audioOn ? '#10b981' : '#8ca3bd';
      audioBtn.style.color = audioOn ? '#10b981' : '#8ca3bd';
    }

    const expected = this.app.settings.value.symbols.length;
    const received = this.app.signals.size;
    const healthyLive = mode === 'LIVE' && received === 0 ? 'error' : mode === 'LIVE' ? 'live' : 'test';
    badge.textContent = mode === 'LIVE' ? `${mode} • ${received}/${expected}` : mode;
    badge.className = `badge ${healthyLive}`;
    $('#realModeBadge').textContent = this.app.real.enabled ? 'ON' : 'OFF';
    $('#realModeBadge').className = `badge ${this.app.real.enabled ? 'on' : 'off'}`;
  }

  renderDataFeed() {
    const symbols = this.app.settings.value.symbols;
    const received = this.app.marketData.size;
    const feedHealth = $('#feedHealth');
    const mode = this.app.modeLabel();
    // تفکیک منبع‌های واقعی: هر دیتا از کدام صرافی آمده (BYBIT/OKX/BINANCE)
    const srcCounts = {};
    for (const market of this.app.marketData.values()) {
      const key = String(market.source || '?').split(' ')[0];
      srcCounts[key] = (srcCounts[key] || 0) + 1;
    }
    const srcText = Object.entries(srcCounts).map(([k, v]) => `${k}×${v}`).join(' ') || '—';
    feedHealth.textContent = `${mode} • ${received}/${symbols.length} • ${srcText}`;
    feedHealth.className = `badge ${mode === 'LIVE' && received === 0 ? 'error' : mode === 'LIVE' ? 'live' : 'test'}`;

    $('#dataFeedRows').innerHTML = symbols.map(symbol => {
      const market = this.app.marketData.get(symbol);
      const error = this.app.dataErrors.get(symbol);
      if (!market) {
        return `<tr>
          <td>${escapeHtml(symbol)}</td><td>--</td><td>--</td><td>--</td><td>--</td><td>--</td>
          <td class="pnl-neg">${escapeHtml(error || 'NO DATA')}</td>
        </tr>`;
      }
      const age = Math.max(0, (Date.now() - Number(market.receivedAt || Date.now())) / 1000);
      const candleTime = market.lastCandle?.ts ? new Date(market.lastCandle.ts).toLocaleTimeString() : '--';
      return `<tr>
        <td>${escapeHtml(symbol)}</td>
        <td class="${String(market.source).includes('LIVE') ? 'source-live' : 'source-test'}">${escapeHtml(market.source)}</td>
        <td>${fmt(market.price, market.price > 10 ? 2 : 6)}</td>
        <td>${escapeHtml(candleTime)}</td>
        <td>${market.candles.length}</td>
        <td>${age.toFixed(1)}s</td>
        <td class="pnl-pos">OK</td>
      </tr>`;
    }).join('') || '<tr><td colspan="7">نمادی برای دریافت دیتا تنظیم نشده</td></tr>';
  }

  renderChart() {
    const select = $('#chartSymbolSelect');
    const symbols = this.app.settings.value.symbols;
    const previous = select.value;
    select.innerHTML = '';
    symbols.forEach(symbol => {
      const option = document.createElement('option');
      option.value = symbol;
      option.textContent = symbol;
      select.appendChild(option);
    });
    const symbol = symbols.includes(previous) ? previous : symbols[0];
    if (symbol) select.value = symbol;
    const market = symbol ? this.app.marketData.get(symbol) : null;
    const signal = symbol ? this.app.signals.get(symbol) : null;

    if (!market) {
      this.chart?.clear(this.app.dataErrors.get(symbol) || 'منتظر دیتای معتبر Bybit...');
      $('#chartSymbolMeta').textContent = symbol ? `${symbol} • DATA ERROR / منتظر دیتا` : 'نمادی انتخاب نشده';
      $('#dataInputJson').textContent = JSON.stringify({ symbol, error: this.app.dataErrors.get(symbol) || 'no data' }, null, 2);
      return;
    }

    const tradesForChart = (this.app.paper?.state?.paperTrades || [])
      .filter(trade => trade.symbol === symbol)
      .slice(0, 80);
    this.chart?.setData(market, signal, tradesForChart);
    const age = Math.max(0, (Date.now() - Number(market.receivedAt || Date.now())) / 1000).toFixed(1);
    $('#chartSymbolMeta').textContent = `${market.source} • Ticker ${fmt(market.price, market.price > 10 ? 2 : 6)} • age ${age}s`;
    $('#dataInputJson').textContent = JSON.stringify({
      source: market.source,
      symbol: market.symbol,
      ticker: market.tickerRaw,
      exchangeTime: market.exchangeTime ? new Date(market.exchangeTime).toISOString() : null,
      receivedAt: new Date(market.receivedAt).toISOString(),
      currentCandleIsOpen: market.currentCandleIsOpen,
      requestInfo: market.requestInfo,
      candlesCount: market.candles.length,
      lastFiveClosedCandles: market.candles.slice(-5)
    }, null, 2);
  }

  renderDashboardPositions() {
    const paper = this.app.paper;
    const rows = paper.state.paperPositions.map(position => {
      const rawMark = this.app.prices.get(position.symbol);
      const hasMark = Number.isFinite(Number(rawMark));
      const pnl = hasMark ? paper.netPnl(position, rawMark) : Number.NaN;
      return `<tr>
        <td>${escapeHtml(position.symbol)}</td>
        <td>${escapeHtml(position.side)}</td>
        <td>${fmt(position.entry)}</td>
        <td>${hasMark ? fmt(rawMark) : '--'}</td>
        <td>${fmt(position.stop)} / ${fmt(position.take)}</td>
        <td class="${hasMark ? (pnl >= 0 ? 'pnl-pos' : 'pnl-neg') : 'muted'}">${fmt(pnl, 3)}</td>
      </tr>`;
    }).join('');
    $('#dashboardPaperPositions').innerHTML = rows || '<tr><td colspan="6">پوزیشن مجازی باز نداریم</td></tr>';
  }

  renderMarkets() {
    const grid = $('#marketGrid');
    const template = $('#marketCardTpl');
    grid.innerHTML = '';

    for (const symbol of this.app.settings.value.symbols) {
      const signal = this.app.signals.get(symbol);
      const node = template.content.cloneNode(true);
      $('h3', node).textContent = symbol;
      const button = $('.paperNow', node);
      const dataState = $('.data-state', node);
      const side = $('.side', node);

      if (!signal) {
        $('.price', node).textContent = '--';
        $('.move', node).textContent = '--';
        $('.vol', node).textContent = '--';
        $('.atr', node).textContent = '--';
        side.textContent = 'WAIT';
        side.className = 'side flat';
        $('.score', node).textContent = '--';
        $('.why', node).textContent = 'برای این نماد دیتای معتبر دریافت نشد؛ سیگنال ساخته نشد.';
        const noDataBlock = $('.block-reason', node);
        if (noDataBlock) {
          noDataBlock.textContent = '🚫 علت عدم ورود: دیتای زنده صرافی دریافت نشد (DATA ERROR)';
          noDataBlock.className = 'block-reason';
        }
        const noDataMicro = $('.micro-tag', node);
        if (noDataMicro) noDataMicro.textContent = '—';
        $('.trade-plan', node).textContent = 'No data / no order';
        dataState.textContent = `DATA ERROR: ${this.app.dataErrors.get(symbol) || 'در انتظار دیتا'}`;
        dataState.className = 'data-state error';
        button.disabled = true;
        grid.appendChild(node);
        continue;
      }

      const decimals = signal.price > 10 ? 2 : 6;
      $('.price', node).textContent = fmt(signal.price, decimals);
      $('.move', node).textContent = pct(signal.movePct);
      $('.vol', node).textContent = `${signal.volX.toFixed(2)}x`;
      $('.atr', node).textContent = pct(signal.atrPct);
      if ($('.rsi-tag', node)) {
        const rsiVal = signal.rsi !== undefined ? signal.rsi.toFixed(0) : '--';
        $('.rsi-tag', node).textContent = rsiVal;
        if (signal.rsi < 35) $('.rsi-tag', node).style.color = '#10b981';
        else if (signal.rsi > 65) $('.rsi-tag', node).style.color = '#ef4444';
        else $('.rsi-tag', node).style.color = '#38bdf8';
      }
      // 🧩 چیپ تاییدیه هم‌جهتی کندل‌های ریز (Micro-Candle Streak)
      const microTag = $('.micro-tag', node);
      if (microTag) {
        microTag.textContent = signal.microTag || '—';
        if (signal.microDirection === 'LONG') microTag.style.color = '#10b981';
        else if (signal.microDirection === 'SHORT') microTag.style.color = '#ef4444';
        else microTag.style.color = '#8ca3bd';
        if (signal.microTag === 'NO DATA') microTag.style.color = '#f59e0b';
      }
      // 🚫 علت شفاف باز نشدن معامله خودکار روی کارت هر ارز
      const blockEl = $('.block-reason', node);
      if (blockEl) {
        const hasOpen = this.app.paper.state.paperPositions.some(position => position.symbol === symbol);
        const reason = this.app.blockReasons.get(symbol);
        if (hasOpen) {
          const pos = this.app.paper.state.paperPositions.find(item => item.symbol === symbol);
          const entryTf = pos?.timeframe ? tfLabel(pos.timeframe) : null;
          const mismatch = pos && pos.tfMs && tfMsOf(this.app.settings.value.timeframe) !== Number(pos.tfMs);
          blockEl.textContent = mismatch
            ? `🔒 ورود روی ${entryTf} • تنظیمات الان ${tfLabel(this.app.settings.value.timeframe)} است → خروج‌های سیگنالی قفل؛ فقط SL/بریک‌ایون/MaxHold فعال`
            : `✅ پوزیشن باز (ورود روی ${entryTf || '—'}) — SL/ترلینگ/خروج هیبریدی با همان تایم‌فریم فعال`;
          blockEl.className = `block-reason ${mismatch ? '' : 'ok'}`;
        } else if (reason) {
          blockEl.textContent = `🚫 علت عدم ورود خودکار: ${reason}`;
          blockEl.className = 'block-reason';
        } else {
          blockEl.textContent = '';
          blockEl.className = 'block-reason hidden';
        }
      }
      side.textContent = signal.side;
      side.className = `side ${signal.side === 'LONG' ? 'long' : signal.side === 'SHORT' ? 'short' : 'flat'}`;
      $('meter', node).value = signal.score;
      $('.score', node).textContent = `${signal.score}%`;
      $('.why', node).textContent = signal.why;
      // ⏱ وضعیت زمانی کندل: تایم‌فریم + چند وقت پیش بسته شد + سلامت هم‌ترازی
      const ageMs = Number.isFinite(Number(signal.candleAgeMs)) ? signal.candleAgeMs : null;
      const tfText = this.app.timeframeLabel();
      const ageText = ageMs === null ? '' : ` • کندل بسته: ${describeAge(ageMs)}`;
      const staleMark = signal.stale ? ' ⚠ کهنه' : '';
      dataState.textContent = `${signal.source} • ${tfText}${ageText}${staleMark}`;
      dataState.className = `data-state ${signal.stale ? 'error' : String(signal.source).includes('LIVE') ? 'live' : 'test'}`;
      $('.trade-plan', node).innerHTML = signal.side === 'WAIT'
        ? 'پلن فعال ندارد؛ امتیاز به حداقل نرسیده.'
        : `Entry ${fmt(signal.entry, decimals)} | SL ${fmt(signal.stop, decimals)} | TP ${fmt(signal.take, decimals)}<br>Notional ${fmt(signal.notional, 2)} | Round fee≈${fmt(signal.fee, 3)} | Risk≈${fmt(signal.risk, 3)} | Reward≈${fmt(signal.reward, 3)}`;
      button.disabled = signal.side === 'WAIT';
      button.onclick = () => {
        if (this.app.paper.open(signal, 'manual', true)) this.renderAll();
      };
      grid.appendChild(node);
    }
  }

  renderTables() {
    const paper = this.app.paper;
    const prices = this.app.prices;
    const realOrders = paper.state.realOrders;

    // 🗂 دیتاگرید پوزیشن‌ها — سورت با کلیک روی سرستون‌ها
    if (!this.positionsGrid) {
      this.positionsGrid = new SimpleGrid({
        tbodyId: 'paperPositions',
        columns: [
          { key: 'symbol', label: 'نماد', type: 'text' },
          { key: 'side', label: 'سمت', type: 'text' },
          { key: 'entry', label: 'ورود', type: 'number' },
          { key: 'mark', label: 'مارک', type: 'number' },
          { key: 'qty', label: 'سایز', type: 'number' },
          { key: 'stop', label: 'SL/TP', type: 'number' },
          { key: 'fees', label: 'Fee تا الان', type: 'number' },
          { key: 'pnl', label: 'PnL خالص', type: 'number' },
          { key: 'actions', label: '', type: 'text', sortable: false }
        ],
        initialSort: { key: 'pnl', dir: -1 },
        getData: () => paper.state.paperPositions.map(position => {
          const rawMark = prices.get(position.symbol);
          const hasMark = Number.isFinite(Number(rawMark));
          return {
            id: position.id, symbol: position.symbol, side: position.side,
            entry: Number(position.entry), mark: hasMark ? Number(rawMark) : Number.NaN,
            qty: Number(position.qty), stop: Number(position.stop), take: Number(position.take),
            fees: hasMark ? Number(position.openFee || 0) + paper.closeFee(position, rawMark) : Number(position.openFee || 0),
            pnl: hasMark ? paper.netPnl(position, rawMark) : Number.NaN
          };
        }),
        renderRow: row => `<tr>
        <td>${escapeHtml(row.symbol)}</td>
        <td>${escapeHtml(row.side)}</td>
        <td>${fmt(row.entry)}</td>
        <td>${Number.isFinite(row.mark) ? fmt(row.mark) : '--'}</td>
        <td>${fmt(row.qty, 6)}</td>
        <td>${fmt(row.stop)} / ${fmt(row.take)}</td>
        <td>${fmt(row.fees, 3)}</td>
        <td class="${Number.isFinite(row.pnl) ? (row.pnl >= 0 ? 'pnl-pos' : 'pnl-neg') : 'muted'}">${Number.isFinite(row.pnl) ? fmt(row.pnl, 3) : '--'}</td>
        <td><button class="small ghost" data-close="${escapeHtml(row.id)}">Close</button></td>
      </tr>`,
        emptyHtml: '<tr><td colspan="9">پوزیشن مجازی باز نداریم</td></tr>'
      });
    }
    this.positionsGrid.render();

    $$('[data-close]').forEach(button => {
      button.onclick = () => {
        const position = positions.find(item => item.id === button.dataset.close);
        if (position) paper.close(position, prices.get(position.symbol) || position.entry, 'manual');
        this.renderAll();
      };
    });

    // 🗂 دیتاگرید معاملات — فیلتر (جست‌وجو/سمت/دلیل) + سورت روی همهٔ ستون‌ها
    if (!this.tradesGrid) {
      this.tradesGrid = new SimpleGrid({
        tbodyId: 'paperTrades',
        columns: [
          { key: 'time', label: 'زمان', type: 'time' },
          { key: 'symbol', label: 'نماد', type: 'text' },
          { key: 'side', label: 'سمت', type: 'text' },
          { key: 'riskProfile', label: 'Risk', type: 'text' },
          { key: 'entry', label: 'ورود / خروج', type: 'number' },
          { key: 'grossPnl', label: 'Gross', type: 'number' },
          { key: 'fees', label: 'Fees', type: 'number' },
          { key: 'pnl', label: 'Net PnL', type: 'number' },
          { key: 'reason', label: 'دلیل / مدت', type: 'text' }
        ],
        initialSort: { key: 'time', dir: -1 },
        filters: [
          { id: 'q', label: '🔍 جست‌وجو (نماد/دلیل)', type: 'text', match: (row, val) => `${row.symbol} ${row.reason}`.toLowerCase().includes(val.toLowerCase()) },
          { id: 'side', label: 'سمت', type: 'select', options: ['LONG', 'SHORT'], match: (row, val) => row.side === val },
          { id: 'reason', label: 'دلیل', type: 'select', options: () => [...new Set((paper.state.paperTrades || []).map(t => t.reason).filter(Boolean))].slice(0, 30), match: (row, val) => row.reason === val }
        ],
        getData: () => paper.state.paperTrades,
        renderRow: trade => `<tr>
        <td>${escapeHtml(new Date(trade.time).toLocaleString())}</td>
        <td>${escapeHtml(trade.symbol)}</td>
        <td>${escapeHtml(trade.side)}</td>
        <td>${escapeHtml(trade.riskProfile || 'legacy')}</td>
        <td>${fmt(trade.entry)} / ${fmt(trade.exit)}</td>
        <td>${fmt(trade.grossPnl, 3)}</td>
        <td>${fmt(trade.fees, 3)}</td>
        <td class="${Number(trade.pnl) >= 0 ? 'pnl-pos' : 'pnl-neg'}">${fmt(trade.pnl, 3)}</td>
        <td>${escapeHtml(trade.reason)} • ${fmt(trade.durationSec, 0)}s</td>
      </tr>`,
        emptyHtml: '<tr><td colspan="9">هنوز معامله مجازی بسته‌شده‌ای ثبت نشده (یا فیلتر همه را حذف کرده)</td></tr>'
      });
    }
    this.tradesGrid.render();

    $('#realOrders').innerHTML = realOrders.map(order => `<tr>
      <td>${escapeHtml(new Date(order.time).toLocaleString())}</td>
      <td>${escapeHtml(order.symbol)}</td>
      <td>${escapeHtml(order.side)}</td>
      <td>${escapeHtml(order.status)}</td>
      <td>${escapeHtml(order.message)}</td>
    </tr>`).join('') || '<tr><td colspan="5">ارسال واقعی نداریم؛ Real به‌صورت پیش‌فرض OFF است</td></tr>';
  }

  renderNetFishing() {
    const symbolSelect = $('#netFishingSymbolSelect');
    const layersSelect = $('#netFishingLayersSelect');
    const symbol = symbolSelect ? symbolSelect.value : 'BTCUSDT';
    const layers = layersSelect ? parseInt(layersSelect.value) : 5;

    const signal = this.app.signals.get(symbol);
    const price = signal ? signal.price : (this.app.prices.get(symbol) || 64000);
    const atr = signal ? signal.atr : (price * 0.004);

    $('#netCenterPrice').textContent = `${fmt(price, price > 10 ? 2 : 6)} USDT`;
    $('#netHarvestedCount').textContent = `${this.app.paper.state.paperTrades.filter(t => t.symbol === symbol).length} صید`;

    const sentiment = (signal && signal.rsi < 35) ? '🟢 تله شورت / فنر صعودی' : (signal && signal.rsi > 65) ? '🔴 تله لانگ / ریزشی' : '⚪ تعادل (NEUTRAL)';
    $('#netWhaleSentiment').textContent = sentiment;
    $('#netNodesRatio').textContent = `${layers} خرید / ${layers} فروش`;

    const stepDist = atr * 0.8;
    const capitalPerNode = (Number(this.app.settings.value.paperInitialEquity || 1000) * 0.8) / layers;
    const leverage = Number(this.app.settings.value.leverage || 5);

    let rows = '';
    // لایه‌های فروش (بالای قیمت)
    for (let i = layers; i >= 1; i--) {
      const targetP = price + (i * stepDist);
      const tp = targetP - (stepDist * 1.35);
      const sl = targetP + (stepDist * 2.0);
      rows += `<tr style="background:rgba(239, 68, 68, 0.08);">
        <td style="color:#ef4444; font-weight:bold;">🔴 SELL_NET_${i}</td>
        <td><span class="badge" style="background:#ef4444; color:#fff;">SHORT</span></td>
        <td style="font-weight:bold;">${fmt(targetP, price > 10 ? 2 : 6)}</td>
        <td>${fmt(capitalPerNode * leverage, 1)}$</td>
        <td style="color:#10b981;">${fmt(tp, price > 10 ? 2 : 6)}</td>
        <td style="color:#ef4444;">${fmt(sl, price > 10 ? 2 : 6)}</td>
        <td><span class="muted">در انتظار تیک</span></td>
      </tr>`;
    }
    // خط قیمت مبنا
    rows += `<tr style="background:rgba(56, 189, 248, 0.18); border-top:2px solid #38bdf8; border-bottom:2px solid #38bdf8;">
      <td colspan="2" style="color:#38bdf8; font-weight:bold;">📍 قیمت فعلی مارکت</td>
      <td colspan="5" style="color:#38bdf8; font-weight:bold; font-size:1.05rem;">${fmt(price, price > 10 ? 2 : 6)} USDT (مرکز تور)</td>
    </tr>`;
    // لایه‌های خرید (زیر قیمت)
    for (let i = 1; i <= layers; i++) {
      const targetP = price - (i * stepDist);
      const tp = targetP + (stepDist * 1.35);
      const sl = targetP - (stepDist * 2.0);
      rows += `<tr style="background:rgba(16, 185, 129, 0.08);">
        <td style="color:#10b981; font-weight:bold;">🟢 BUY_NET_${i}</td>
        <td><span class="badge" style="background:#10b981; color:#fff;">LONG</span></td>
        <td style="font-weight:bold;">${fmt(targetP, price > 10 ? 2 : 6)}</td>
        <td>${fmt(capitalPerNode * leverage, 1)}$</td>
        <td style="color:#10b981;">${fmt(tp, price > 10 ? 2 : 6)}</td>
        <td style="color:#ef4444;">${fmt(sl, price > 10 ? 2 : 6)}</td>
        <td><span class="muted">در انتظار تیک</span></td>
      </tr>`;
    }

    const container = $('#netFishingNodesRows');
    if (container) container.innerHTML = rows;
  }

  renderAll() {
    this.renderStats();
    this.renderDataFeed();
    this.renderChart();
    this.renderDashboardPositions();
    this.renderMarkets();
    this.renderTables();
    this.renderNetFishing();
  }
}
