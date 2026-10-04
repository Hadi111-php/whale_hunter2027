# -*- coding: utf-8 -*-
"""
📱 تست حیاتی: آیا الان یه هکر می‌تونه با ادعای شماره‌ی یکی دیگه، دستگاه ثبت کنه؟
این دقیقاً همون سناریوی سؤال داداش است: «هکر نسخه‌ی یکی دیگر را نصب در گوشی
خودش می‌کند و ارتباط می‌گیرد» - باید ببینیم آیا این کار مسدود می‌شود یا نه.
"""
import sys
sys.path.insert(0, '/home/user/secure_wake_prototype')

from device_agent import DeviceAgent
from platform_center import PlatformCenter, PlatformError
from identity_verification import VerificationError

results = {"passed": [], "failed": []}


def check(name, cond):
    (results["passed"] if cond else results["failed"]).append(name)
    print(("✅ " if cond else "❌ ") + name)


def line(t):
    print("\n" + "=" * 70)
    print(t)
    print("=" * 70)


# ==========================================================================
line("1️⃣ سناریوی حمله‌ی اصلی: هکر ادعای شماره‌ی یکی دیگر را می‌کند")
# ==========================================================================
platform = PlatformCenter()

real_start = platform.create_user_with_verification_start("real_ali", phone="09123456789", email="ali@example.com")
real_otp = real_start["otp"]["_debug_otp_for_test_only"]
print(f"کاربر واقعی 'real_ali' ساخته شد. OTP واقعی (که فقط باید به گوشیِ 09123456789 برسد): {real_otp}")
check("کاربر واقعی هنوز phone_verified=False است (تا وقتی کد را وارد نکرده)",
      platform.users["real_ali"].phone_verified is False)

# نکته‌ی مهم: هکر سعی می‌کند برای همان شماره یک OTP جدید بگیرد به این امید که
# کد قبلیِ real_ali را باطل کند (حمله‌ی OTP Invalidation DoS که با تست واقعی
# کشف شد) - ولی چون هنوز داخل بازه‌ی cooldown هستیم، این تلاش رد می‌شود و
# کد اصلیِ real_ali دست‌نخورده باقی می‌ماند. مهم‌تر: چون send_otp قبل از ساخت
# کاربر اجرا می‌شود (رفع باگ state ناقص)، وقتی این تلاش fail می‌کند، هیچ
# حساب "hacker_fake" یتیمی هم در سیستم باقی نمی‌ماند.
try:
    platform.create_user_with_verification_start("hacker_fake", phone="09123456789", email="hacker@evil.com")
    check("هکر نباید بتواند OTP کاربر واقعی را با درخواست مجدد باطل کند", False)
except VerificationError:
    check("[رفع‌شده] تلاش هکر برای باطل‌سازی OTP کاربر واقعی (با درخواست مجدد) مسدود شد (cooldown)", True)
    check("[رفع‌شده] بعد از fail شدن OTP، هیچ حساب یتیمی برای هکر ساخته نشده",
          "hacker_fake" not in platform.users)

# هکر یک user_id دیگر برای خودش می‌سازد (با شماره‌ی خودش، نه شماره‌ی جعلی) و
# سعی می‌کند بدون تایید، دستگاه ثبت کند - نکته‌ی اصلی این بخش همین است:
platform.create_user("hacker_fake", phone="", email="hacker@evil.com")

hacker_device = DeviceAgent(device_id="hacker-device-01", center_public_key_hex=platform.security.center_public_key_bytes)
try:
    platform.register_device_for_user("hacker_fake", hacker_device.device_id, hacker_device.public_key_bytes)
    check("هکر نباید بتواند بدون تایید واقعی شماره، دستگاه ثبت کند", False)
except PlatformError as e:
    check("هکر بدون تایید OTP واقعی نتوانست دستگاه ثبت کند", True)
    print("   پیام رد شدن:", e)

# هکر سعی می‌کند کد را حدس بزند (چون OTP واقعی را ندارد، فقط تلاش‌های تصادفی می‌زند)
guess_failed_count = 0
for guess in ["000000", "123456", "111111"]:
    try:
        platform.confirm_phone_verification("hacker_fake", "09123456789", guess)
    except VerificationError:
        guess_failed_count += 1
check("حدس‌های هکر (بدون داشتن OTP واقعی) همگی رد شدند", guess_failed_count == 3)


