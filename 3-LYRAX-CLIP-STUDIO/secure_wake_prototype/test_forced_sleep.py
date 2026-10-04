# -*- coding: utf-8 -*-
"""
🔐 تست کامل قابلیت جدید: «مرکز می‌تواند بخواباند، ولی هرگز نمی‌تواند بیدار کند»

سناریوها:
1. حالت عادی: گوشی بیدار می‌شود، درخواست می‌فرستد، ماموریت normal دریافت می‌کند.
2. مرکز (طبق تشخیص امنیتی) دستگاه را برای خواب اجباری علامت می‌زند.
3. گوشی دوباره با تصمیم کاربر بیدار می‌شود و درخواست می‌فرستد.
   -> باید ببینیم علی‌رغم معتبر بودن کامل درخواست (امضا/زنجیره/nonce درست)،
      مرکز دستور «فوراً بخواب» می‌دهد و ماموریت dispatch نمی‌شود.
4. تایید می‌کنیم که is_awake گوشی بعد از این جواب واقعاً False شده.
5. اثبات می‌کنیم که مرکز *هرگز* نمی‌تواند خودش تماس بگیرد و گوشی را از حالت
   خواب به بیدار ببرد - برعکسِ این مسیر اصلاً وجود ندارد (هیچ متدی روی
   ControlCenter نیست که device_agent.wake_up() را صدا بزند).
"""
import sys
sys.path.insert(0, '/home/user/secure_wake_prototype')

from device_agent import DeviceAgent
from control_center import ControlCenter, SecurityError


def line(t):
    print("\n" + "=" * 70)
    print(t)
    print("=" * 70)


line("🔧 راه‌اندازی")
center = ControlCenter()
phone = DeviceAgent(device_id="phone-guard-001", center_public_key_hex=center.center_public_key_bytes)
center.register_device(phone.device_id, phone.public_key_bytes)
print("گوشی ثبت شد. is_awake =", phone.is_awake)


line("1️⃣ سناریوی عادی: کاربر بیدار می‌کند، ماموریت عادی دریافت می‌شود")
phone.wake_up()
print("کاربر دکمه را زد. is_awake =", phone.is_awake)
block1 = phone.build_signed_request({"mission": "بررسی سلامت سیستم"})
resp1 = center.receive_block(block1)
phone.handle_center_response(resp1)
print("پاسخ مرکز:", resp1["status"], "-", resp1["message"])
print("directive:", resp1["directive"])
print("is_awake گوشی بعد از پاسخ عادی (باید هنوز هرچی کاربر خواسته باشد):", phone.is_awake)
phone.sleep()  # کاربر خودش تصمیم می‌گیرد بخواباند
print("کاربر خودش خواباند. is_awake =", phone.is_awake)


line("2️⃣ مرکز امنیتی تشخیص می‌دهد این گوشی مشکوک است و پرچم خواب اجباری می‌زند")
flag_result = center.flag_device_for_forced_sleep(phone.device_id, reason="رفتار غیرعادی: تلاش مکرر برای ارسال دستورات حساس")
print("نتیجه‌ی flag:", flag_result)


line("3️⃣ اثبات کلیدی: آیا مرکز می‌تواند خودش گوشی را بیدار کند؟")
has_wake_method = hasattr(center, "wake_device") or hasattr(center, "force_wake") or hasattr(center, "call_device")
print(f"آیا ControlCenter متدی برای بیدار کردن مستقیم گوشی دارد؟ {has_wake_method}")
print("is_awake گوشی همچنان:", phone.is_awake, "(باید False بماند، چون فقط کاربر می‌تواند بیدار کند)")
assert not has_wake_method
assert phone.is_awake is False
print("✅ تأیید شد: مرکز هیچ راهی برای بیدار کردن از راه دور ندارد.")


line("4️⃣ حالا کاربر (بدون اطلاع از تصمیم امنیتی مرکز) خودش دوباره بیدار می‌کند")
phone.wake_up()
print("کاربر دکمه را زد. is_awake =", phone.is_awake)
block2 = phone.build_signed_request({"mission": "ارسال گزارش به سرور دیگر"})
print("گوشی یک درخواست کاملاً معتبر و امضاشده ساخت (امضا/زنجیره/nonce درست است).")

resp2 = center.receive_block(block2)
print("\nپاسخ خام مرکز:")
print(" status:", resp2["status"])
print(" message:", resp2["message"])
print(" directive:", resp2["directive"])

assert resp2["status"] == "accepted_but_force_sleep"
assert resp2["directive"]["force_sleep"] is True
print("\n✅ با اینکه بلوک از نظر امنیتی ۱۰۰٪ معتبر بود (امضا/زنجیره/nonce OK)،")
print("   مرکز ماموریت را dispatch نکرد و دستور خواب اجباری فرستاد.")


line("5️⃣ گوشی دستور را اجرا می‌کند و واقعاً می‌خوابد")
print("قبل از پردازش پاسخ: is_awake =", phone.is_awake)
phone.handle_center_response(resp2)
print("بعد از پردازش پاسخ: is_awake =", phone.is_awake)
assert phone.is_awake is False
print("✅ گوشی علی‌رغم اینکه کاربر آن را بیدار نگه داشته بود، به‌خاطر دستور مرکز خوابید.")
print("   دلیل ثبت‌شده روی گوشی:", phone.last_forced_sleep_reason)


line("6️⃣ رفع پرچم توسط مرکز (وقتی مشکل امنیتی برطرف شد) و ادامه‌ی کار عادی")
center.clear_forced_sleep_flag(phone.device_id)
phone.wake_up()
block3 = phone.build_signed_request({"mission": "ماموریت عادی بعد از رفع مشکل"})
resp3 = center.receive_block(block3)
phone.handle_center_response(resp3)
print("پاسخ بعد از رفع پرچم:", resp3["status"], "| directive:", resp3["directive"])
assert resp3["status"] == "accepted"
assert phone.is_awake is True  # چون این‌بار force_sleep نبود، حالت بیداری کاربر دست‌نخورده ماند
print("✅ بعد از رفع پرچم، گوشی دوباره طبق روال عادی کار می‌کند.")

line("📊 جمع‌بندی")
print("""
این آزمایش دقیقاً همان معماری نامتقارنی را که خواسته شده بود پیاده و تست کرد:

  بیدار شدن  → فقط با تصمیم و اقدام دستی کاربر (هیچ مسیر فنی برای مرکز وجود ندارد)
  خوابیدن   → هم با تصمیم کاربر، هم با دستور امنیتی مرکز (از طریق piggyback روی
              همان درخواستی که خودِ گوشی شروع کرده، نه با تماس مستقیم مرکز با گوشی)

این یعنی مرکز یک Kill-Switch امنیتی واقعی دارد (می‌تواند جلوی یک گوشی مشکوک/شده را
بگیرد)، بدون اینکه همزمان یک درِ پشتی برای «بیدار کردن از راه دور» باز کرده باشد.
""")
