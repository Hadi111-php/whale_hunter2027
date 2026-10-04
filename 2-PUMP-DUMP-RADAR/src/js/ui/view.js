import { $, $$, escapeHtml, fmt, tfLabel, toBool } from '../core/utils.js';
import { SimpleGrid } from './grid-tools.js';

export class DashboardView {
  constructor(app) {
    this.app = app;
  }

  bind() {
    $$('.tab').forEach(button => {
      button.onclick = () => {
        $$('.tab, .panel').forEach(el => el.classList.remove('active'));
        button.classList.add('active');
        $(`#${button.dataset.tab}`)?.classList.add('active');
      };
    });

    $('#refreshBtn').onclick = () => void this.app.scan();
    $('#autoScanToggle').onchange = () => this.app.schedule();

    const audioBtn = $('#audioToggleBtn');
    if (audioBtn) {
      audioBtn.onclick = () => {
        const next = String(this.app.settings.value.audioAlerts) === 'true' ? 'false' : 'true';
        this.app.settings.save({ ...this.app.settings.value, audioAlerts: next });
        if (next === 'true') {
          this.app.audio.unlock();
          this.app.audio.radarAlert('PUMP');
        }
        this.renderStats();
      };
    }
    document.addEventListener('pointerdown', () => this.app.audio?.unlock?.(), { once: true });

    $('#panicBtn').onclick = () => {
      this.app.killAll();
      $('#statusText').textContent = '🛑 Kill Switch فعال — همه پوزیشن‌ها بسته و اسکن متوقف شد';
    };
    $('#resetPaperBtn').onclick = () => {
      if (confirm('ریست کامل حساب مجازی پمپ/دامپ؟')) {
        this.app.paper.reset();
        this.renderAll();
      }
    };
    $('#exportJsonBtn').onclick = () => {
      const payload = {
        exportedAt: new Date().toISOString(),
        equity: this.app.paper.state.paperEquity,
        feesPaid: this.app.paper.state.feesPaid,
        positions: this.app.paper.state.paperPositions,
        trades: this.app.paper.state.paperTrades,
        settings: this.app.settings.value,
        radar: this.app.radar.snapshot()
      };
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `pump_dump_export_${Date.now()}.json`;
      a.click();
      URL.revokeObjectURL(url);
    };
    $('#clearLogsBtn').onclick = () => this.app.logger.clear();
    this.app.logger.onChange(entries => {
      $('#logBox').textContent = entries.map(e => this.app.logger.format(e)).join('\n');
    });
    $('#settingsForm').onsubmit = event => this.saveSettings(event);
    $('#defaultsBtn').onclick = () => {
      if (!confirm('بازگشت به تنظیمات پیش‌فرض؟')) return;
      this.app.settings.reset();
      this.app.paper = new (this.app.paper.constructor)(this.app.settings, this.app.logger);
      this.renderSettings();
      this.renderAll();
      void this.app.scan();
    };
  }

  saveSettings(event) {
    event.preventDefault();
    const form = event.target;
    const next = { ...this.app.settings.value };
    for (const [key, value] of Object.entries(next)) {
      const el = form.elements[key];
      if (!el) continue;
      if (typeof value === 'number') {
        const n = Number(el.value);
        if (Number.isFinite(n)) next[key] = n;
      } else {
        next[key] = el.value || '';
      }
    }
    this.app.settings.save(next);
    this.app.logger.info('SETTINGS SAVED', { window: next.radarWindowMin, pump: next.radarPumpThresholdPct });
    this.renderAll();
    void this.app.scan();
    alert('✅ تنظیمات ذخیره و اعمال شد');
  }

  renderSettings() {
    const form = $('#settingsForm');
    for (const [key, value] of Object.entries(this.app.settings.value)) {
      const el = form.elements[key];
      if (el) el.value = value;
    }
    $('#autoTradeToggle').checked = toBool(this.app.settings.value.paperAutoDefault);
  }

