# راه‌اندازی سریع SkyGround Local Agent

این راهنما برای اجرای سریع ایجنت روی Windows/VM است.

---

## 1) پیش‌نیازها

### Python

```powershell
python --version
```

Python 3.10 یا بالاتر کافی است.

### Git

```powershell
git --version
```

برای `git_status`، `git_diff` و `apply_patch` لازم است.

### یکی از مغزها

#### گزینه A: Ollama آفلاین

```powershell
ollama pull qwen2.5-coder:7b-instruct
```

#### گزینه B: API مثل GapGPT

```powershell
$env:GAPGPT_API_KEY="sk-..."
```

کلید را داخل فایل‌های پروژه ذخیره نکن.

---

## 2) ساخت config

از پوشه agent:

```powershell
cd local_cursor_agent
copy config.example.json config.json
```

### اگر می‌خواهی با Ollama شروع کنی

در `config.json`:

```json
{
  "llm_provider": "ollama",
  "model": "qwen2.5-coder:7b-instruct",
  "ollama_url": "http://localhost:11434"
}
```

### اگر می‌خواهی با GapGPT/API شروع کنی

در PowerShell:

```powershell
$env:GAPGPT_API_KEY="sk-..."
```

در `config.json`:

```json
{
  "llm_provider": "openai_compatible",
  "openai_base_url": "https://api.gapgpt.app/v1",
  "openai_api_key_env": "GAPGPT_API_KEY",
  "model": "gpt-4o"
}
```

### حالت پیشنهادی هوشمند

```json
{
  "llm_provider": "auto",
  "brain_routing_enabled": true,
  "brain_routing_simple_provider": "ollama",
  "brain_routing_complex_provider": "openai_compatible",
  "brain_routing_sensitive_provider": "ollama",
  "brain_routing_allow_api_for_sensitive": false
}
```

---

## 3) اجرای ایجنت روی پروژه

```powershell
python agent.py --config config.json --root "C:\path\to\your\project"
```

مثال:

```powershell
python agent.py --config config.json --root "C:\Users\Ali\Desktop\my-app"
```

داشبورد معمولاً اینجاست:

```text
http://127.0.0.1:8765
```

اگر dashboard_token گذاشته‌ای، با همان token وارد شو.

---

## 4) کارهای اولیه بعد از اجرا

### 4.1 Index پروژه

در CLI:

```text
/index
```

یا در شروع اجرا:

```powershell
python agent.py --config config.json --root "C:\path\to\project" --index
```

### 4.2 انتخاب Policy

در داشبورد، بخش `Policy Templates`:

- برای بررسی بدون تغییر:
  ```text
  Read-only Review
  ```

- برای پروژه Python:
  ```text
  Safe Python
  ```

- برای Node/React:
  ```text
  Safe Node
  ```

- برای شروع محافظه‌کار:
  ```text
  Cautious Manual
  ```

بعد اگر خواستی:

```text
Save Policy
```

### 4.3 تست API Chat اگر GapGPT داری

در داشبورد:

```text
External API Chat / کمک‌برنامه‌نویس
```

بزن:

```text
Preset GapGPT
```

بعد API key را در Header جایگزین کن:

```json
{
  "Authorization": "Bearer YOUR_API_KEY",
  "Content-Type": "application/json"
}
```

Prompt بزن و `Ask API` را تست کن.

---

## 5) نحوه استفاده روزمره

### از داشبورد task بده

مثلاً:

```text
ساختار پروژه را بررسی کن، تکنولوژی‌ها را تشخیص بده و فایل‌های مهم را معرفی کن.
```

یا:

```text
این خطای login را بررسی کن. قبل از تغییر فایل‌ها approval بگیر.
```

### اگر از API خارجی جواب گرفتی

بعد از `Ask API` یکی از این‌ها را بزن:

```text
Review with Agent      فقط بررسی
Implement Safely       بررسی و اعمال امن
Apply as Patch         اگر جواب API شامل patch است
```

---

## 6) راه‌اندازی چشم با log

اگر اپلیکیشن log دارد، در داشبورد مسیر log را ثبت کن:

```text
Vector Memory + Desktop Logs
Register Log
Observe Logs
Desktop State
```

فرمت log پیشنهادی:

```text
screen=LoginPage route=/login state=ready action=submit result=error message="Invalid token"
```

---

## 7) راه‌اندازی دست با shortcut در VM

اول shortcut ثبت کن:

```text
Shortcut name: open_search
Shortcut keys: Ctrl+K
Shortcut description: Open global search
```

بعد:

```text
Dry Run Shortcut
```

اگر درست بود، در Runtime Config:

```json
"enable_shortcut_execution": true,
"require_approval_for_shortcuts": false,
"shortcut_execution_dry_run": false
```

سپس:

```text
Execute Shortcut
```

---

## 8) حافظه و تزریق

برای رشد تدریجی ایجنت:

1. از داشبورد taskهای مهم را اجرا کن.
2. تجربه‌ها در `memory.sqlite` ذخیره می‌شوند.
3. در بخش `Vector Memory + Desktop Logs` بزن:

```text
Monthly Inject
```

این تجربه‌ها را وارد حافظه برداری می‌کند:

```text
.sg_agent/vector_memory.sqlite
```

---

## 9) مسیرهای داخلی که بهتر است gitignore شوند

در پروژه اصلی:

```gitignore
.sg_agent/
```

---

## 10) پیشنهاد اولین task

بعد از اجرای ایجنت، این task را از داشبورد بده:

```text
پروژه را onboarding کن: ساختار پوشه‌ها، تکنولوژی‌ها، نحوه اجرا، نحوه تست، فایل‌های مهم، ریسک‌ها و پیشنهاد policy مناسب را استخراج کن. هیچ فایلی را تغییر نده. نتیجه را به صورت خلاصه مدیریتی و فنی بده و نکات مهم را در حافظه ذخیره کن.
```