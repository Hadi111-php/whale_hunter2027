داداش 
### 🔴 **۱. باگ مرگبار `prevLine` برای شعرهای تکراری (Critical)**
**مشکل:** جستجو بر اساس `e.content === prevText` در شعرهای تکراری (مثل کوروس) باعث می‌شود کاربر به خط اشتباه برگردد.
**راه‌حل:** استفاده از `Map` برای نگاشت مستقیم `index` به `eventId`.

```javascript
// static/js/handlers/LineHandler.js - نسخه اصلاح شده کامل
import { EventFactory } from '../modules/EventFactory.js';

export class LineHandler {
    constructor(project, onSyncUpdateCallback) {
        this.project = project;
        this.onSyncUpdateCallback = onSyncUpdateCallback || (() => {});
        this.rawLines = [];
        this.currentIndex = -1;
        this.activeEventId = null;
        this.lineToEventMap = new Map(); // FIX: نگاشت مستقیم ایندکس به eventId
    }

    setRawLyrics(text) {
        // FIX: پشتیبانی از CRLF و حذف فضاهای اضافی
        this.rawLines = text.split(/\r?\n/).map(l => l.trim()).filter(l => l.length > 0);
        this.currentIndex = -1;
        this.activeEventId = null;
        this.lineToEventMap.clear();
        this.onSyncUpdateCallback(this);
    }

    nextLine(currentTime) {
        if (this.rawLines.length === 0) return;

        if (this.currentIndex >= 0 && this.activeEventId) {
            const currentEvt = this.project.timeline.getEvent(this.activeEventId);
            if (currentEvt) {
                currentEvt.endTime = currentTime;
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
        const defaultEnd = Math.min(currentTime + defaultDuration, this.project.timeline.duration);
        const newEvt = EventFactory.createLyricsEvent(nextText, currentTime, defaultEnd);
        
        this.activeEventId = newEvt.id;
        this.lineToEventMap.set(this.currentIndex, newEvt.id); // FIX: ذخیره نگاشت
        this.project.timeline.addEvent(newEvt);
        this.onSyncUpdateCallback(this);
    }

    prevLine(currentTime) {
        if (this.rawLines.length === 0 || this.currentIndex <= 0) return;

        // FIX: حذف ایونت فعلی و پاک کردن نگاشت
        if (this.activeEventId) {
            this.project.timeline.removeEvent(this.activeEventId);
            this.lineToEventMap.delete(this.currentIndex);
        }

        this.currentIndex--;
        const prevEventId = this.lineToEventMap.get(this.currentIndex); // FIX: جستجوی مستقیم
        const defaultDuration = this.project.defaultLyricDuration || 3.0;
        
        if (prevEventId) {
            const existingEvt = this.project.timeline.getEvent(prevEventId);
            if (existingEvt) {
                existingEvt.endTime = Math.max(existingEvt.startTime + defaultDuration, currentTime);
                this.activeEventId = existingEvt.id;
            }
        } else {
            const newEvt = EventFactory.createLyricsEvent(
                this.rawLines[this.currentIndex], 
                Math.max(0, currentTime - defaultDuration), 
                currentTime
            );
            this.activeEventId = newEvt.id;
            this.lineToEventMap.set(this.currentIndex, newEvt.id);
            this.project.timeline.addEvent(newEvt);
        }

        this.project.timeline.notifyChange();
        this.onSyncUpdateCallback(this);
    }

    getCurrentLineText() {
        if (this.currentIndex >= 0 && this.currentIndex < this.rawLines.length) {
            return this.rawLines[this.currentIndex];
        }
        return "آماده همگام‌سازی (روی خط بعدی کلیک کنید)";
    }
}
```

### 🔴 **۲. Race Condition در `RenderService._jobs` (Critical)**
**مشکل:** دیکشنری در Python thread-safe نیست. اگر دو رندر همزمان استاتوس را آپدیت کنند، ممکن است corruption رخ دهد.
**راه‌حل:** استفاده از `threading.Lock`.