  renderStats() {
    const paper = this.app.paper;
    let openNet = 0;
    for (const position of paper.state.paperPositions) {
      const market = this.app.marketData.get(position.symbol);
      if (market) openNet += paper.netPnl(position, market.price);
    }
    const trades = paper.state.paperTrades;
    const wins = trades.filter(t => t.pnl > 0).length;
    const grossP = trades.filter(t => t.pnl > 0).reduce((s, t) => s + t.pnl, 0);
    const grossL = trades.filter(t => t.pnl < 0).reduce((s, t) => s + Math.abs(t.pnl), 0);

    $('#equityCard').textContent = `${fmt(paper.state.paperEquity, 2)} USDT`;
    const openEl = $('#openPnlCard');
    openEl.textContent = `${openNet >= 0 ? '+' : ''}${fmt(openNet, 3)} USDT`;
    openEl.style.color = openNet > 0 ? '#10b981' : openNet < 0 ? '#ef4444' : '#8ca3bd';
    $('#winRateCard').textContent = trades.length ? `${(wins / trades.length * 100).toFixed(1)}٪ (${trades.length})` : '--';
    $('#pfCard').textContent = trades.length ? (grossL > 0 ? (grossP / grossL).toFixed(2) : '∞') : '--';
    $('#feesCard').textContent = `${fmt(paper.state.feesPaid, 3)} USDT`;
    const sv = this.app.signalValidator?.stats();
    const accEl = $('#radarAccuracyCard');
    if (accEl) accEl.textContent = sv?.settled ? `${sv.accuracyPct}% (${sv.settled})` : '⏳ در حال جمع‌آوری';

    const audioBtn = $('#audioToggleBtn');
    if (audioBtn) {
      const on = String(this.app.settings.value.audioAlerts) === 'true';
      audioBtn.textContent = on ? '🔊 صدا: روشن' : '🔇 صدا: خاموش';
      audioBtn.style.borderColor = on ? '#10b981' : '#8ca3bd';
      audioBtn.style.color = on ? '#10b981' : '#8ca3bd';
    }
  }