# ==========================================================================
line("2️⃣ کنترل: کاربر واقعی با کد درست، شماره را تایید و دستگاه را ثبت می‌کند")
# ==========================================================================
confirm_result = platform.confirm_phone_verification("real_ali", "09123456789", real_otp)
check("کاربر واقعی با OTP درست تایید شد", confirm_result["verified"] is True)
check("phone_verified حالا True شده", platform.users["real_ali"].phone_verified is True)

real_device = DeviceAgent(device_id="real-ali-device-01", center_public_key_hex=platform.security.center_public_key_bytes)
platform.register_device_for_user("real_ali", real_device.device_id, real_device.public_key_bytes)
check("کاربر واقعی بعد از تایید توانست دستگاه ثبت کند", real_device.device_id in platform.users["real_ali"].device_ids)


# ==========================================================================
line("3️⃣ حفاظت در برابر 'دزدیدن' یک شماره‌ی از قبل تایید‌شده توسط کاربر دیگر")
# ==========================================================================
platform2 = PlatformCenter()
platform2.create_user_with_verification_start("owner_user", phone="09121112233")
owner_otp = platform2.identity._pending[__import__("platform_pii").fingerprint("09121112233")].otp_code
platform2.confirm_phone_verification("owner_user", "09121112233", owner_otp)
check("owner_user مالک واقعی 09121112233 شد", platform2.users["owner_user"].phone_verified is True)

# حالا یک کاربر دوم سعی می‌کند همان شماره را برای خودش تایید کند
platform2.create_user_with_verification_start("thief_user", phone="09121112233")
thief_otp = platform2.identity._pending[__import__("platform_pii").fingerprint("09121112233")].otp_code
try:
    platform2.confirm_phone_verification("thief_user", "09121112233", thief_otp)
    check("کاربر دوم نباید بتواند شماره‌ی از قبل تایید‌شده‌ی دیگری را برای خودش ثبت کند", False)
except VerificationError:
    check("انتقال غیرمجاز یک شماره‌ی از قبل تایید‌شده به کاربر دیگر مسدود شد", True)


# ==========================================================================
line("4️⃣ ضد Brute-force: بعد از تعداد تلاش زیاد، کد باطل می‌شود")
# ==========================================================================
platform3 = PlatformCenter()
platform3.create_user_with_verification_start("brute_test_user", phone="09129998877")
for i in range(6):
    try:
        platform3.confirm_phone_verification("brute_test_user", "09129998877", "000000")
    except VerificationError:
        pass
try:
    fp = __import__("platform_pii").fingerprint("09129998877")
    still_pending = fp in platform3.identity._pending
    check("بعد از تلاش‌های زیاد ناموفق، OTP باطل/حذف شده (ضد brute-force)", not still_pending)
except Exception:
    check("بررسی brute-force", False)


# ==========================================================================
line("5️⃣ کنترل حالت غیرفعال (برای دمو/تست داخلی که می‌شود اختیاری کرد)")
# ==========================================================================
platform_demo = PlatformCenter(require_phone_verification=False)
demo_user = platform_demo.create_user("demo_user", phone="09120000000")
demo_device = DeviceAgent(device_id="demo-device", center_public_key_hex=platform_demo.security.center_public_key_bytes)
platform_demo.register_device_for_user("demo_user", demo_device.device_id, demo_device.public_key_bytes)
check("در حالت require_phone_verification=False (فقط دمو)، ثبت بدون OTP هم کار می‌کند",
      demo_device.device_id in platform_demo.users["demo_user"].device_ids)


# ==========================================================================
line("6️⃣ ضد DoS: تلاش‌های نامربوط یک نفر دیگر نباید سهمیه‌ی کاربر واقعی را مصرف کند")
# ==========================================================================
platform4 = PlatformCenter()
victim_start = platform4.create_user_with_verification_start("victim", phone="09121110000")
victim_otp = victim_start["otp"]["_debug_otp_for_test_only"]
platform4.create_user("attacker", phone="")

for _ in range(5):
    try:
        platform4.confirm_phone_verification("attacker", "09121110000", "000000")
    except VerificationError:
        pass

try:
    result = platform4.confirm_phone_verification("victim", "09121110000", victim_otp)
    check("[رفع‌شده] بعد از ۵ تلاش بی‌ربط مهاجم، قربانی همچنان با کد درست خودش تایید می‌شود", result["verified"] is True)
except VerificationError:
    check("[رفع‌شده] بعد از ۵ تلاش بی‌ربط مهاجم، قربانی همچنان با کد درست خودش تایید می‌شود", False)


print(f"\n📊 نتیجه‌ی نهایی: {len(results['passed'])} موفق / {len(results['failed'])} ناموفق")
if results["failed"]:
    for f in results["failed"]:
        print("  ❌", f)
