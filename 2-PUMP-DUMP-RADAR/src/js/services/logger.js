import { readJson, writeJson } from '../core/utils.js';
import { STORAGE_KEYS } from '../core/config.js';

const MAX_LINES = 2000; // سقف لاگ ماندگار — برای «بررسی بعد» (v1.2.1)

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
    this.lines.unshift({ t: new Date().toISOString(), level: 'info', msg, ...(obj !== undefined ? { obj } : {}) });
    this.lines = this.lines.slice(0, MAX_LINES);
    this.emit();
  }

  format(entry) {
    if (typeof entry === 'string') return entry;
    const time = entry.t ? new Date(entry.t).toLocaleString() : '--';
    return `[${time}] ${entry.msg}${entry.obj ? ' ' + JSON.stringify(entry.obj) : ''}`;
  }

  clear() {
    this.lines = [];
    this.emit();
  }
}
