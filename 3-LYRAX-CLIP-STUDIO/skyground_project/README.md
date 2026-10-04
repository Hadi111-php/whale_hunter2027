# SkyGround Local Cursor-like Coding Agent v3

یک ایجنت برنامه‌نویسی محلی برای **Windows + Ollama**؛ شبیه نسخه‌ی ساده، قابل توسعه و قابل نظارت از Cursor Agent.

نسخه ۳ علاوه بر ابزارهای کدنویسی، یک **داشبورد ادمین** هم دارد برای:

- ثبت task از داشبورد و اجرای صفی توسط ایجنت
- Reflex/Skill Layer برای اجرای سریع دستورات پایه مثل «کپی کن»، `save` و `git status` بدون مغز بزرگ
- API Playground برای صدا زدن API خارجی/لینک prompt و تبدیل پاسخ به task
- Secret Scanner/Masking برای جلوگیری از نمایش token/key/password در log/diff/memory
- نظارت زنده روی وضعیت ایجنت
- Admin Token اختیاری برای محافظت داشبورد
- Pause/Resume/Cancel/Emergency Stop
- تأیید یا رد عملیات خطرناک مثل write/edit/command
- پرسش/پاسخ بین ایجنت و ادمین
- دادن دسترسی موقت و granular مثل فقط `src/**` یا فقط `python -m pytest*`
- تغییر پارامترهای runtime مثل مدل، temperature، max_steps بدون restart

---

## معماری

```text
User / Admin
  ↓
CLI + Admin Dashboard + API Playground
  ↓
Local Coding Agent
  ↓
Ollama Local Model = مغز آفلاین
  ↓
Tools = چشم و دست
  - list_dir / read_file        دیدن پروژه و فایل‌ها
  - search_project / index      جستجوی پروژه و symbolها
  - write_file / edit_file      ویرایش امن با diff و backup
  - apply_patch                 patch چندفایلی با unified diff
  - git_status / git_diff       آگاهی از وضعیت Git
  - run_command                 اجرای تست/فرمان با approval
  - ask_admin                   پرسش از ادمین از داشبورد
  - remember / search_memory    حافظه تجربه محلی
  ↓
SQLite Memory + Project Index
```

---

## قابلیت‌های اصلی

### 0) Task Manager از داشبورد

داشبورد حالا فقط مرکز نظارت نیست؛ مرکز فرماندهی هم هست.

از داخل داشبورد می‌توانی:

```text
Submit Task
Pause
Resume
Cancel Task
Emergency Stop
Clear Stop
```

Taskها status دارند:

```text
queued
running
cancelling
completed
failed
cancelled
```

ایجنت taskهای ثبت‌شده از داشبورد را در یک worker پس‌زمینه، یکی‌یکی اجرا می‌کند. اگر task وسط کار نیاز به approval یا سؤال داشته باشد، همان داشبورد آن را مدیریت می‌کند.

`Emergency Stop` این کارها را انجام می‌دهد:

- approvalهای pending را reject می‌کند.
- سؤال‌های pending را expire می‌کند.
- policy را به read-only mode می‌برد.
- taskهای queued/running را cancel می‌کند.
- اجرای task بعد از نقطه امن بعدی متوقف می‌شود.

### 0.1) Admin Injection Center

در داشبورد بخشی اضافه شده است:

```text
Admin Injection Center
```

از اینجا می‌توانی هم دستی و هم از طریق فایل، داده آموزشی به ایجنت تزریق کنی:

```text
متن ساده → memory.sqlite و vector_memory.sqlite
JSON bundle → memory + vector + intents + skills + shortcuts
```

فایل در مرورگر خوانده می‌شود و محتوا به agent فرستاده می‌شود. فرمت JSON bundle نمونه:

