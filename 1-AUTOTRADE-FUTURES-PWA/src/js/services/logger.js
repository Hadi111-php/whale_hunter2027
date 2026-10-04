import { readJson, writeJson } from '../core/utils.js';
import { STORAGE_KEYS } from '../core/config.js';

const MAX_LINES = 2000; // سقف لاگ ماندگار در localStorage — برای «بررسی بعد» (v2.10.1)

/**
 * لاگر ساختاریافته: هر رخداد یک آبجکت { t, level, msg, obj? } است تا
 * ۱) در کنسول لاگ به صورت متن خوانا نمایش داده شود و
 * ۲) با toJsonl() به فایل JSONL (هر خط یک JSON) برای کالبدشکافی آفلاین تبدیل شود.
 * رکوردهای متنی قدیمی به صورت خودکار به فرم ساختاریافته مهاجرت داده می‌شوند.
 */
export class Logger {
  constructor() {
    const saved = readJson(STORAGE_KEYS.logs, []);
    this.lines = (Array.isArray(saved) ? saved : [])
      .map(entry => (typeof entry === 'string' ? { t: new Date().toISOString(), level: 'info', msg: entry } : entry))
      .filter(entry => entry && typeof entry.msg !== 'undefined');
    this.listeners = new Set();
  }

  onChange(fn) {
    this.listeners.add(fn);
    fn(this.lines);
  }

  emit() {
    writeJson(STORAGE_KEYS.logs, this.lines);
    this.listeners.forEach(fn => fn(this.lines));
  }

  info(msg, obj) {
    this.lines.unshift({
      t: new Date().toISOString(),
      level: 'info',
      msg,
      ...(obj !== undefined ? { obj } : {})
    });
    this.lines = this.lines.slice(0, MAX_LINES);
    this.emit();
  }

  format(entry) {
    if (typeof entry === 'string') return entry;
    const time = entry.t ? new Date(entry.t).toLocaleString() : '--';
    return `[${time}] ${entry.msg}${entry.obj ? ' ' + JSON.stringify(entry.obj) : ''}`;
  }

  // خروجی JSONL به ترتیب زمانی (قدیمی → جدید) — آماده ذخیره و تحلیل با tools/manage_trades.py
  toJsonl() {
    return [...this.lines].reverse().map(entry => JSON.stringify(entry)).join('\n');
  }

  clear() {
    this.lines = [];
    this.emit();
  }
}
