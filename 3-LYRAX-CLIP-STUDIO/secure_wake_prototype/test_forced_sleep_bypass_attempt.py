# -*- coding: utf-8 -*-
"""
⚠️ تست حمله‌ی MITM روی قابلیت force_sleep (بعد از رفع آسیب‌پذیری با امضای پاسخ مرکز)

نسخه‌ی اول این تست نشان داد که وقتی پاسخ مرکز امضا نمی‌شد، یک مهاجم Man-in-the-Middle
می‌توانست directive.force_sleep را در مسیر حذف کند. حالا که _sign_response و
_verify_center_signature اضافه شده، همان حمله را دوباره اجرا می‌کنیم تا مطمئن شویم
واقعاً مسدود شده است.
"""
import sys
sys.path.insert(0, '/home/user/secure_wake_prototype')

from device_agent import DeviceAgent
from control_center import ControlCenter

center = ControlCenter()
phone = DeviceAgent(device_id="phone-mitm-001", center_public_key_hex=center.center_public_key_bytes)
center.register_device(phone.device_id, phone.public_key_bytes)

center.flag_device_for_forced_sleep(phone.device_id, reason="تست حمله‌ی MITM روی دستور خواب")

phone.wake_up()
block = phone.build_signed_request({"mission": "کاری که نباید انجام شود"})
real_response = center.receive_block(block)

print("پاسخ واقعی مرکز:", real_response["directive"])

# شبیه‌سازی حمله‌ی Man-in-the-Middle: هکر پاسخ مرکز را روی شبکه می‌گیرد
# و قبل از رسیدن به گوشی، دستکاری می‌کند.
tampered_response = dict(real_response)
tampered_response["directive"] = {"force_sleep": False}  # هکر دستور خواب را حذف می‌کند!
tampered_response["status"] = "accepted"

print("\nپاسخ دستکاری‌شده توسط هکر (قبل از رسیدن به گوشی):", tampered_response["directive"])

phone.handle_center_response(tampered_response)
print("\nنتیجه: is_awake گوشی بعد از پردازش پاسخ دستکاری‌شده =", phone.is_awake)
print("last_forced_sleep_reason =", phone.last_forced_sleep_reason)

# معیار درست موفقیت این تست، خودِ is_awake نیست (چون از قبل به‌خاطر wake_up() کاربر
# True بود)، بلکه این است که آیا گوشی پاسخِ بدون امضای معتبر را «نادیده گرفت» یا نه.
# اگر نادیده گرفته باشد، last_forced_sleep_reason باید دقیقاً این مقدار مشخص را
# داشته باشد؛ در غیر این صورت (یعنی اگر مقدار reason واقعی مهاجم را می‌دیدیم)
# یعنی گوشی فریب خورده و پاسخ جعلی/بی‌امضا را پردازش کرده است.
attack_blocked = (phone.last_forced_sleep_reason == "IGNORED_UNSIGNED_OR_INVALID_RESPONSE")

if not attack_blocked:
    print("\n🚨 آسیب‌پذیری هنوز وجود دارد! پاسخ دستکاری‌شده (بدون امضای معتبر) پردازش شد.")
    assert False, "رگرسیون امنیتی: پاسخ بدون امضای معتبر نباید پردازش شود"
else:
    print("\n✅ رفع آسیب‌پذیری تایید شد: چون هکر امضای مرکز را نداشت (کلید خصوصی مرکز")
    print("   را در اختیار ندارد)، نتوانست یک پاسخ دستکاری‌شده با امضای معتبر بسازد.")
    print("   گوشی پاسخ فاقد امضای معتبر را کاملاً نادیده گرفت (نه force_sleep=True واقعی را")
    print("   از دست داد، نه به force_sleep=False قلابی مهاجم اعتماد کرد) و در همان وضعیت")
    print("   قبلی (بیدار، چون کاربر خودش بیدارش کرده بود) باقی ماند — یعنی این حمله‌ی")
    print("   خاص هیچ سودی برای مهاجم نداشت.")

print("\n" + "=" * 70)
print("🔬 تست کنترلی: آیا پاسخ واقعی (بدون دستکاری) هنوز درست کار می‌کند؟")
print("=" * 70)
phone.wake_up()
control_block = phone.build_signed_request({"mission": "تست کنترلی بعد از رفع باگ"})
control_response = center.receive_block(control_block)
phone.handle_center_response(control_response)
print("is_awake بعد از پاسخ واقعی و امضاشده‌ی مرکز (باید False چون flag هنوز فعال است):", phone.is_awake)
assert phone.is_awake is False
print("✅ رفتار صحیح (force_sleep واقعی) دست‌نخورده باقی مانده؛ فقط نسخه‌ی جعلی رد شد.")