```json
{
  "memories": [
    {"kind": "user_preference", "text": "پاسخ‌ها فارسی باشند."}
  ],
  "intents": [
    {"id": "browser.refresh", "description": "Refresh page", "aliases": ["refresh", "رفرش", "ctrl+r"]}
  ],
  "shortcuts": [
    {"name": "refresh", "description": "Refresh active page", "keys": ["Ctrl", "R"], "risk": "low"}
  ],
  "skills": [
    {"id": "shortcut.refresh", "intent": "browser.refresh", "executor": "execute_shortcut", "args": {"name": "refresh"}, "safety_level": "fast"}
  ]
}
```

دکمه `Sample Bundle` همین نمونه را داخل داشبورد آماده می‌کند.

### 0.25) Reflex / Skills؛ چهار دست و پای ایجنت

برای اینکه ایجنت برای کارهای پایه هر بار سراغ مغز بزرگ نرود، یک لایه Reflex اضافه شده است.

این لایه دستورهایی مثل این‌ها را local تشخیص می‌دهد:

```text
کپی کن
copy
ذخیره کن
save
git status
observe logs
```

و آن‌ها را به intent و skill تبدیل می‌کند:

```text
کپی کن → clipboard.copy → shortcut.copy → Ctrl+C
ذخیره کن → file.save_active → shortcut.save → Ctrl+S
git status → git.status → git_status tool
```

فایل‌های مربوطه:

```text
.sg_agent/intents.json
.sg_agent/skills.json
.sg_agent/events/YYYY-MM-DD.jsonl
```

در داشبورد بخش جدیدی هست:

```text
Reflex / Skills
```

دکمه‌ها:

```text
Resolve          فقط تشخیص intent/skill
Dry Run          تست بدون اجرای واقعی
Execute          اجرای skill
List Skills      دیدن مهارت‌ها
Event Counts     شمارش رویدادها
Daily Distill    خلاصه و پیشنهاد یادگیری روزانه
Distill + Apply  اعمال پیشنهادهای امن مثل trusted کردن skillهای موفق
```

نمونه تست:

```text
Reflex command: کپی کن
Dry Run
```

باید ببینی:

```text
intent = clipboard.copy
skill = shortcut.copy
sendkeys = ^c
```

این همان مرحله «چهار دست و پا رفتن» ایجنت است: اول مهارت‌های پایه، بعد رشد و اعتماد بیشتر.

### 0.4) Project Factory / Scaffold Mode

برای ساخت پروژه از صفر، داشبورد بخش جدید دارد:

```text
Project Factory
```

از اینجا می‌توانی بدون VS Code UI، مستقیم پروژه بسازی. اول `Preview / Dry Run` را بزن، بعد اگر درست بود `Create Project`.

Templateهای اولیه:

```text
python_flask_site
python_fastapi_api
static_html_site
python_cli_tool
```

مثلاً برای درخواست «یک وب‌سایت با پایتون بساز»، template مناسب:

```text
python_flask_site
```

خروجی نمونه:

```text
my_site/
  app.py
  requirements.txt
  README.md
  templates/index.html
  static/style.css
```

ساخت پروژه با یک preview/diff کلی انجام می‌شود و برای اعمال، approval می‌گیرد مگر اینکه policy را کم‌سخت‌گیر کرده باشی.

### 0.5) External API Chat برای لینک/API خارجی

اگر از یک سایت API گرفته‌ای و با PowerShell به آن prompt می‌فرستی، حالا می‌توانی همان را از داشبورد راحت‌تر و شبیه چت استفاده کنی.

در بخش زیر:

```text
External API Chat / کمک‌برنامه‌نویس
```

می‌توانی وارد کنی:

- Endpoint URL
- Method: `POST` یا `GET`
- Headers JSON مثل Authorization
- Body template با placeholderهای زیر:

```text
{{prompt_json}}   امن برای قرار گرفتن داخل JSON
{{prompt}}        متن خام prompt
```

مثلاً Body template پیشنهادی برای API ساده:

```json
{"prompt":{{prompt_json}}}
```

برای APIهای OpenAI-compatible مثل GapGPT:

```json
{
  "model": "{{model}}",
  "messages": [
    {
      "role": "user",
      "content": {{prompt_json}}
    }
  ]
}
```

