// static/js/handlers/LineHandler.js - نسخه اصلاح‌شده با حذف قطعی خط اشتباه و استایل‌های انیمیشن
import { EventFactory } from '../modules/EventFactory.js';

export class LineHandler {
    constructor(project, onSyncUpdateCallback) {
        this.project = project;
        this.onSyncUpdateCallback = onSyncUpdateCallback || (() => {});
        this.rawLines = [];
        this.currentIndex = -1;
        this.activeEventId = null;
        this.lineToEventMap = new Map(); // نگاشت مستقیم ایندکس خط به شناسه ایونت
        this.lyricAnimationStyle = "karaoke_glow"; // karaoke_glow | fade_zoom | kinetic_popup | clean_lemon
    }

    setRawLyrics(text) {
        this.rawLines = text.split(/\r?\n/).map(l => l.trim()).filter(l => l.length > 0);
        this.currentIndex = -1;
        this.activeEventId = null;
        this.lineToEventMap.clear();
        this.onSyncUpdateCallback(this);
    }

    setAnimationStyle(style) {
        this.lyricAnimationStyle = style || "karaoke_glow";
        if (this.project) {
            this.project.lyricAnimationStyle = this.lyricAnimationStyle;
        }
        this.onSyncUpdateCallback(this);
    }

    nextLine(currentTime) {
        if (this.rawLines.length === 0) return;

        // بستن ایونت خط جاری در زمان کلیک فعلی
        if (this.currentIndex >= 0) {
            const currentEventId = this.lineToEventMap.get(this.currentIndex) || this.activeEventId;
            if (currentEventId) {
                const currentEvt = this.project.timeline.getEvent(currentEventId);
                if (currentEvt) {
                    currentEvt.endTime = currentTime;
                }
            }
        }

        this.currentIndex++;
        if (this.currentIndex >= this.rawLines.length) {
            this.currentIndex = this.rawLines.length - 1;
            this.activeEventId = null;
            this.project.timeline.notifyChange();
            this.onSyncUpdateCallback(this);
            return;
        }

        const nextText = this.rawLines[this.currentIndex];
        const defaultDuration = this.project.defaultLyricDuration || 4.0;
        const defaultEnd = Math.min(currentTime + defaultDuration, this.project.timeline.duration || (currentTime + defaultDuration));
        
        const newEvt = EventFactory.createLyricsEvent(nextText, currentTime, defaultEnd);
        newEvt.animationStyle = this.lyricAnimationStyle;
        
        this.activeEventId = newEvt.id;
        this.lineToEventMap.set(this.currentIndex, newEvt.id);
        this.project.timeline.addEvent(newEvt);
        this.onSyncUpdateCallback(this);
    }

    prevLine(currentTime) {
        if (this.rawLines.length === 0 || this.currentIndex < 0) return;

        // 1. حذف کامل ایونت خط جاری که اشتباه ثبت شده بود
        const currentEventId = this.lineToEventMap.get(this.currentIndex) || this.activeEventId;
        if (currentEventId) {
            this.project.timeline.removeEvent(currentEventId);
            this.lineToEventMap.delete(this.currentIndex);
        }

        // 2. برگشت ایندکس به خط قبل
        this.currentIndex--;

        // 3. اگر هنوز روی خطوط قبلی هستیم، وضعیت خط قبل را بازیابی و باز نگه می‌داریم
        if (this.currentIndex >= 0) {
            const prevEventId = this.lineToEventMap.get(this.currentIndex);
            if (prevEventId) {
                const existingEvt = this.project.timeline.getEvent(prevEventId);
                if (existingEvt) {
                    this.activeEventId = existingEvt.id;
                    const defaultDuration = this.project.defaultLyricDuration || 4.0;
                    existingEvt.endTime = Math.max(existingEvt.startTime + defaultDuration, (currentTime || existingEvt.startTime + defaultDuration));
                }
            } else {
                this.activeEventId = null;
            }
        } else {
            this.activeEventId = null;
        }

        this.project.timeline.notifyChange();
        this.onSyncUpdateCallback(this);
    }

    getCurrentLineText() {
        if (this.currentIndex >= 0 && this.currentIndex < this.rawLines.length) {
            return `[خط ${this.currentIndex + 1}/${this.rawLines.length}]: ${this.rawLines[this.currentIndex]}`;
        }
        return "آماده همگام‌سازی (روی دکمه خط بعدی کلیک کنید)";
    }
}
