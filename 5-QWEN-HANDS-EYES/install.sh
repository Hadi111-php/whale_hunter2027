#!/usr/bin/env bash
set -e

echo "═════════════════════════════════════════════════════════════════"
echo " 🧠 نصب و راه‌اندازی وابستگی‌های Qwen-Hands-Eyes"
echo "═════════════════════════════════════════════════════════════════"

python3 -m pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "✅ نصب پکیج‌ها با موفقیت انجام شد."
echo "برای شروع اجرای ایجنت، دستور ./start_agent.sh را وارد کنید."