و Response JSON path معمولاً این است:

```text
choices.0.message.content
```

امکانات این بخش:

- Preset آماده برای OpenAI-compatible API
- Preset آماده برای GapGPT
- فیلد Model با placeholderهای `{{model}}` و `{{model_json}}`
- System/Instruction اختصاصی برای API
- Context/Code برای paste کردن کد یا خطا
- Quick prompts مثل Analyze، Generate Code، Debug، Write Tests، Refactor
- Chat history محلی در مرورگر
- Response JSON path برای استخراج جواب تمیز، مثل:

```text
answer
text
choices.0.message.content
```

دکمه‌ها:

```text
Ask API                  ارسال سوال به API
Use Response as Agent Task تبدیل جواب API به task برای agent داخلی
Copy Response             کپی جواب
Clear Chat                پاک‌کردن تاریخچه local
```

`Use Response as Agent Task` پاسخ API را به عنوان context به agent داخلی می‌دهد تا اگر لازم بود فایل‌های پروژه را بخواند، diff بسازد و با approval تغییرات را اعمال کند.

نکته امنیتی: headerها و endpointهای دارای token در event log تا حد ممکن mask می‌شوند، اما بهتر است API key را در repo ذخیره نکنی.

### 0.75) Secret Scanner / Masking

برای امنیت بیشتر، سیستم ماسک‌کردن secret اضافه شده است. به‌صورت پیش‌فرض فعال است و قبل از نمایش/ذخیره در بخش‌های حساس، مقدارهایی مثل این‌ها را mask می‌کند:

```text
API keys
Bearer tokens
passwordها
secretها
private key blockها
DATABASE_URL / DB_URL
GitHub/OpenAI/Google/Slack tokenهای رایج
```

مثلاً:

```text
OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz
```

در داشبورد/log/context به شکل زیر دیده می‌شود:

```text
OPENAI_API_KEY=sk-a…[SECRET_MASKED]
```

محل‌هایی که masking اعمال می‌شود:

- `read_file` output
- project index preview/snippets
- dashboard event log
- approval diff/patch preview
- command stdout/stderr
- git diff/status output
- memory database
- task snapshot در داشبورد
- raw model output هنگام نمایش در CLI

تنظیمات مربوطه در `config.json`:

```json
"mask_secrets": true,
"mask_secrets_in_memory": true,
"block_sensitive_file_reads": false,
"sensitive_file_globs": [
  ".env",
  ".env.*",
  "**/.env",
  "**/.env.*",
  "*.pem",
  "*.key",
  "**/secrets/**"
]
```

اگر `block_sensitive_file_reads` را `true` کنی، خواندن فایل‌هایی مثل `.env` به‌کلی block می‌شود. اگر `false` باشد، محتوا خوانده می‌شود ولی secretها mask می‌شوند.

### 1) Admin Dashboard

داشبورد به‌صورت local روی سیستم خودت اجرا می‌شود:

```text
http://127.0.0.1:8765
```

در داشبورد می‌بینی و کنترل می‌کنی:

- ثبت task جدید
- pause/resume/cancel/emergency stop
- وضعیت agent: idle/running/stop
- مدل فعال
- task فعلی
- uptime
- project index summary
- git status
- pending approvals
- pending asks
- event log زنده
- runtime config
- session permissions
- policy templates
- save/load policy از فایل `.sg_agent/policy.json`

### 1.5) Admin Token اختیاری

اگر در `config.json` مقدار زیر را پر کنی:

```json
"dashboard_token": "یک-رمز-طولانی-ایمن"
```

داشبورد بدون token باز نمی‌شود و یک صفحه ورود نشان می‌دهد. APIهای داشبورد هم نیاز به token دارند.

اگر مقدار خالی باشد:

```json
"dashboard_token": ""
```

داشبورد بدون login کار می‌کند. برای استفاده جدی، مخصوصاً اگر host را از `127.0.0.1` تغییر می‌دهی، حتماً token بگذار.

### 2) Approval Queue

