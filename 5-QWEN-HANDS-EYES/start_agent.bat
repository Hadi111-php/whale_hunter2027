@echo off
chcp 65001 >nul
echo ═════════════════════════════════════════════════════════════════
echo  🚀 در حال اجرای مغز آفلاین Qwen-Hands-Eyes (SkyGround OS)
echo ═════════════════════════════════════════════════════════════════

python main.py --config config/config.json --port 8765
pause