  renderRadar() {
    const snap = this.app.radar.snapshot();
    const badge = $('#radarStatusBadge');
    if (!badge) return;
    badge.textContent = snap.enabled ? (snap.error ? 'خطا در آخرین پول' : 'فعال') : 'غیرفعال';
    badge.style.color = !snap.enabled ? '#8ca3bd' : snap.error ? '#ef4444' : '#10b981';
    $('#radarSourceMeta').textContent = snap.lastPollAt ? `${snap.source} • ${new Date(snap.lastPollAt).toLocaleTimeString()}` : '--';
    $('#radarUniverse').textContent = snap.universe ? `${snap.universe} نماد` : '--';
    $('#radarWarmup').textContent = snap.warmupRemainMin ? `~${snap.warmupRemainMin} دقیقه تا پنجره کامل` : 'پنجره کامل ✓';
    $('#radarDiscovered').textContent = String(snap.active.length);

    // ⏱ تایم‌فریم کار رادار — زنده از Settings (تشخیص/ورود/قضاوت)
    const set = this.app.settings.value;
    const modeEl = $('#radarModeMeta');
    if (modeEl) modeEl.textContent = `تشخیص: پنجره ${Math.max(5, Number(set.radarWindowMin) || 60)} دقیقه • ورود: ${tfLabel(set.entryTimeframe || '1')} • قضاوت رویداد: ${Math.max(1, Number(set.radarCheckMinutes) || 10)} دقیقه`;
    const sumEl = $('#ignitionSummary');
    if (sumEl) sumEl.textContent = this.app.ignitionSummary || 'در انتظار اولین اسکن...';

    const turnover = v => {
      const n = Number(v) || 0;
      return n >= 1e9 ? `$${(n / 1e9).toFixed(2)}B` : n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : `$${(n / 1e3).toFixed(0)}K`;
    };
    const change = v => `<td class="${v >= 0 ? 'pnl-pos' : 'pnl-neg'}">${v >= 0 ? '+' : ''}${Number(v).toFixed(2)}%</td>`;

    $('#moversRows').innerHTML = (snap.movers || []).slice(0, 12).map(m => `<tr>
      <td style="font-weight:800;">${escapeHtml(m.symbol)}</td>
      ${change(m.changePct)}
      <td>${m.basis === 'window' ? 'پنجره رادار' : 'تقریب ۲۴س'}</td>
      <td>${turnover(m.turnover24h)}</td>
      <td>${m.isNew ? '🆕 تازه‌لیست' : m.changePct >= 10 ? '🚀 داغ' : m.changePct <= -10 ? '💀 ریزش' : '—'}</td>
    </tr>`).join('') || '<tr><td colspan="5">در انتظار اولین پول موفق...</td></tr>';

    const sideLabel = { LONG: '🚀 پمپ → کاندید خرید', SHORT: '💀 دامپ → کاندید فروش', WATCH: '🆕 تازه‌لیست → فقط WATCH' };
    $('#activeRows').innerHTML = (snap.active || []).map(rec => {
      const signal = this.app.signals.get(rec.symbol);
      const block = this.app.blockReasons.get(rec.symbol);
      const blockHtml = block ? `<div class="block-reason">🚫 ${escapeHtml(block)}</div>` : '';
      const planHtml = signal && signal.side !== 'WAIT'
        ? `<div class="trade-plan">Entry ${fmt(signal.entry)} | SL ${fmt(signal.stop)} | TP ${fmt(signal.take)} | امتیاز ${signal.score}٪</div>`
        : '';
      return `<tr>
        <td style="font-weight:800;">${escapeHtml(rec.symbol)}</td>
        <td>${sideLabel[rec.side] || rec.side}</td>
        ${change(rec.changePct)}
        <td>${turnover(rec.turnover24h)}</td>
        <td>${rec.ttlRemainMin} دقیقه</td>
        <td>${blockHtml || planHtml || '—'}</td>
      </tr>`;
    }).join('') || '<tr><td colspan="5">هنوز نماد داغی کشف نشده...</td></tr>';

    const typeLabel = { PUMP: '🚀 PUMP', DUMP: '💀 DUMP', NEW: '🆕 NEW' };
    const verdictLabel = { CORRECT: '✅ درست', INCORRECT: '❌ غلط', PENDING: '⏳ …' };
    $('#eventsRows').innerHTML = (snap.events || []).map(ev => {
      const verdict = ev.type === 'NEW' ? null
        : this.app.signalValidator?.get(`ev:${ev.symbol}:${Math.floor(ev.t / 60000)}`);
      return `<tr>
      <td>${ev.t ? new Date(ev.t).toLocaleTimeString() : '--'}</td>
      <td style="font-weight:800;">${typeLabel[ev.type] || ev.type}</td>
      <td>${escapeHtml(ev.symbol)}</td>
      ${change(ev.changePct)}
      <td>${turnover(ev.turnover24h)}</td>
      <td class="${verdict?.status === 'CORRECT' ? 'pnl-pos' : verdict?.status === 'INCORRECT' ? 'pnl-neg' : 'muted'}">${verdict ? `${verdictLabel[verdict.status] || verdict.status}${verdict.movePct !== null ? ` (${verdict.movePct > 0 ? '+' : ''}${verdict.movePct}%)` : ''}` : '—'}</td>
    </tr>`; }).join('') || '<tr><td colspan="6">رخدادی ثبت نشده...</td></tr>';
  }