هر وقت ایجنت بخواهد عملیات حساس انجام دهد، درخواست در داشبورد می‌آید:

- `write_file`
- `edit_file`
- `edit_file_multi`
- `apply_patch`
- `run_command`

ادمین می‌تواند:

- Approve
- Reject
- reason بنویسد

تا وقتی approval نیاید، اجرای همان ابزار pause می‌شود.

### 3) Patch Engine چندفایلی

ابزار `apply_patch` می‌تواند یک unified diff چندفایلی را با `git apply --check` بررسی کند، بعد patch را در داشبورد برای approval نشان دهد، backup بگیرد و اعمال کند.

این برای تغییرات هماهنگ بین چند فایل حرفه‌ای‌تر از `old_text/new_text` است.

### 4) Ask Admin

ایجنت می‌تواند وسط کار از ادمین سؤال بپرسد، مثلاً:

```text
آیا اجازه دارم full test suite را اجرا کنم؟
```

یا:

```text
بین refactor کامل و fix کوچک کدام را ترجیح می‌دهی؟
```

این سؤال در داشبورد نمایش داده می‌شود و ادمین پاسخ می‌دهد.

### 5) Session Permissions / Granular Grant Access

در داشبورد می‌توانی برای همان session دسترسی موقت و جزئی بدهی:

- `Read-only mode`
  - همه write/edit/commandها رد می‌شوند.

- `Auto-approve writes`
  - write/edit/apply_patchها فقط طبق policy تأیید خودکار می‌شوند.

- `Allowed write globs`
  - مثال:
    ```text
    src/**
    README.md
    ```

- `Denied write globs`
  - مثال:
    ```text
    .env
    **/secrets/**
    ```

- `Reject write/edit خارج از allowlist`
  - اگر فعال باشد، مسیرهای خارج از allowlist حتی approval دستی هم نمی‌گیرند و مستقیم reject می‌شوند.

- `Auto-approve commands`
  - commandها فقط طبق policy تأیید خودکار می‌شوند.

- `Allowed command globs`
  - مثال:
    ```text
    python -m pytest*
    npm test*
    npm run build*
    ```

- `Denied command fragments`
  - مثال:
    ```text
    rm -rf
    del /s
    format 
    ```

- `Reject command خارج از allowlist`
  - اگر فعال باشد، commandهای خارج از allowlist مستقیم reject می‌شوند.

- `Auto-answer questions`
  - سؤال‌های ask_admin با پاسخ ثابت جواب داده می‌شوند.

قانون مهم:

```text
Deny > Reject unmatched > Auto approve > Manual approval
```

> توصیه امنیتی: برای اتوماسیون امن، auto-approve را فقط همراه allowlist محدود و reject unmatched فعال کن.

### 6) Policy Templates + Save/Load

در داشبورد چند template آماده اضافه شده است:

- `Cautious Manual`
  - همه عملیات حساس approval دستی می‌خواهند.

- `Read-only Review`
  - همه write/edit/commandها reject می‌شوند.

- `Safe Python`
  - commandهای امن Python مثل `python -m pytest*` و `ruff check*` auto-approve می‌شوند.

- `Safe Node`
  - commandهای امن Node مثل `npm test*` و `npm run build*` auto-approve می‌شوند.

- `Docs Only`
  - فقط فایل‌های markdown/docs auto-approve می‌شوند.

- `Src + Tests Development`
  - فقط `src/**` و `tests/**` قابل ویرایش خودکار هستند و test/buildهای رایج مجازند.

در داشبورد می‌توانی:

```text
Apply Template
Merge Template
Save Policy
Load Policy
Reset Session
```

Policy ذخیره‌شده در workspace پروژه قرار می‌گیرد:

```text
.sg_agent/policy.json
```

اگر `auto_load_policy` در config روشن باشد، policy در شروع اجرای بعدی خودکار load می‌شود.

### 7) Vector Memory + Desktop Logs

در داشبورد بخش جدیدی اضافه شده است:

```text
Vector Memory + Desktop Logs
```

