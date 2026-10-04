# -*- coding: utf-8 -*-
"""
🏛️ تست جامع لایه‌ی پلتفرم چندکاربره: کاربران، اپ‌ها، ماسک PII، و پرداخت (فقط ساختار).
همچنین تایید می‌کند که تمام لایه‌های امنیتی قبلی (چشم‌ودست، فایروال محتوایی،
خودکشیِ اعتماد) در سطح پلتفرم هم دست‌نخورده و فعال می‌مانند.
"""
import sys
sys.path.insert(0, '/home/user/secure_wake_prototype')

from device_agent import DeviceAgent
from platform_center import PlatformCenter, PlatformError
from platform_pii import mask_phone, mask_email, validate_phone, validate_email, fingerprint
from control_center import DeviceRevokedError

results = {"passed": [], "failed": []}


def check(name, cond):
    (results["passed"] if cond else results["failed"]).append(name)
    print(("✅ " if cond else "❌ ") + name)


def line(t):
    print("\n" + "=" * 70)
    print(t)
    print("=" * 70)


# ==========================================================================
line("1️⃣ ماسک‌گذاری PII - داده‌ی خام هرگز نباید در نسخه‌ی نمایشی دیده شود")
# ==========================================================================
check("شماره تلفن معتبر تشخیص داده می‌شود", validate_phone("09123456789"))
check("شماره تلفن نامعتبر رد می‌شود", not validate_phone("abc123"))
check("ایمیل معتبر تشخیص داده می‌شود", validate_email("ali@example.com"))
check("ایمیل نامعتبر رد می‌شود", not validate_email("not-an-email"))

masked_phone = mask_phone("09123456789")
check(f"شماره ماسک‌شده رقم وسط را مخفی می‌کند: {masked_phone}", "3456" not in masked_phone and masked_phone.startswith("0912"))

masked_email = mask_email("ali.rezaei@example.com")
check(f"ایمیل ماسک‌شده بخش حساس را مخفی می‌کند: {masked_email}", "rezaei" not in masked_email)

check("fingerprint یک مقدار برگشت‌ناپذیر (هش) تولید می‌کند، نه خودِ شماره",
      fingerprint("09123456789") != "09123456789" and len(fingerprint("09123456789")) == 64)


# ==========================================================================
line("2️⃣ ساخت کاربر - مقدار خام هرگز روی آبجکت نمی‌ماند")
# ==========================================================================
# نکته: بعد از اضافه‌شدن identity_verification.py، ثبت دستگاه به‌طور پیش‌فرض
# نیاز به تایید واقعی شماره (OTP) دارد. چون تمرکز این فایل تست روی PII/اپ/
# پرداخت/ایزوله‌سازی چندکاربره است (نه خودِ فرآیند OTP که در
# test_identity_verification.py جداگانه و کامل تست شده)، اینجا این الزام را
# آگاهانه غیرفعال می‌کنیم تا این تست‌ها روی موضوع اصلی خودشان متمرکز بمانند.
platform = PlatformCenter(require_phone_verification=False)
user1 = platform.create_user("user_ali", phone="09123456789", email="ali@example.com")

public_view = user1.to_public_dict()
check("خروجی عمومی کاربر شامل شماره خام نیست", "09123456789" not in str(public_view))
check("خروجی عمومی کاربر شامل ایمیل خام نیست", "ali@example.com" not in str(public_view))
check("خروجی عمومی شامل نسخه‌ی ماسک‌شده هست", "0912" in public_view["phone_masked"])

try:
    platform.create_user("user_bad", phone="not-a-phone")
    check("فرمت غلط تلفن باید رد شود", False)
except PlatformError:
    check("فرمت غلط تلفن به‌درستی رد شد", True)


# ==========================================================================
line("3️⃣ ثبت دستگاه برای کاربر - همچنان از همان ControlCenter امنیتی عبور می‌کند")
# ==========================================================================
phone_device = DeviceAgent(device_id="ali-phone-01", center_public_key_hex=platform.security.center_public_key_bytes)
platform.register_device_for_user("user_ali", phone_device.device_id, phone_device.public_key_bytes)

check("دستگاه به کاربر متصل شد", phone_device.device_id in platform.users["user_ali"].device_ids)
check("مالکیت دستگاه درست ثبت شده", platform.device_owner[phone_device.device_id] == "user_ali")

phone_device.wake_up()
block = phone_device.build_signed_request({"mission": "بررسی وضعیت"})
resp = platform.security.receive_block(block)  # همان مسیر امنیتی قبلی، بدون میان‌بر
phone_device.handle_center_response(resp)
check("درخواست معتبر از طریق پلتفرم هم مثل قبل پردازش می‌شود", resp["status"] == "accepted")


# ==========================================================================
line("4️⃣ رجیستری اپ‌ها - هر اپ مستقل از دستگاه، با app_id خاص خودش")
# ==========================================================================
app1 = platform.register_app("MyShoppingApp", owner_user_id="user_ali")
check("اپ با app_id یکتا ساخته شد", app1.app_id.startswith("app_"))
check("اپ ابتدا active است", app1.status == "active")

