// static/js/modules/Timeline.js
export class Timeline {
    constructor() {
        this.events = [];
        this.currentTime = 0.0;
        this.duration = 10.0;
        this.isPlaying = false;
        this.listeners = [];
        this._sortedEvents = null; // کش برای آرایه مرتب‌شده
    }

    addEvent(event) {
        this.events.push(event);
        this._sortedEvents = null; // ابطال کش
        this.recalculateDuration();
        this.notifyChange();
    }

    removeEvent(eventId) {
        this.events = this.events.filter(e => e.id !== eventId);
        this._sortedEvents = null; // ابطال کش
        this.recalculateDuration();
        this.notifyChange();
    }

    getEvent(eventId) {
        return this.events.find(e => e.id === eventId);
    }

    updateEvent(eventId, newData) {
        const evt = this.getEvent(eventId);
        if (evt) {
            Object.assign(evt, newData);
            this._sortedEvents = null; // ابطال کش
            this.recalculateDuration();
            this.notifyChange();
        }
    }

    // بهینه‌سازی ترکیبی: جستجوی دودویی برای مرز شروع + فیلتر سریع بازه‌ای
    // این روش مانع از قطع شدن رویدادهای طولانی (مثل موزیک زمینه ۳ دقیقه‌ای) می‌شود
    getActiveEvents(time) {
        if (this.events.length === 0) return [];
        
        const sorted = this.getSortedEvents();
        
        // یافتن آخرین رویدادی که startTime <= time است با جستجوی دودویی
        let low = 0, high = sorted.length - 1;
        let lastEligibleIndex = -1;
        
        while (low <= high) {
            const mid = (low + high) >> 1;
            if (sorted[mid].startTime <= time) {
                lastEligibleIndex = mid;
                low = mid + 1;
            } else {
                high = mid - 1;
            }
        }

        if (lastEligibleIndex === -1) return [];

        // جمع‌آوری تمام رویدادهایی که هنوز پایان نیافته‌اند (پوشش کامل رویدادهای همپوشان و بلند)
        const active = [];
        for (let i = 0; i <= lastEligibleIndex; i++) {
            if (sorted[i].endTime >= time) {
                active.push(sorted[i]);
            }
        }
        return active;
    }

    getSortedEvents() {
        if (!this._sortedEvents) {
            this._sortedEvents = [...this.events].sort((a, b) => a.startTime - b.startTime);
        }
        return this._sortedEvents;
    }

    recalculateDuration() {
        let maxT = 10.0;
        for (const e of this.events) {
            if (e.endTime > maxT) {
                maxT = e.endTime;
            }
        }
        this.duration = maxT;
        return this.duration;
    }

    subscribe(callback) {
        this.listeners.push(callback);
    }

    notifyChange() {
        for (const cb of this.listeners) {
            cb(this);
        }
    }
}
