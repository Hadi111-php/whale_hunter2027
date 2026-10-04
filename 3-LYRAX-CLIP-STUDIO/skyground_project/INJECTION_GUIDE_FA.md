# راهنمای تزریق اولیه و رشد حافظه ایجنت

هدف تزریق این است که ایجنت زودتر پروژه، سبک کاری تو، مسیرهای مهم، خطاهای پرتکرار و تصمیم‌های قبلی را یاد بگیرد.

---

## 1) تزریق یعنی چه؟

در این سیستم سه سطح حافظه داریم:

```text
1. memory.sqlite
   حافظه خام تجربه‌ها، taskها، نتیجه‌ها، تصمیم‌ها

2. vector_memory.sqlite
   حافظه برداری برای پیدا کردن تجربه‌های مرتبط

3. prompt/context runtime
   چیزی که در هر task به مغز داده می‌شود
```

تزریق یعنی انتقال تجربه‌های مهم به لایه‌ای که agent بتواند بعداً سریع‌تر بازیابی کند.

---

## 2) تزریق اولیه پروژه

اولین task پیشنهادی در داشبورد:

```text
پروژه را onboarding کن. فقط بخوان و تحلیل کن، هیچ تغییری اعمال نکن.
موارد زیر را استخراج کن:
1. تکنولوژی‌ها و frameworkها
2. ساختار پوشه‌ها
3. فایل‌های مهم
4. نحوه اجرا
5. نحوه تست و build
6. مسیرهای حساس مثل .env و configها
7. policy پیشنهادی برای این پروژه
8. خطاها یا ریسک‌های احتمالی
9. چیزهایی که باید در حافظه بلندمدت ذخیره شوند
در پایان، موارد مهم را با ابزار remember و add_vector_memory ذخیره کن.
```

اگر می‌خواهی مطمئن‌تر باشد، اول Policy را بگذار روی:

```text
Read-only Review
```

---

## 3) تزریق سبک کاری تو

این task را بده:

```text
این‌ها ترجیحات کاری من هستند. آن‌ها را به عنوان user_preferences و project_workflow در حافظه ذخیره کن:
- پاسخ‌ها فارسی باشد مگر اینکه کد یا اصطلاح فنی انگلیسی لازم باشد.
- قبل از تغییر فایل‌ها diff نشان بده.
- برای کارهای حساس از approval داشبورد استفاده کن.
- برای پروژه‌های کدنویسی اول git_status بگیر.
- برای خطاها اول فایل‌های مرتبط را بخوان، بعد patch پیشنهاد بده.
- secretها و .env نباید به API خارجی فرستاده شوند.
```

---

## 4) تزریق دستورات اجرای پروژه

بعد از اینکه فهمیدی پروژه چطور اجرا می‌شود، یک task بده:

```text
نحوه اجرای پروژه، تست، build و lint را از فایل‌های پروژه استخراج کن و در حافظه ذخیره کن. اگر مطمئن نیستی، سوال بپرس. هیچ commandی را بدون approval اجرا نکن.
```

نمونه حافظه مطلوب:

```text
project_run_command: npm run dev
project_test_command: npm test
project_build_command: npm run build
project_lint_command: npm run lint
```

---

## 5) تزریق log چشم ایجنت

اگر اپ log دارد، بهتر است logها markerدار باشند:

```text
app=myapp screen=LoginPage route=/login state=ready action=submit result=error message="Invalid token"
```

بعد در داشبورد:

```text
Register Log
Observe Logs
Desktop State
```

سپس task بده:

```text
log observationهای اخیر را تحلیل کن و الگوی موقعیت‌یابی اپ را به حافظه برداری اضافه کن. توضیح بده screen/route/stateهای شناخته‌شده کدامند.
```

---

## 6) تزریق ماهانه

هر ماه یا بعد از چند روز کار جدی:

در داشبورد:

```text
Monthly Inject
```

یا task بده:

```text
تجربه‌های مهم این ماه را خلاصه کن، موارد تکراری و تصمیم‌های مهم را جدا کن، و آن‌ها را به vector memory تزریق کن.
```

---

## 7) تزریق خطاهای پرتکرار

هر بار خطایی حل شد، این را از agent بخواه:

```text
این مشکل حل شد. لطفاً root cause، فایل‌های درگیر، راه‌حل، تست انجام‌شده و نشانه‌های تشخیص آینده را به حافظه و vector memory اضافه کن.
```

---

## 8) تزریق shortcutها

برای چشم/دست، shortcutها باید ثبت شوند:

نمونه:

```text
name: open_search
keys: Ctrl+K
description: Open global search
app: vscode
risk: low
```

بعد:

```text
Dry Run Shortcut
```

اگر درست بود، در VM می‌توانی execution را فعال کنی.

---

## 9) چک‌لیست سریع تزریق برای پروژه جدید

```text
[ ] config.json آماده شد
[ ] dashboard باز شد
[ ] policy مناسب انتخاب شد
[ ] /index اجرا شد
[ ] onboarding task اجرا شد
[ ] run/test/build commands ذخیره شد
[ ] log pathها ثبت شدند
[ ] shortcutهای مهم ثبت شدند
[ ] Monthly Inject انجام شد
```

---

## 10) اگر خواستی من کمک کنم

تو می‌توانی ساختار پروژه یا README یا package.json/pyproject را بدهی، من برایت:

- taskهای تزریق مناسب می‌نویسم
- policy مناسب پیشنهاد می‌دهم
- log marker استاندارد طراحی می‌کنم
- shortcut registry اولیه می‌سازم
- promptهای onboarding مخصوص همان پروژه را آماده می‌کنم