  renderTrades() {
    const paper = this.app.paper;
    const prices = this.app.marketData;
    $('#positionsRows').innerHTML = paper.state.paperPositions.map(p => {
      const market = prices.get(p.symbol);
      const pnl = market ? paper.netPnl(p, market.price) : Number.NaN;
      const holdMin = Math.round((Date.now() - p.openedAt) / 60000);
      return `<tr>
        <td>${escapeHtml(p.symbol)}</td>
        <td>${escapeHtml(p.side)}</td>
        <td>${fmt(p.entry)}</td>
        <td>${market ? fmt(market.price) : '--'}</td>
        <td>${fmt(p.stop)} / ${fmt(p.take)}</td>
        <td>${holdMin}m</td>
        <td class="${pnl >= 0 ? 'pnl-pos' : 'pnl-neg'}">${fmt(pnl, 3)}</td>
      </tr>`;
    }).join('') || '<tr><td colspan="7">پوزیشن بازی نداریم</td></tr>';

    // 🗂 دیتاگرید معاملات — فیلتر (جست‌وجو/سمت) + سورت روی ستون‌ها
    if (!this.tradesGrid) {
      this.tradesGrid = new SimpleGrid({
        tbodyId: 'tradesRows',
        columns: [
          { key: 'time', label: 'زمان', type: 'time' },
          { key: 'symbol', label: 'نماد', type: 'text' },
          { key: 'side', label: 'سمت', type: 'text' },
          { key: 'entry', label: 'ورود → خروج', type: 'number' },
          { key: 'radarChangePct', label: 'کشف رادار', type: 'number' },
          { key: 'fees', label: 'Fees', type: 'number' },
          { key: 'pnl', label: 'Net PnL', type: 'number' },
          { key: 'reason', label: 'دلیل / مدت', type: 'text' }
        ],
        initialSort: { key: 'time', dir: -1 },
        filters: [
          { id: 'q', label: '🔍 جست‌وجو (نماد/دلیل)', type: 'text', match: (row, val) => `${row.symbol} ${row.reason}`.toLowerCase().includes(val.toLowerCase()) },
          { id: 'side', label: 'سمت', type: 'select', options: ['LONG', 'SHORT'], match: (row, val) => row.side === val }
        ],
        getData: () => paper.state.paperTrades,
        renderRow: t => `<tr>
      <td>${new Date(t.time).toLocaleString()}</td>
      <td>${escapeHtml(t.symbol)}</td>
      <td>${escapeHtml(t.side)}</td>
      <td>${fmt(t.entry)} → ${fmt(t.exit)}</td>
      <td>${t.radarChangePct !== undefined ? `${t.radarChangePct >= 0 ? '+' : ''}${Number(t.radarChangePct).toFixed(1)}٪` : '--'}</td>
      <td>${fmt(t.fees, 3)}</td>
      <td class="${t.pnl >= 0 ? 'pnl-pos' : 'pnl-neg'}">${fmt(t.pnl, 3)}</td>
      <td>${escapeHtml(t.reason)} • ${Math.round(t.durationSec / 60)}m</td>
    </tr>`,
        emptyHtml: '<tr><td colspan="8">هنوز معامله‌ای بسته نشده (یا فیلتر همه را حذف کرده)</td></tr>'
      });
    }
    this.tradesGrid.render();
  }

  renderAll() {
    // 🛡 ضدگلوله: هر بخش جداگانه — خطای یک بخش هرگز رندر بقیه را نمی‌کشد
    const sections = [['آمار', () => this.renderStats()], ['رادار', () => this.renderRadar()], ['معاملات', () => this.renderTrades()]];
    const errors = [];
    for (const [name, fn] of sections) {
      try { fn(); } catch (error) { errors.push(`${name}: ${error.message}`); }
    }
    if (errors.length) {
      this.app.logger?.info?.('RENDER ERROR', { errors: errors.join(' | ') });
      const st = document.getElementById('statusText');
      if (st) st.textContent = `⚠️ خطای رندر: ${errors.join(' | ')}`;
    }
  }
}
