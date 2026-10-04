/**
 * هشدار صوتی رادار پمپ/دامپ — Web Audio API خالص، بدون فایل خارجی.
 * PUMP: سه نُتی صعودی | DUMP: سه نُتی نزولی | NEW/کشف: چایم دو نُتی
 * Execution: دو بوق صعودی برای خرید، نزولی برای فروش.
 */
export class AudioAlerts {
  constructor(settings, logger) {
    this.s = settings;
    this.log = logger;
    this.ctx = null;
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

  soft() {
    return Math.min(1, Number(this.s.value.audioVolume) * 0.5);
  }

  radarAlert(type) {
    if (!this.enabled()) return;
    if (type === 'PUMP') {
      this.tone(523.25, 0, 0.12);
      this.tone(659.25, 0.13, 0.12);
      this.tone(783.99, 0.26, 0.18);
    } else if (type === 'DUMP') {
      this.tone(783.99, 0, 0.12);
      this.tone(659.25, 0.13, 0.12);
      this.tone(523.25, 0.26, 0.18);
    } else {
      const v = this.soft();
      this.tone(880, 0, 0.18, { volume: v });
      this.tone(1174.66, 0.12, 0.22, { volume: v });
    }
  }

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
}
