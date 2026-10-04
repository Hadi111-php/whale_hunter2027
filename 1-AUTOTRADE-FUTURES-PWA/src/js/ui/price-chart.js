import { fmt } from '../core/utils.js';
import { reversalZones, zigzagPivots, DEFAULT_REVERSAL_PARAMS } from '../services/reversal-detector.js';

/**
 * 📈 چارت تعاملی کندل‌استیک — سبک TradingView
 * ---------------------------------------------------------------------------
 * خواستهٔ داداش هادی: «نموداری که نشان دهد کجا buy/sell احتمال وقوع دارد، با
 * قابلیت زوم (دو انگشت روی موبایل / اسکرول دسکتاپ) و برعکسش.»
 *
 * امکانات:
 *   • زوم: پینچ دو انگشتی (موبایل) + چرخ ماوس (دسکتاپ) — لنگر روی محل انگشت/موس
 *   • پن: درگ با یک انگشت/ماوس به چپ‌وراست
 *   • ریست: دابل‌کلیک/دابل‌تپ
 *   • نواحی احتمالی خرید/فروش: باندهای سبز/قرمز از الگوهای V (کف) و Λ (سقف)
 *   • مارکر معاملات واقعی: ▲ ورود / ✕ خروج (سبز=سود، قرمز=ضرر)
 *   • خطوط Last/Entry/SL/TP + کراس‌هیر و اطلاعات OHLC هاور
 */
export class PriceChart {
  constructor(canvas) {
    this.canvas = canvas;
    this.market = null;
    this.signal = null;
    this.trades = [];
    this.maxBars = 400;
    this.view = { bars: 90, offset: 0 }; // offset = تعداد کندل عقب‌تر از آخرین کندل
    this.hover = null;
    this.pointers = new Map();
    this.pinch = null;

    canvas.style.touchAction = 'none'; // ژست‌های مرورگر را خاموش کن — پینچ برای ما
    this.resizeObserver = typeof ResizeObserver === 'function'
      ? new ResizeObserver(() => this.draw())
      : null;
    if (this.resizeObserver) this.resizeObserver.observe(canvas);
    window.addEventListener('resize', () => this.draw());
    this.bindEvents();
  }

  setData(market, signal, trades = []) {
    this.market = market || null;
    this.signal = signal || null;
    this.trades = Array.isArray(trades) ? trades : [];
    // حفظ موقعیت نمای فعلی در حدود مجاز
    this.clampView();
    this.draw();
  }

  clear(message = 'No market data') {
    this.market = null;
    this.signal = null;
    this.trades = [];
    this.view = { bars: 90, offset: 0 };
    this.draw(message);
  }

  candles() {
    return (this.market?.candles || []).slice(-this.maxBars);
  }

  clampView() {
    const total = this.candles().length;
    if (!total) return;
    this.view.bars = Math.max(20, Math.min(this.maxBars, Math.round(this.view.bars)));
    this.view.offset = Math.max(0, Math.min(total - this.view.bars, Math.round(this.view.offset)));
  }