r = platform.record_app_request(app1.app_id)
check("ثبت درخواست اپ کار می‌کند", r["ok"] and r["request_count"] == 1)

platform.suspend_app(app1.app_id, reason="رفتار مشکوک گزارش شد")
check("اپ suspend شد", platform.apps[app1.app_id].status == "suspended")

try:
    platform.record_app_request(app1.app_id)
    check("اپ suspended نباید بتواند درخواست جدید ثبت کند", False)
except PlatformError:
    check("اپ suspended به‌درستی از ثبت درخواست جدید منع شد", True)


# ==========================================================================
line("5️⃣ پرداخت - فقط ساختار/نیت، هرگز تراکنش واقعی")
# ==========================================================================
app2 = platform.register_app("ActiveApp", owner_user_id="user_ali")
intent = platform.create_payment_intent("user_ali", app2.app_id, amount_rials=500000, purpose="خرید اشتراک ماهانه")
check("Payment Intent با وضعیت 'در انتظار اتصال درگاه' ساخته می‌شود (نه انجام‌شده)",
      intent.status == "pending_gateway_integration")
check("هیچ gateway_ref واقعی وجود ندارد (چون هیچ تراکنش واقعی رخ نداده)", intent.gateway_ref is None)

try:
    platform.create_payment_intent("user_ali", app1.app_id, amount_rials=100000, purpose="تست")
    check("پرداخت برای اپ suspended نباید ساخته شود", False)
except PlatformError:
    check("پرداخت برای اپ suspended به‌درستی رد شد", True)

try:
    PaymentIntent_test = platform.create_payment_intent("user_ali", app2.app_id, amount_rials=-100, purpose="منفی")
    check("مبلغ منفی نباید پذیرفته شود", False)
except PlatformError:
    check("مبلغ منفی/نامعتبر به‌درستی رد شد", True)


# ==========================================================================
line("6️⃣ ایزوله‌سازی چندکاربره: مشکل کاربر A نباید کاربر B را تحت تاثیر قرار دهد")
# ==========================================================================
user2 = platform.create_user("user_sara", phone="09351234567", email="sara@example.com")
sara_device = DeviceAgent(device_id="sara-phone-01", center_public_key_hex=platform.security.center_public_key_bytes)
platform.register_device_for_user("user_sara", sara_device.device_id, sara_device.public_key_bytes)

# کاربر علی (یا گوشیش) دو بار محتوای مخرب می‌فرستد -> باید trust suicide شود
phone_device.wake_up()
b1 = phone_device.build_signed_request({"mission": "run_command", "command": "rm -rf /"})
platform.security.receive_block(b1)
phone_device.wake_up()
b2 = phone_device.build_signed_request({"mission": "run_command", "command": "mkfs.ext4 /dev/sda"})
r2 = platform.security.receive_block(b2)
check("دستگاه کاربر علی بعد از ۲ تخلف revoke شد", r2["revoked"] is True)

# حالا چک کنیم کاربر سارا کاملاً سالم و بدون مشکل است
sara_device.wake_up()
b3 = sara_device.build_signed_request({"mission": "کار عادی سارا"})
r3 = platform.security.receive_block(b3)
sara_device.handle_center_response(r3)
check("دستگاه کاربر سارا کاملاً سالم مانده و تحت تاثیر تخلف کاربر دیگر قرار نگرفته",
      r3["status"] == "accepted" and sara_device.device_id not in platform.security.revoked_devices)

try:
    phone_device.wake_up()
    b4 = phone_device.build_signed_request({"mission": "حتی یک پیام کاملاً بی‌خطر"})
    platform.security.receive_block(b4)
    check("دستگاه revoked‌شده‌ی علی نباید دیگر هیچ پیامی بفرستد", False)
except DeviceRevokedError:
    check("دستگاه revoked‌شده‌ی علی برای همیشه مسدود ماند (Trust Suicide حفظ شد)", True)


# ==========================================================================
line("7️⃣ داشبورد پلتفرم - خلاصه‌ی 'کدام فعال، کدام خواب' طبق درخواست صریح")
# ==========================================================================
summary = platform.dashboard_summary()
print("خلاصه‌ی داشبورد:")
for k, v in summary.items():
    if k != "devices":
        print(f"  {k}: {v}")
print("  devices:")
for dev_id, info in summary["devices"].items():
    print(f"    {dev_id}: owner={info['owner']}, revoked={info['revoked']}, "
          f"forced_sleep_pending={info['forced_sleep_pending']}, strikes={info['trust_strikes']}")

check("داشبورد تعداد کاربران را درست می‌شمارد", summary["total_users"] == 2)
check("داشبورد تعداد دستگاه‌ها را درست می‌شمارد", summary["total_devices"] == 2)
check("داشبورد دستگاه revoked را درست نشان می‌دهد", summary["revoked_devices"] == 1)
check("داشبورد اپ suspended را درست می‌شمارد", summary["suspended_apps"] == 1)
check("داشبورد اپ active را درست می‌شمارد", summary["active_apps"] == 1)


print(f"\n📊 نتیجه‌ی نهایی: {len(results['passed'])} موفق / {len(results['failed'])} ناموفق")
if results["failed"]:
    for f in results["failed"]:
        print("  ❌", f)
