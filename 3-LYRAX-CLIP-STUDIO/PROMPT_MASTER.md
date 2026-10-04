# 🎬 پرامپت مهندسی جامع و حرفه‌ای ساخت ادیتور ماژولار کلیپ (Master Architectural Prompt)

این سند حاوی **پرامپت استاندارد معماری** برای ساخت پلتفرم ویرایشگر ویدیو با روش اختصاصی شماست. می‌توانید این متن را به هر هوش مصنوعی یا برنامه‌نویسی بدهید تا دقیقاً همین سیستم را با تمام جزئیات برایتان خلق کند.

---

## 📋 متن پرامپت معماری (جهت کپی و استفاده)

> **Role & Objective:**
> You are an Expert Full-Stack Video Web Application Architect. I want you to build a professional, beautiful, parametric, modular, touch-friendly (mobile & desktop) Single-Page Web Video Editor (Clip Maker Studio) designed for vertical 9:16 (1080x1920) video output.
> 
> ### 🎯 Core UI & Workflow Requirements:
> 
> 1. **Tabbed Interface Navigation (Two Tabs):**
>    - **Tab 1 (`Main Workspace`):** Dedicated to media file selection, raw lyrics input, live canvas preview, and real-time interactive tap-to-sync recording.
>    - **Tab 2 (`Settings & Advanced Exports`):** Dedicated to parametric subtitle styling (Font Family, Font Size, Fill Color, Outline/Stroke Color, Outline Thickness, Word Speaking Rate) and generating two distinct JSON scenario exports.
> 
> 2. **Grouped Top Control Bar (Clean Layout):**
>    - **Group A (Project Storage):** Put `[Project Name Input]`, `[Create New Project ✨]`, `[Temporary Save 💾]`, and `[Restore Project 📂]` tightly grouped together in one visual box.
>    - **Group B (Playback & Sync Actions):** Put `[Start Project (Play) ▶️]`, `[Prev Line ⏪]`, `[Next Line ⏩ (Space)]`, and `[Stop ⏹️]` tightly grouped together side by side.
> 
> 3. **Top-Down Step-by-Step Layout (No Hunting/Scrolling):**
>    - At the very top of Tab 1, display **Step 1 (Media Selectors)** allowing simultaneous selection of Audio (`MP3/WAV`) and Background Media (`MP4 video OR JPG image`), side by side with **Step 2 (Raw Lyrics Paste Box)**.
>    - Right below it, place the **Live 9:16 Canvas Preview** (rendered from an offscreen 1080x1920 Full HD canvas to guarantee performance).
>    - **Crucial Mobile UX:** Directly touching the bottom border of the Canvas, place a giant Green Tap Button: `👆 تپ روی گوشی: نمایش و ثبت خط بعدی`. The user must be able to watch the canvas and tap the button with their thumb simultaneously without shifting their gaze.
> 
> 4. **Persistent Karaoke Word Bolding Effect (RTL Persian Optimized):**
>    - When a lyrics line is active on screen, words must be highlighted sequentially from right to left based on the elapsed time and `words_per_second` rate.
>    - **Persistence Rule:** Once a word turns bright white & bolded, **it must retain its bold/white highlight until the end of the line!** Do not unbold previously spoken words in the same sentence. This accumulative white bolding creates a flawless karaoke reading experience.
>    - Ensure web fonts (`Vazirmatn`, `IRANSans`, `Tahoma`) scale cleanly on canvas without jagged bitmap artifacts.
> 
> 5. **Dual JSON Export Engines (In Settings Tab):**
>    - **Export Format 1 (Standard Architectural Scenario JSON):** Must output an exact JSON structure matching this schema:
>      ```json
>      {
>        "project_metadata": {
>          "version": "1.0",
>          "base_file": "background.mp4",
>          "resolution_width": 1080,
>          "resolution_height": 1920,
>          "fps": 30
>        },
>        "timeline_events": [
>          {
>            "event_id": 1,
>            "layer_type": "overlay",
>            "content_type": "text_subtitle",
>            "source": "سلام داداش، این متن لیریکس هست",
>            "start_time": 5.0,
>            "end_time": 10.0,
>            "positioning": { "type": "relative_percentage", "x1": 0, "y1": 78, "x2": 100, "y2": 93 },
>            "font_style": { "color": "#FFF000", "size": 64, "stroke": "#000000" }
>          }
>        ]
>      }
>      ```
>    - **Export Format 2 (Word-Level Karaoke Timestamps JSON):** Must output the precise start/end time of each line, and **nested inside each line, the exact start and end timestamp of every single word** for backend karaoke rendering:
>      ```json
>      {
>        "project_name": "my_clip",
>        "export_type": "word_level_karaoke_sync",
>        "lines_sync_data": [
>          {
>            "line_index": 1,
>            "text": "سلام داداش گلم",
>            "start_time": 0.0,
>            "end_time": 3.5,
>            "words_sync": [
>              { "word": "سلام", "start": 0.0, "end": 0.8 },
>              { "word": "داداش", "start": 0.8, "end": 1.9 },
>              { "word": "گلم", "start": 1.9, "end": 3.5 }
>            ]
>          }
>        ]
>      }
>      ```
> 
> ### 🛠️ Technical Stack & Audio Sandbox Rules:
> - Use standard HTML5 `<audio>` playback unlocked via user touch/click events (crucial for iOS Safari). Do NOT route audio through complex `AudioContext` nodes during live sync mode to avoid iframe sandbox disconnections.
> - Ensure background videos use `playsinline` attribute so mobile browsers don't force native full-screen takeover.

---

## 🎁 توضیحات تکمیلی برای شما داداش گلم

این پرامپت مهندسی، تمام فلسفه، قلق‌های لمسی موبایل، حفظ بولد کلمات، چیدمان تب‌ها و ساختارهای دوگانه جیسون را در خود ذخیره کرده است. 

علاوه بر این پرامپت، **نسخه عملی عملیاتی نرم‌افزار (`studio.html`) نیز با همین ۴ آپدیت در پنجره پیش‌نمایش برایت باز شد!** می‌تونی تب‌ها و خروجی‌های دوگانه جیسون رو همین الان اونجا دانلود کنی! ❤️🌹