این بخش برای رشد تدریجی ایجنت و چشم/دست امن طراحی شده است.

#### Vector Memory

امکانات:

```text
Search Vector Memory
Monthly Inject
```

`Monthly Inject` تجربه‌های ذخیره‌شده در حافظه SQLite را به حافظه برداری تزریق می‌کند تا agent کم‌کم الگوهای تکراری را بهتر پیدا کند.

فعلاً vector memory با روش dependency-free hashing vector ساخته شده؛ بعداً می‌توان آن را با embedding واقعی محلی مثل Ollama embeddings جایگزین کرد.

#### Desktop Logs / Eye

ایجنت می‌تواند log فایل‌های اپلیکیشن‌ها را به عنوان چشم امن بخواند:

```text
Register Log
Observe Logs
```

مثلاً اگر اپ log بدهد:

```text
screen=LoginPage route=/login state=ready
```

ایجنت می‌تواند بفهمد کجاست، بدون screenshot.

دکمه `Desktop State` در داشبورد، موقعیت فعلی اپ‌ها را به صورت کارت و timeline نشان می‌دهد:

```text
Current app
Current screen
Current route
Current state
Last action/result/message
Confidence score
Timeline
```

#### Shortcut Registry / Hand

shortcutها ثبت، پیشنهاد و در صورت فعال بودن، اجرا می‌شوند:

```text
Register Shortcut
Suggest Shortcut
Dry Run Shortcut
Execute Shortcut
```

اجرای shortcut فقط برای shortcutهای ثبت‌شده است؛ هیچ کلیک آزاد یا تایپ آزاد وجود ندارد. برای تست امن اول `Dry Run Shortcut` را بزن. روی Windows اجرای واقعی با PowerShell/WScript SendKeys انجام می‌شود.

تنظیمات مربوطه:

```json
"enable_shortcut_execution": false,
"require_approval_for_shortcuts": true,
"shortcut_execution_dry_run": false,
"shortcut_execution_method": "powershell_sendkeys",
"shortcut_execution_delay_ms": 120,
"min_desktop_confidence_for_shortcut": 0.0,
"allow_shortcut_without_desktop_state": true
```

برای محیط VM که خودت گفتی و کنترلش دست توست، می‌توانی روان‌تر تنظیم کنی:

```json
"enable_shortcut_execution": true,
"require_approval_for_shortcuts": false,
"min_desktop_confidence_for_shortcut": 0.0,
"allow_shortcut_without_desktop_state": true
```

### 8) Runtime Config Hot Update

از داشبورد می‌توانی بدون restart این‌ها را تغییر بدهی:

- `llm_provider`: `ollama`، `openai_compatible` یا `auto`
- `model`
- `ollama_url`
- `openai_base_url`
- تنظیمات Smart Brain Routing
- `openai_api_key_env`
- `openai_timeout_sec`
- `openai_max_tokens`
- `temperature`
- `num_ctx`
- `max_steps`
- `max_file_read_chars`
- `command_timeout_sec`
- `require_approval_for_writes`
- `require_approval_for_commands`

این تغییرات روی runtime فعلی اعمال می‌شوند. اگر می‌خواهی دائمی شوند، بعداً همان مقدارها را در `config.json` هم ذخیره کن.

---

## نصب پیش‌نیازها در Windows

### 1) Python

Python 3.10+ نصب باشد:

```powershell
python --version
```

### 2) Ollama

Ollama را نصب کن:

https://ollama.com/download

بعد مدل کدنویسی بگیر:

```powershell
ollama pull qwen2.5-coder:7b-instruct
```

اگر سیستم ضعیف‌تر است:

```powershell
ollama pull qwen2.5-coder:3b
```

اگر سیستم قوی‌تر است:

```powershell
ollama pull qwen2.5-coder:14b-instruct
```

تست:

```powershell
ollama run qwen2.5-coder:7b-instruct
```

### استفاده از API به‌جای Ollama، مثل GapGPT

