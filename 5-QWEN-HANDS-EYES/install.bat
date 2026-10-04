@echo off
chcp 65001 >nul
echo ═════════════════════════════════════════════════════════════════
echo  🧠 نصب و راه‌اندازی وابستگی‌های Qwen-Hands-Eyes
echo ═════════════════════════════════════════════════════════════════

python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo ✅ نصب پکیج‌ها به پایان رسید.
echo برای اجرای ایجنت، فایل start_agent.bat را اجرا کنید.
pause
