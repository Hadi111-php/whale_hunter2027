/**
 * سیستم هشدار صوتی زنده (Live Audio Beep & Proximity Alert)
 * ---------------------------------------------------------------------------
 * مبتنی بر Web Audio API و کاملاً بدون نیاز به فایل صوتی خارجی.
 *
 * سطح ۱ — Pre-Alert (چایم ملایم):
 *   وقتی امتیاز سیگنال یک نماد از آستانه (پیش‌فرض ۷۵) عبور کند؛ با Cooldown
 *   پارامتریک برای هر نماد تا اسکن‌های پرتکرار باعث اسپم صوتی نشوند.
 *
 * سطح ۲ — Execution Beep (بوق اجرای معامله):
 *   دو بوق صعودی برای باز شدن خودکار خرید (LONG) و دو بوق نزولی برای فروش (SHORT).
 *
 * نکته مرورگر: AudioContext تا اولین تعامل کاربر (کلیک/لمس) در حالت suspended
 * است؛ به همین دلیل view روی اولین pointerdown یک بار unlock() صدا می‌زند.
 * در محیط بدون AudioContext (مثل تست Node) همه متدها بدون خطا no-op می‌شوند.
 */
export class AudioAlerts {
  constructor(settings, logger) {
    this.s = settings;
    this.log = logger;
    this.ctx = null;
    this.lastChimeAt = new Map();
  }

  enabled() {
    return String(this.s.value.audioAlerts) === 'true';
  }

  unlock() {
    const ctx = this.ensureCtx();
    if (ctx && ctx.state === 'suspended') ctx.resume().catch(() => {});
    return !!ctx;
  }

  ensureCtx() {
    if (this.ctx) return this.ctx;
    const Ctor = globalThis.AudioContext || globalThis.webkitAudioContext;
    if (!Ctor) return null;
    try {
      this.ctx = new Ctor();
    } catch {
      this.ctx = null;
    }
    return this.ctx;
  }

  tone(freq, atSec, durSec, { type = 'sine', volume } = {}) {
    const ctx = this.ensureCtx();
    if (!ctx) return false;
    if (ctx.state === 'suspended') ctx.resume().catch(() => {});
    const master = Number.isFinite(Number(volume)) ? Number(volume) : Number(this.s.value.audioVolume);
    const peak = Math.min(1, Math.max(0.0001, master * 0.4));
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    const t0 = ctx.currentTime + atSec;
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t0);
    gain.gain.setValueAtTime(0.0001, t0);
    gain.gain.exponentialRampToValueAtTime(peak, t0 + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + durSec);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(t0);
    osc.stop(t0 + durSec + 0.05);
    return true;
  }

  softVolume() {
    return Math.min(1, Number(this.s.value.audioVolume) * 0.5);
  }

  // سطح ۱ — چایم ملایم دو نُتی (A5 → D6) با حجم کمتر
  preAlert() {
    const v = this.softVolume();
    this.tone(880, 0, 0.18, { volume: v });
    this.tone(1174.66, 0.12, 0.22, { volume: v });
  }

  // سطح ۲ — دو بوق: صعودی (C5 → G5) برای خرید، نزولی (G5 → C5) برای فروش
  execution(side, symbol) {
    if (!this.enabled()) return;
    const isLong = String(side).toUpperCase() === 'LONG';
    if (isLong) {
      this.tone(523.25, 0, 0.12);
      this.tone(783.99, 0.15, 0.16);
    } else {
      this.tone(783.99, 0, 0.12);
      this.tone(523.25, 0.15, 0.16);
    }
    this.log?.info?.('AUDIO EXECUTION BEEP', { side, symbol: symbol || '--' });
  }

  /**
   * بررسی Pre-Alert در هر اسکن: اگر امتیاز نماد بالای آستانه باشد و Cooldown
   * نماد گذشته باشد، چایم پخش می‌شود. عمداً ساده و قابل پیش‌بینی است:
   * «حداقل یک بوق در هر بازه cooldown برای نمادِ داغ» — بدون اسپم.
   */
  preAlertCheck(signal) {
    if (!signal || !this.enabled()) return false;
    const threshold = Number(this.s.value.preAlertScore);
    if (!Number.isFinite(threshold)) return false;
    const score = Number(signal.score);
    if (!Number.isFinite(score) || score < threshold) return false;

    const cooldownMs = Math.max(0, Number(this.s.value.preAlertCooldownSec)) * 1000;
    const key = signal.symbol;
    const last = Number(this.lastChimeAt.get(key) || 0);
    if (Date.now() - last < cooldownMs) return false;

    this.lastChimeAt.set(key, Date.now());
    this.preAlert();
    this.log?.info?.('AUDIO PRE-ALERT', { symbol: key, score, threshold });
    return true;
  }

  // وقتی دیتای نماد قطع شد، وضعیت صوتی آن پاک شود
  drop(symbol) {
    this.lastChimeAt.delete(symbol);
  }
}
