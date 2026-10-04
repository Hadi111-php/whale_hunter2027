/**
 * ✅ اعتبارسنج سیگنال — «هر سیگنال بعد از N دقیقه با واقعیت مقایسه می‌شود»
 * ---------------------------------------------------------------------------
 * برگرفته از سیستم مانیتورینگ نهنگ (فایل Hyper.txt):
 * هر سیگنال/رخداد با وضعیت PENDING ثبت می‌شود و بعد از VALIDATION_DELAY با قیمت
 * فعلی مقایسه و CORRECT یا INCORRECT می‌شود → «درصد دقت واقعی» سیستم همیشه
 * دیده می‌شود. این همان فلسفهٔ نردبان است: قدم بعدی را واقعیت قضاوت می‌کند.
 *
 * خالص و سبک. با persistKey رکوردها در localStorage ماندگار می‌شوند: بعد از
 * ری‌استارت اپ، PENDINGها در همان اسکن بعدی قضاوت می‌شوند و تاریخچهٔ دقت حفظ می‌شود.
 */
import { readJson, writeJson } from '../core/utils.js';

export class SignalValidator {
  /**
   * @param delayMs      چند میلی‌ثانیه بعد، سیگنال قضاوت شود (پیش‌فرض ۱۵ دقیقه)
   * @param thresholdPct حرکت چند درصد در جهت سیگنال = درست (پیش‌فرض ۱.۵٪)
   * @param maxItems     حداکثر رکورد نگه‌داری‌شده (قدیمی‌ها حذف می‌شوند)
   * @param persistKey   اگر داده شود، رکوردها در localStorage ماندگار می‌شوند (ری‌استارت‌پذیر)
   */
  constructor({ delayMs = 15 * 60000, thresholdPct = 1.5, maxItems = 300, persistKey = null } = {}) {
    this.delayMs = Math.max(60000, Number(delayMs) || 15 * 60000);
    this.thresholdPct = Math.max(0.1, Number(thresholdPct) || 1.5);
    this.maxItems = Math.max(10, Number(maxItems) || 300);
    this.persistKey = persistKey ? String(persistKey) : null;
    this.items = new Map(); // id → record
    if (this.persistKey) {
      const saved = readJson(this.persistKey, []);
      if (Array.isArray(saved)) {
        for (const rec of saved.slice(-this.maxItems)) {
          if (rec && rec.id) this.items.set(rec.id, rec);
        }
      }
    }
  }

  /** ذخیرهٔ وضعیت در localStorage (فقط وقتی persistKey داده شده باشد) */
  _persist() {
    if (!this.persistKey) return;
    writeJson(this.persistKey, [...this.items.values()].slice(-this.maxItems));
  }

  /** ثبت سیگنال جدید (id تکراری نادیده گرفته می‌شود). خروجی: ثبت شد یا نه */
  track(id, { symbol, direction, refPrice, meta = {} }) {
    if (!id || this.items.has(id)) return false;
    const price = Number(refPrice);
    if (!Number.isFinite(price) || price <= 0) return false;
    if (!['LONG', 'SHORT'].includes(direction)) return false;
    this.items.set(id, {
      id, symbol, direction, refPrice: price, meta,
      t: Date.now(), status: 'PENDING', movePct: null, settledAt: null
    });
    if (this.items.size > this.maxItems) {
      const oldest = this.items.keys().next().value;
      this.items.delete(oldest);
    }
    this._persist();
    return true;
  }

  /** رکوردهای سررسیدشدهٔ هنوز قضاوت‌نشده */
  pending(now = Date.now()) {
    return [...this.items.values()].filter(item => item.status === 'PENDING' && now - item.t >= this.delayMs);
  }

  /** قضاوت یک رکورد با قیمت فعلی. خروجی: رکورد به‌روزشده یا null */
  settle(id, price, now = Date.now()) {
    const item = this.items.get(id);
    if (!item || item.status !== 'PENDING') return null;
    const p = Number(price);
    if (!Number.isFinite(p) || p <= 0) return null;
    const raw = (p - item.refPrice) / item.refPrice * 100;
    const movePct = item.direction === 'LONG' ? raw : -raw;
    item.movePct = Number(movePct.toFixed(2));
    item.status = movePct >= this.thresholdPct ? 'CORRECT' : 'INCORRECT';
    item.settledAt = now;
    this._persist();
    return item;
  }

  /** خواندن یک رکورد (برای جدول رویدادها) */
  get(id) {
    return this.items.get(id) || null;
  }

  /** آمار دقت: { tracked, settled, correct, incorrect, pending, accuracyPct } */
  stats() {
    const all = [...this.items.values()];
    const settled = all.filter(item => item.status !== 'PENDING');
    const correct = settled.filter(item => item.status === 'CORRECT').length;
    const pending = all.length - settled.length;
    return {
      tracked: all.length,
      settled: settled.length,
      correct,
      incorrect: settled.length - correct,
      pending,
      accuracyPct: settled.length ? Number((correct / settled.length * 100).toFixed(1)) : null
    };
  }
}