  bindEvents() {
    const c = this.canvas;
    c.addEventListener('pointerdown', event => {
      c.setPointerCapture(event.pointerId);
      this.pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (this.pointers.size === 2) {
        const [p1, p2] = [...this.pointers.values()];
        this.pinch = { dist: Math.hypot(p1.x - p2.x, p1.y - p2.y), bars: this.view.bars };
      }
    });
    c.addEventListener('pointermove', event => {
      if (!this.pointers.has(event.pointerId)) {
        // هاور (بدون درگ): کراس‌هیر + اطلاعات کندل
        const rect = c.getBoundingClientRect();
        this.hover = { x: event.clientX - rect.left, y: event.clientY - rect.top };
        this.draw();
        return;
      }
      const prev = this.pointers.get(event.pointerId);
      this.pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (this.pointers.size === 2 && this.pinch) {
        // 🤏 پینچ دو انگشتی → زوم
        const [p1, p2] = [...this.pointers.values()];
        const dist = Math.hypot(p1.x - p2.x, p1.y - p2.y);
        if (dist > 8 && this.pinch.dist > 8) {
          this.view.bars = this.pinch.bars * (this.pinch.dist / dist);
          this.clampView();
        }
      } else if (this.pointers.size === 1 && prev) {
        // 👆 درگ تک‌انگشتی → پن
        const dBars = (event.clientX - prev.x) / (this.barPx || 8);
        this.view.offset += dBars > 0 ? Math.ceil(dBars) : Math.floor(dBars);
        this.clampView();
        this.draw();
      }
    });
    const release = event => {
      this.pointers.delete(event.pointerId);
      if (this.pointers.size < 2) this.pinch = null;
    };
    c.addEventListener('pointerup', release);
    c.addEventListener('pointercancel', release);
    c.addEventListener('pointerleave', () => { this.hover = null; this.draw(); });
    c.addEventListener('wheel', event => {
      event.preventDefault();
      const factor = event.deltaY > 0 ? 1.12 : 0.89;
      this.view.bars *= factor;
      this.clampView();
      this.draw();
    }, { passive: false });
    c.addEventListener('dblclick', () => {
      this.view = { bars: 90, offset: 0 };
      this.draw();
    });
  }

  dimensions() {
    const rect = this.canvas.getBoundingClientRect();
    const width = Math.max(320, Math.floor(rect.width || this.canvas.clientWidth || 820));
    const height = Math.max(260, Math.floor(rect.height || 360));
    const ratio = window.devicePixelRatio || 1;
    this.canvas.width = Math.floor(width * ratio);
    this.canvas.height = Math.floor(height * ratio);
    this.canvas.style.height = `${height}px`;
    const context = this.canvas.getContext('2d');
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    return { context, width, height };
  }