```python
# backend/services.py - بخش RenderService اصلاح شده
import threading
import time
import os
from werkzeug.utils import secure_filename
from backend.models import Project

BASE_PROJECTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "projects"))

class FileService:
    @staticmethod
    def save_uploaded_file(project_name, file_storage):
        proj_dir = FileService.get_project_dir(project_name)
        original_name = file_storage.filename
        
        # FIX: حفظ نام‌های فارسی به صورت ایمن
        import re
        safe_name = re.sub(r'[\\/:*?"<>|]', '_', original_name)
        
        dest_path = os.path.join(proj_dir, safe_name)
        counter = 1
        base, ext = os.path.splitext(safe_name)
        while os.path.exists(dest_path):
            safe_name = f"{base}_{counter}{ext}"
            dest_path = os.path.join(proj_dir, safe_name)
            counter += 1
        
        file_storage.save(dest_path)
        return safe_name

class RenderService:
    _jobs = {}
    _lock = threading.Lock()  # FIX: قفل برای ایمنی نخ‌ها

    @classmethod
    def start_render_job(cls, project: Project, engine_type="ffmpeg"):
        job_id = f"job_{int(time.time() * 1000)}"
        with cls._lock:  # FIX: نوشتن ایمن
            cls._jobs[job_id] = {
                "status": "rendering",
                "progress": 0,
                "message": "در حال آماده‌سازی رندر...",
                "output_file": None,
                "error": None,
                "created_at": time.time()
            }

        from backend.renderers import FFmpegRenderer, MoviePyRenderer

        def run():
            try:
                proj_dir = FileService.get_project_dir(project.name)
                output_filename = f"{project.name}_export.mp4"
                output_path = os.path.join(proj_dir, output_filename)

                def progress_cb(pct, msg):
                    with cls._lock:  # FIX: آپدیت ایمن
                        if job_id in cls._jobs:
                            cls._jobs[job_id]["progress"] = int(pct)
                            cls._jobs[job_id]["message"] = msg

                renderer_cls = MoviePyRenderer if engine_type == "moviepy" else FFmpegRenderer
                renderer = renderer_cls(project, proj_dir, output_path, progress_cb)
                renderer.render()

                with cls._lock:
                    cls._jobs[job_id].update({
                        "status": "completed",
                        "progress": 100,
                        "message": "رندر با موفقیت به اتمام رسید!",
                        "output_file": output_filename
                    })
            except Exception as e:
                with cls._lock:
                    cls._jobs[job_id].update({
                        "status": "error",
                        "error": str(e),
                        "message": f"خطا در رندر: {str(e)}"
                    })

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return job_id

    @classmethod
    def get_job_status(cls, job_id):
        with cls._lock:  # FIX: خواندن ایمن
            return cls._jobs.get(job_id, {"status": "not_found"})

    @classmethod
    def cleanup_old_jobs(cls, max_age_seconds=3600):
        """FIX: پاکسازی جاب‌های قدیمی برای جلوگیری از نشت حافظه"""
        now = time.time()
        with cls._lock:
            old_jobs = [jid for jid, data in cls._jobs.items() if now - data.get("created_at", 0) > max_age_seconds]
            for jid in old_jobs:
                del cls._jobs[jid]
```

### 🟡 **۳. بهینه‌سازی `getActiveEvents` با Binary Search (Performance)**
**مشکل:** استفاده از `.filter()` روی تمام ایونت‌ها در هر فریم (۶۰ بار در ثانیه) برای پروژه‌های بزرگ باعث افت فریم می‌شود.
**راه‌حل:** استفاده از جستجوی دودویی (Binary Search) چون آرایه مرتب است.

```javascript
// static/js/modules/Timeline.js - متد getActiveEvents را با این جایگزین کن
export class Timeline {
    constructor() {
        this.events = [];
        this.currentTime = 0.0;
        this.duration = 10.0;
        this.isPlaying = false;
        this.listeners = [];
        this._sortedEvents = null; // FIX: کش برای آرایه مرتب
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

    // FIX: جستجوی دودویی O(log N) به جای O(N)
    getActiveEvents(time) {
        if (this.events.length === 0) return [];
        
        const sorted = this.getSortedEvents();
        let left = 0, right = sorted.length - 1;
        const result = [];
        
        while (left <= right) {
            const mid = Math.floor((left + right) / 2);
            const evt = sorted[mid];
            
            if (evt.startTime <= time && evt.endTime >= time) {
                result.push(evt);
                // بررسی همسایه‌ها (چون ایونت‌ها ممکن است همپوشانی داشته باشند)
                let i = mid - 1;
                while (i >= 0 && sorted[i].endTime >= time) {
                    result.push(sorted[i]);
                    i--;
                }
                i = mid + 1;
                while (i < sorted.length && sorted[i].startTime <= time) {
                    result.push(sorted[i]);
                    i++;
                }
                break;
            } else if (evt.startTime > time) {
                right = mid - 1;
            } else {
                left = mid + 1;
            }
        }
        return result;
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
            if (e.endTime > maxT) maxT = e.endTime;
        }
        this.duration = maxT;
        return this.duration;
    }

    subscribe(callback) { this.listeners.push(callback); }
    notifyChange() { for (const cb of this.listeners) cb(this); }
}
```

### 🟢 **۴. اضافه کردن `defaultLyricDuration` به `Project` (Architecture)**
```javascript
// static/js/modules/Project.js
export class Project {
    constructor(name = "default_project") {
        this.name = name;
        this.resolution = [1080, 1920];
        this.fps = 30;
        this.background = "#000000";
        this.defaultLyricDuration = 4.0; // FIX: قابل تنظیم توسط کاربر
        this.timeline = new Timeline();
    }

    toDict() {
        return {
            name: this.name,
            resolution: this.resolution,
            fps: this.fps,
            background: this.background,
            defaultLyricDuration: this.defaultLyricDuration,
            duration: this.timeline.duration,
            events: this.timeline.events.map(e => e.toDict())
        };
    }

    loadFromDict(d) {
        this.name = d.name || "default_project";
        this.resolution = d.resolution || [1080, 1920];
        this.fps = d.fps || 30;
        this.background = d.background || "#000000";
        this.defaultLyricDuration = d.defaultLyricDuration || 4.0;
        
        this.timeline.events = [];
        const evts = d.events || [];
        for (const ed of evts) {
            try {
                this.timeline.events.push(Event.fromDict(ed));
            } catch (e) {
                console.warn('Failed to load event:', ed, e); // FIX: جلوگیری از کرش کل پروژه
            }
        }
        this.timeline.recalculateDuration();
        this.timeline.notifyChange();
    }
}
```

---