اگر می‌خواهی مغز اصلی agent به‌جای Ollama از API سازگار با OpenAI استفاده کند، در PowerShell اول API key را در environment بگذار:

```powershell
$env:GAPGPT_API_KEY="sk-..."
```

بعد در `config.json` این مقدارها را بگذار:

```json
{
  "llm_provider": "openai_compatible",
  "openai_base_url": "https://api.gapgpt.app/v1",
  "openai_api_key_env": "GAPGPT_API_KEY",
  "model": "gpt-4o",
  "temperature": 0.2
}
```

نکته: `openai_base_url` باید base باشد، یعنی:

```text
https://api.gapgpt.app/v1
```

خود agent به‌صورت داخلی `/chat/completions` را اضافه می‌کند.

توصیه امنیتی: API key را مستقیم داخل `config.json` نگذار مگر برای تست کوتاه. بهتر است از env var استفاده کنی.

### Smart Brain Routing

اگر می‌خواهی agent خودش بین مغز محلی و API تصمیم بگیرد:

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

منطق پیش‌فرض:

```text
کار ساده یا خصوصی‌تر       → Ollama
کار پیچیده کدنویسی/دیباگ   → API مثل GapGPT
کار حساس شامل token/.env   → فقط Ollama
```

اگر API key تنظیم نشده باشد، route مربوط به API به Ollama fallback می‌کند.

در داشبورد، Task Manager حالا برای هر task نشان می‌دهد:

```text
Brain provider: ollama یا openai_compatible
Reason: simple_task / complex_task / sensitive_local_policy
Sensitive: yes/no
Complex: yes/no
Fallback reason در صورت نیاز
Language profile: فارسی/لاتین/mixed
```

---

## اجرا

از پوشه‌ی agent:

```powershell
cd local_cursor_agent
copy config.example.json config.json
python agent.py --config config.json --root "C:\path\to\your\project"
```

مثال:

```powershell
python agent.py --config config.json --root "C:\Users\Ali\Desktop\my-app"
```

اگر dashboard فعال باشد، در خروجی می‌بینی:

```text
Dashboard: http://127.0.0.1:8765
```

بعد این آدرس را در مرورگر باز کن.

برای index کردن قبل از شروع:

```powershell
python agent.py --config config.json --root "C:\Users\Ali\Desktop\my-app" --index
```

یا داخل خود CLI:

```text
/index
```

---

## دستورهای محلی داخل CLI

```text
/help              نمایش راهنما
/index             ساخت/بازسازی index پروژه
/status            git status
/diff              git diff کل پروژه
/diff path/file.py git diff برای یک فایل
/search QUERY      جستجو در project index
/memory QUERY      جستجو در حافظه تجربه
/summary           خلاصه index
/dashboard         نمایش آدرس داشبورد
exit               خروج
```

---

## نمونه دستورها به ایجنت

```text
ساختار پروژه را بررسی کن و بگو از چه تکنولوژی‌هایی استفاده شده.
```

```text
در پروژه دنبال بخش login بگرد، فایل‌های مرتبط را بخوان و توضیح بده جریان ورود کاربر چطور کار می‌کند.
```

```text
این خطا را پیدا کن و اگر نیاز به اجرای تست داشتی از ادمین اجازه بگیر: Cannot read property 'token' of undefined
```

```text
README پروژه را بهتر کن. قبل از اعمال تغییر diff را نشان بده و منتظر approval ادمین بمان.
```

```text
وضعیت git و diff را بررسی کن و خلاصه کن چه تغییراتی انجام شده.
```

---

## تنظیمات مهم در config.json