  draw(emptyMessage = 'منتظر دیتای معتبر Bybit...') {
    const { context: ctx, width, height } = this.dimensions();
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#08182a';
    ctx.fillRect(0, 0, width, height);

    const all = this.candles();
    if (!all.length) {
      ctx.fillStyle = '#8ca3bd';
      ctx.font = '14px Tahoma, Arial';
      ctx.textAlign = 'center';
      ctx.fillText(emptyMessage, width / 2, height / 2);
      return;
    }

    const total = all.length;
    const end = total - this.view.offset;            // آخرین کندلِ نمای فعلی
    const start = Math.max(0, end - this.view.bars); // اولین کندلِ نمای فعلی
    const candles = all.slice(start, end);
    const signal = this.signal;
    const padding = { left: 58, right: 18, top: 24, bottom: 48 };
    const chartWidth = width - padding.left - padding.right;
    const chartHeight = height - padding.top - padding.bottom;
    const volumeHeight = Math.max(34, chartHeight * 0.16);
    const priceHeight = chartHeight - volumeHeight - 10;
    const plotted = candles.flatMap(cd => [Number(cd.low), Number(cd.high)]).filter(Number.isFinite);
    const signalPrices = signal?.side !== 'WAIT' ? [signal.entry, signal.stop, signal.take] : [];
    const zones = reversalZones(all, DEFAULT_REVERSAL_PARAMS, Math.min(all.length, 120));
    const zonePrices = zones.flatMap(z => [z.priceLow, z.priceHigh]);
    const minPrice = Math.min(...plotted, ...zonePrices.filter(Number.isFinite));
    const maxPrice = Math.max(...plotted, ...zonePrices.filter(Number.isFinite));
    const span = Math.max(maxPrice - minPrice, maxPrice * 0.0001);
    const lower = minPrice - span * 0.06;
    const upper = maxPrice + span * 0.06;
    const maxVolume = Math.max(...candles.map(cd => Number(cd.volume) || 0), 1);
    const step = chartWidth / candles.length;
    this.barPx = step;
    const bodyWidth = Math.max(2, step * 0.62);

    const priceY = price => padding.top + (upper - price) / (upper - lower) * priceHeight;
    const barX = idx => padding.left + (idx - start) * step + step / 2; // idx در کل آرایهٔ all

    // ── نواحی احتمالی خرید/فروش (V/Λ) — باند افقی روی کل ناحیهٔ دید
    for (const z of zones) {
      const y1 = priceY(z.priceHigh);
      const y2 = priceY(z.priceLow);
      if (!Number.isFinite(y1) || !Number.isFinite(y2)) continue;
      ctx.fillStyle = z.kind === 'buy' ? 'rgba(53,224,161,.10)' : 'rgba(255,92,122,.10)';
      ctx.fillRect(padding.left, y1, chartWidth, Math.max(2, y2 - y1));
      ctx.strokeStyle = z.kind === 'buy' ? 'rgba(53,224,161,.45)' : 'rgba(255,92,122,.45)';
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(padding.left, y1); ctx.lineTo(width - padding.right, y1);
      ctx.moveTo(padding.left, y2); ctx.lineTo(width - padding.right, y2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = z.kind === 'buy' ? '#35e0a1' : '#ff5c7a';
      ctx.font = 'bold 10px Tahoma, Arial';
      ctx.textAlign = 'left';
      ctx.fillText(z.kind === 'buy' ? `V خرید احتمالی ${fmt(z.strengthPct, 1)}٪` : `Λ فروش احتمالی ${fmt(z.strengthPct, 1)}٪`, padding.left + 6, y1 - 3);
    }

    // ── شبکه و محور قیمت
    ctx.strokeStyle = 'rgba(140,163,189,.16)';
    ctx.lineWidth = 1;
    ctx.font = '10px Tahoma, Arial';
    ctx.textAlign = 'left';
    ctx.fillStyle = '#8ca3bd';
    for (let i = 0; i <= 4; i += 1) {
      const y = padding.top + priceHeight * i / 4;
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(width - padding.right, y);
      ctx.stroke();
      const value = upper - (upper - lower) * i / 4;
      ctx.fillText(fmt(value, value > 10 ? 2 : 6), 5, y + 4);
    }

    // ── حجم و کندل‌ها
    candles.forEach(cd => {
      const idx = all.indexOf(cd);
      const x = barX(idx);
      const rising = cd.close >= cd.open;
      const color = rising ? '#35e0a1' : '#ff5c7a';
      ctx.fillStyle = rising ? 'rgba(53,224,161,.28)' : 'rgba(255,92,122,.28)';
      const volumeTop = padding.top + priceHeight + 10 + (1 - (Number(cd.volume) || 0) / maxVolume) * volumeHeight;
      ctx.fillRect(x - bodyWidth / 2, volumeTop, bodyWidth, padding.top + priceHeight + 10 + volumeHeight - volumeTop);

      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, priceY(cd.high));
      ctx.lineTo(x, priceY(cd.low));
      ctx.stroke();
      ctx.fillStyle = color;
      const openY = priceY(cd.open);
      const closeY = priceY(cd.close);
      ctx.fillRect(x - bodyWidth / 2, Math.min(openY, closeY), bodyWidth, Math.max(1, Math.abs(closeY - openY)));
    });

    // ── مارکرهای V/Λ (نقطهٔ برگشت)
    const pivots = zigzagPivots(all, DEFAULT_REVERSAL_PARAMS);
    for (const p of pivots) {
      if (p.i < start || p.i >= end) continue;
      const x = barX(p.i);
      const y = priceY(p.price);
      ctx.fillStyle = p.type === 'low' ? '#35e0a1' : '#ff5c7a';
      ctx.font = 'bold 11px Tahoma, Arial';
      ctx.textAlign = 'center';
      ctx.fillText(p.type === 'low' ? 'V' : 'Λ', x, p.type === 'low' ? y + 16 : y - 8);
    }

    // ── مارکرهای معاملات واقعی (▲ ورود / ✕ خروج)
    const tfMs = all.length > 1 ? all[1].ts - all[0].ts : 0;
    for (const t of this.trades) {
      const tTime = Number(t.time);
      if (!Number.isFinite(tTime)) continue;
      let idx = all.findIndex(cd => cd.ts <= tTime && (tfMs === 0 || cd.ts + tfMs > tTime));
      if (idx < 0) idx = tTime >= all[0].ts ? all.length - 1 : -1;
      if (idx < start || idx >= end) continue;
      const x = barX(idx);
      // ورود
      const entryY = priceY(Number(t.entry));
      if (Number.isFinite(entryY)) {
        ctx.fillStyle = t.side === 'LONG' ? '#35e0a1' : '#ff5c7a';
        ctx.beginPath();
        const dir = t.side === 'LONG' ? 1 : -1;
        ctx.moveTo(x, entryY + dir * 9);
        ctx.lineTo(x - 5, entryY - dir * 4);
        ctx.lineTo(x + 5, entryY - dir * 4);
        ctx.closePath();
        ctx.fill();
      }
      // خروج
      const exitY = priceY(Number(t.exit));
      if (Number.isFinite(exitY)) {
        ctx.strokeStyle = Number(t.pnl) >= 0 ? '#35e0a1' : '#ff5c7a';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x - 4, exitY - 4); ctx.lineTo(x + 4, exitY + 4);
        ctx.moveTo(x + 4, exitY - 4); ctx.lineTo(x - 4, exitY + 4);
        ctx.stroke();
      }
    }

