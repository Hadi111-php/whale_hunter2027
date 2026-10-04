# SkyGround Agent - Next Architecture Priorities

این سند برای موارد جدیدی است که اضافه شد: تشخیص فارسی/لاتین، چشم/دست مبتنی بر shortcut/log، و رشد حافظه برداری.

## اصل‌های معماری

1. **اول متن و زبان را درست بفهمیم**
   - تشخیص فارسی/لاتین با Unicode
   - تشخیص جهت متن: RTL/LTR/Mixed
   - ذخیره language profile کنار task/memory

2. **چشم/دست دسکتاپ اول از log و shortcut استفاده کند**
   - حالت عادی: خواندن log فایل‌ها، title/state، route/screen markers
   - حرکت: فقط shortcutهای ثبت‌شده و policy‌شده
   - screenshot فقط در موارد خاص و با approval جداگانه

3. **یادگیری تدریجی**
   - هر تجربه مهم در SQLite memory ذخیره شود
   - ماهانه memoryها به vector brain تزریق شوند
   - vector brain فعلاً dependency-free hashing vector دارد، بعداً قابل جایگزینی با Ollama embeddings است

4. **امنیت قبل از استقلال**
   - secret masking
   - approval
   - policy templates
   - emergency stop
   - read-only mode

---

## فایل‌های جدید

```text
text_intelligence.py
  Unicode Persian/Latin detection
  RTL/LTR/Mixed direction
  script run splitting

vector_memory.py
  local hashed vector memory
  monthly injection interface
  future-compatible with real embeddings

desktop_io.py
  safe desktop I/O scaffolding
  shortcut registry
  log tail observation
  desktop state journal
```

---

## ترتیب ادامه توسعه

### فاز ۱ - انجام شده/شروع‌شده

- [x] Unicode Persian/Latin detection
- [x] ذخیره language profile کنار task
- [x] secret masking
- [x] API Chat -> Agent Task
- [x] task manager/dashboard
- [x] vector memory scaffold
- [x] desktop shortcut/log scaffold

### فاز ۲ - مرحله بعدی پیشنهادی

- [ ] Dashboard UI برای language profile و text direction
- [ ] ابزار agent برای `search_vector_memory`
- [ ] ابزار agent برای `monthly_inject_memory`
- [ ] Dashboard button برای monthly injection
- [ ] ابزار read desktop logs از داشبورد/agent

### فاز ۳

- [ ] Shortcut policy و اجرای shortcut با approval
- [ ] app-specific log adapters
- [ ] screenshot exceptional mode با approval و masking
- [ ] desktop state timeline

### فاز ۴

- [ ] جایگزینی vector hashing با embedding واقعی local
- [ ] تزریق ماهانه خودکار با خلاصه‌سازی LLM
- [ ] memory pruning/confidence/source tracking

---

## قرارداد log برای چشم ایجنت

برای اینکه agent بدون screenshot بفهمد کجاست، appها بهتر است logهایی شبیه این تولید کنند:

```text
2026-06-09T10:00:00 screen=LoginPage route=/login state=ready
2026-06-09T10:00:05 action=submit_login result=error message="Invalid token"
2026-06-09T10:00:10 screen=Dashboard route=/dashboard state=loaded
```

`desktop_io.py` دنبال markerهای زیر می‌گردد:

```text
route=
path=
url=
screen=
view=
window=
page=
```

---

## قرارداد shortcut

Shortcutها باید با نام و ریسک ثبت شوند:

```json
{
  "name": "open_search",
  "description": "Open global search",
  "keys": ["Ctrl", "K"],
  "app": "vscode",
  "risk": "low",
  "requires_approval": false
}
```

اجرای واقعی shortcut هنوز عمداً فعال نشده؛ باید بعداً با policy و approval اضافه شود.