```json
{
  "llm_provider": "ollama",
  "ollama_url": "http://localhost:11434",
  "openai_base_url": "https://api.gapgpt.app/v1",
  "openai_api_key_env": "GAPGPT_API_KEY",
  "openai_api_key": "",
  "openai_timeout_sec": 600,
  "openai_max_tokens": 0,
  "model": "qwen2.5-coder:7b-instruct",
  "temperature": 0.2,
  "num_ctx": 8192,
  "max_steps": 8,

  "enable_dashboard": true,
  "dashboard_host": "127.0.0.1",
  "dashboard_port": 8765,
  "dashboard_token": "",
  "approval_timeout_sec": 0,
  "policy_file": ".sg_agent/policy.json",
  "auto_load_policy": true,
  "vector_memory_file": ".sg_agent/vector_memory.sqlite",
  "vector_dimensions": 384,
  "desktop_state_file": ".sg_agent/desktop_state.json",

  "require_approval_for_writes": true,
  "require_approval_for_commands": true,
  "create_backups": true,
  "mask_secrets": true,
  "mask_secrets_in_memory": true,
  "block_sensitive_file_reads": false,

  "auto_index_on_start": false
}
```

`approval_timeout_sec = 0` یعنی approvalها timeout ندارند و تا پاسخ ادمین منتظر می‌مانند.

---

## حافظه و فایل‌های داخلی

ایجنت داخل workspace پروژه این پوشه را می‌سازد:

```text
.sg_agent/
  memory.sqlite
  vector_memory.sqlite
  desktop_state.json
  intents.json
  skills.json
  policy.json
  events/
    YYYY-MM-DD.jsonl
  distillations/
    YYYY-MM-DD.json
  backups/
```

داخل `memory.sqlite` هم حافظه‌ی مکالمه/تجربه و هم project index ذخیره می‌شود.

پیشنهاد: این مسیر را به `.gitignore` اضافه کن:

```gitignore
.sg_agent/
```

---

## امنیت

این نسخه محافظه‌کار طراحی شده:

- از workspace root بیرون نمی‌رود.
- برای write/edit از ادمین approval می‌گیرد.
- برای command از ادمین approval می‌گیرد.
- چند دستور خطرناک block شده‌اند.
- Git tools فقط read-only هستند.
- backup قبل از تغییر فایل ساخته می‌شود.
- dashboard فقط روی `127.0.0.1` اجرا می‌شود، مگر خودت host را تغییر بدهی.

با این حال، برای استفاده جدی:

1. روی branch جدا کار کن.
2. `.sg_agent/` را gitignore کن.
3. auto-approve را با احتیاط فعال کن.
4. قبل از merge، `git diff` را دستی هم بررسی کن.

---

## فایل‌های مهم

```text
local_cursor_agent/
  agent.py              # هسته ایجنت و ابزارها
  dashboard.py          # داشبورد ادمین و approval/ask/config API
  security.py           # secret scanner/masking و sensitive path helpers
  text_intelligence.py  # تشخیص Unicode فارسی/لاتین و جهت متن
  vector_memory.py      # حافظه برداری محلی و تزریق ماهانه تجربه‌ها
  desktop_io.py         # چشم/دست امن مبتنی بر log و shortcut registry
  intent_registry.py    # تشخیص intent و aliasهای فارسی/انگلیسی
  skill_registry.py     # مهارت‌های پایه، safety level، confidence و آمار استفاده
  reflex_engine.py      # اجرای local intent→skill بدون مغز بزرگ
  event_journal.py      # ثبت JSONL رویدادها برای یادگیری روزانه
  daily_distiller.py    # تحلیل روزانه eventها و پیشنهاد یادگیری
  project_scaffolds.py  # templateهای ساخت پروژه از صفر
  config.example.json   # تنظیمات نمونه
  README.md             # راهنما
```

---

## مسیر توسعه بعدی

مرحله‌های بعدی پیشنهادی:

1. **ذخیره دائمی runtime config از داشبورد** با backup/rollback
2. **Policy editor پیشرفته‌تر** با import/export و history
3. **Patch engine پیشرفته‌تر** با parser داخلی و rollback خودکار
4. **تست‌رانر هوشمند** بر اساس نوع پروژه
5. **RAG/Embedding محلی** برای جستجوی معنایی پروژه
6. **داشبورد پیشرفته‌تر با WebSocket** به‌جای polling
7. **Desktop eye/hand** با screenshot/OCR/pyautogui، با approval سخت‌گیرانه