    // ── خطوط قیمت
    const lastPrice = Number(this.market.price);
    this.drawLine(ctx, padding.left, width - padding.right, priceY(lastPrice), '#53a7ff', 'Last', lastPrice, height, padding);
    if (signal?.side !== 'WAIT') {
      this.drawLine(ctx, padding.left, width - padding.right, priceY(signal.entry), '#ffd166', 'Entry', signal.entry, height, padding);
      this.drawLine(ctx, padding.left, width - padding.right, priceY(signal.stop), '#ff5c7a', 'SL', signal.stop, height, padding);
      this.drawLine(ctx, padding.left, width - padding.right, priceY(signal.take), '#35e0a1', 'TP', signal.take, height, padding);
    }

    // ── کراس‌هیر + اطلاعات کندل هاور‌شده
    if (this.hover) {
      const idx = Math.min(candles.length - 1, Math.max(0, Math.floor((this.hover.x - padding.left) / step)));
      const cd = candles[idx];
      if (cd) {
        const x = barX(all.indexOf(cd));
        ctx.strokeStyle = 'rgba(140,163,189,.4)';
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(x, padding.top); ctx.lineTo(x, height - padding.bottom);
        ctx.moveTo(padding.left, this.hover.y); ctx.lineTo(width - padding.right, this.hover.y);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = '#e9f1ff';
        ctx.font = '10px Tahoma, Arial';
        ctx.textAlign = 'left';
        const dec = cd.close > 10 ? 2 : 6;
        ctx.fillText(`O ${fmt(cd.open, dec)}  H ${fmt(cd.high, dec)}  L ${fmt(cd.low, dec)}  C ${fmt(cd.close, dec)}`, padding.left + 6, padding.top - 8);
      }
    }

    // ── سربرگ و راهنما
    ctx.fillStyle = '#e9f1ff';
    ctx.font = 'bold 12px Tahoma, Arial';
    ctx.textAlign = 'right';
    ctx.fillText(`${this.market.symbol} • ${this.market.source}`, width - padding.right, 15);
    ctx.fillStyle = '#8ca3bd';
    ctx.font = '10px Tahoma, Arial';
    const zoomHint = 'زوم: پینچ/اسکرول • پن: درگ • ریست: دابل‌تپ';
    ctx.fillText(`${candles.length}/${total} کندل • ${signal?.side || 'WAIT'} • ${zoomHint}`, width - padding.right, height - 12);
  }

  drawLine(ctx, left, right, y, color, label, value, canvasHeight, padding) {
    if (!Number.isFinite(y) || y < padding.top - 5 || y > canvasHeight - padding.bottom + 5) return;
    ctx.save();
    ctx.setLineDash([5, 4]);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
    ctx.restore();
    ctx.fillStyle = color;
    ctx.font = '10px Tahoma, Arial';
    ctx.textAlign = 'left';
    ctx.fillText(`${label} ${fmt(value, value > 10 ? 2 : 6)}`, 5, Math.max(padding.top + 10, y - 4));
  }
}
