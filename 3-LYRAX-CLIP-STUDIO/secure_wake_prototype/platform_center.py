# -*- coding: utf-8 -*-
"""
🏛️ لایه‌ی پلتفرم چندکاربره روی همان مرکز امنیتی که قبلاً ساختیم و تست کردیم.

معماری:
    User Account  (کاربر واقعی؛ شماره/ایمیل فقط ماسک‌شده ذخیره می‌شود)
        └── Device  (یک یا چند «چشم‌ودست» که کاربر روی گوشی‌هایش نصب کرده)
    App Registration  (هر اپلیکیشن/سرویس بیرونی که برای کاربر درخواست می‌فرستد،
                        با app_id مشخص، مستقل از اینکه device کدام است)
    Payment Intent    (فقط *ساختار* یک درخواست پرداخت؛ هرگز تراکنش واقعی انجام
                        نمی‌دهد - باید به یک درگاه پرداخت مجاز و قانونی وصل شود)

نکته‌ی مهم: هیچ‌کدام از این کلاس‌ها چیزی از منطق امنیتی قبلی (امضا/زنجیره/
nonce/فایروال محتوایی/خودکشیِ اعتماد) را عوض یا دور نمی‌زنند؛ ControlCenter
همچنان تنها مسیر معتبر برای receive_block است. این ماژول فقط context/متادیتای
سطح پلتفرم را روی همان مرکز اضافه می‌کند.
"""
import time
import uuid
from typing import Any, Dict, List, Optional

from control_center import ControlCenter, SecurityError, DeviceRevokedError
from platform_pii import mask_phone, mask_email, validate_phone, validate_email, fingerprint
from identity_verification import IdentityVerificationService, VerificationError


class PlatformError(Exception):
    pass


class UserAccount:
    def __init__(self, user_id: str, phone: str = "", email: str = ""):
        self.user_id = user_id
        # مقدار خام هرگز روی آبجکت نگه داشته نمی‌شود؛ فقط ماسک و اثرانگشت.
        self.phone_masked = mask_phone(phone) if phone else ""
        self.email_masked = mask_email(email) if email else ""
        self.phone_fingerprint = fingerprint(phone) if phone else ""
        self.email_fingerprint = fingerprint(email) if email else ""
        # نکته‌ی امنیتی کلیدی (رفع آسیب‌پذیری کشف‌شده با تست): صرفِ اعلام یک شماره
        # به معنی مالکیت آن نیست. تا وقتی phone_verified=False باشد، هیچ دستگاهی
        # نباید برای این کاربر ثبت شود - چون کل هدف گرفتن شماره همین بود: تشخیص
        # قطعی اینکه "این نسخه/گوشی متعلق به همین شخص است"، نه یک هکر که فقط
        # ادعای مالکیت شماره را کرده.
        self.phone_verified = False
        self.email_verified = False
        self.device_ids: List[str] = []
        self.created_at = time.time()

    def to_public_dict(self) -> Dict[str, Any]:
        """چیزی که مجاز است در داشبورد/لاگ نمایش داده شود - هرگز مقدار خام."""
        return {
            "user_id": self.user_id,
            "phone_masked": self.phone_masked,
            "email_masked": self.email_masked,
            "device_ids": list(self.device_ids),
            "created_at": self.created_at,
        }


class AppRegistration:
    def __init__(self, app_id: str, app_name: str, owner_user_id: str):
        self.app_id = app_id
        self.app_name = app_name
        self.owner_user_id = owner_user_id
        self.registered_at = time.time()
        self.status = "active"  # active | suspended
        self.request_count = 0
        self.last_request_at: Optional[float] = None

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "app_id": self.app_id,
            "app_name": self.app_name,
            "owner_user_id": self.owner_user_id,
            "status": self.status,
            "request_count": self.request_count,
            "last_request_at": self.last_request_at,
        }


class PaymentIntent:
    """
    فقط *نیت*/ساختار یک درخواست پرداخت را نگه می‌دارد. status همیشه با
    "pending_gateway_integration" شروع می‌شود و **هیچ تابعی در این کلاس
    پول واقعی جابه‌جا نمی‌کند**. اتصال به درگاه واقعی (زرین‌پال/آیدی‌پی و...)
    باید در یک لایه‌ی کاملاً جدا و بعد از طی مراحل قانونی/مجوز پیاده شود.
    """
    def __init__(self, intent_id: str, user_id: str, app_id: str, amount_rials: int, purpose: str):
        if amount_rials <= 0:
            raise PlatformError("مبلغ باید مثبت باشد")
        self.intent_id = intent_id
        self.user_id = user_id
        self.app_id = app_id
        self.amount_rials = amount_rials
        self.purpose = purpose
        self.status = "pending_gateway_integration"
        self.created_at = time.time()
        self.gateway_ref = None  # وقتی به درگاه واقعی وصل شد، اینجا مرجع تراکنش می‌آید

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "user_id": self.user_id,
            "app_id": self.app_id,
            "amount_rials": self.amount_rials,
            "purpose": self.purpose,
            "status": self.status,
            "created_at": self.created_at,
            "gateway_ref": self.gateway_ref,
        }


class PlatformCenter:
    """
    هسته‌ی پلتفرم: یک ControlCenter امنیتی را می‌سازد و روی آن، رجیستری
    کاربران/اپ‌ها/پرداخت‌ها را اضافه می‌کند. تمام درخواست‌های امنیتی واقعی
    (بلوک‌های گوشی) همچنان از self.security.receive_block عبور می‌کنند -
    این کلاس هیچ مسیر میان‌بر امنیتی جدیدی باز نمی‌کند.
    """

    def __init__(self, require_phone_verification: bool = True):
        self.security = ControlCenter()
        self.identity = IdentityVerificationService()
        self.users: Dict[str, UserAccount] = {}
        self.apps: Dict[str, AppRegistration] = {}
        self.payment_intents: Dict[str, PaymentIntent] = {}
        self.device_owner: Dict[str, str] = {}  # device_id -> user_id
        # اگر False شود (مثلاً برای تست‌های داخلی/دمو)، احراز هویت شماره اجباری
        # نیست؛ در حالت پیش‌فرض و برای هر استقرار واقعی باید True بماند.
        self.require_phone_verification = require_phone_verification

    # -----------------------------------------------------------------
    # مدیریت کاربر
    # -----------------------------------------------------------------
    def create_user(self, user_id: str, phone: str = "", email: str = "") -> UserAccount:
        if user_id in self.users:
            raise PlatformError(f"کاربر {user_id} از قبل وجود دارد")
        if phone and not validate_phone(phone):
            raise PlatformError("فرمت شماره تلفن نامعتبر است")
        if email and not validate_email(email):
            raise PlatformError("فرمت ایمیل نامعتبر است")
        user = UserAccount(user_id, phone=phone, email=email)
        self.users[user_id] = user
        return user

    def create_user_with_verification_start(self, user_id: str, phone: str, email: str = "") -> Dict[str, Any]:
        """
        جایگزین امن‌تر create_user: کاربر ساخته می‌شود ولی phone_verified=False
        می‌ماند، و بلافاصله یک OTP برای شماره‌ی ادعاشده ارسال می‌شود. کاربر باید
        با confirm_phone_verification کد را تایید کند تا phone_verified=True شود.

        نکته: اگر برای همین شماره یک OTP فعال دیگری (مثلاً توسط یک مهاجم که
        سعی در ادعای همین شماره دارد) به‌تازگی ارسال شده باشد، این متد
        VerificationError می‌دهد (به‌خاطر cooldown ضد-DoS در send_otp).

        --- رفع آسیب‌پذیری کشف‌شده با تست واقعی (Orphaned/Partial User State) ---
        قبلاً ترتیب اجرا این‌طور بود: اول create_user (کاربر واقعاً ساخته و ثبت
        می‌شد)، بعد send_otp. اگر send_otp fail می‌کرد (مثلاً به‌خاطر cooldown)،
        کاربر با همان user_id از قبل در self.users باقی می‌ماند - یک "حساب یتیمِ"
        نیمه‌ساخته که هرگز phone_verified نمی‌شود ولی جای user_id را اشغال کرده.
        راه‌حل: ابتدا OTP را می‌فرستیم (که ممکن است fail کند)، و فقط اگر موفق
        بود، کاربر را واقعاً می‌سازیم؛ یعنی هیچ state ناقصی باقی نمی‌ماند.
        """
        if user_id in self.users:
            raise PlatformError(f"کاربر {user_id} از قبل وجود دارد")
        if phone and not validate_phone(phone):
            raise PlatformError("فرمت شماره تلفن نامعتبر است")
        if email and not validate_email(email):
            raise PlatformError("فرمت ایمیل نامعتبر است")

        otp_result = self.identity.send_otp(phone, user_id=user_id)  # اگر cooldown فعال باشد، اینجا قبل از ساخت کاربر fail می‌کند
        user = UserAccount(user_id, phone=phone, email=email)
        self.users[user_id] = user
        return {"user": user, "otp": otp_result}

    def confirm_phone_verification(self, user_id: str, phone: str, submitted_code: str) -> Dict[str, Any]:
        """قدم ۲: کاربر کد دریافتی را وارد می‌کند تا مالکیت واقعی شماره اثبات شود."""
        if user_id not in self.users:
            raise PlatformError(f"کاربر ناشناس: {user_id}")
        result = self.identity.confirm_otp(phone, submitted_code, user_id)  # اگر غلط باشد VerificationError می‌دهد
        self.users[user_id].phone_verified = True
        return result

    def register_device_for_user(self, user_id: str, device_id: str, public_key_hex: str) -> None:
        if user_id not in self.users:
            raise PlatformError(f"کاربر ناشناس: {user_id}")
        user = self.users[user_id]
        # --- رفع آسیب‌پذیری کشف‌شده با تست ---
        # قبلاً هر کاربری (حتی با شماره‌ی جعلی/ادعاشده) می‌توانست بلافاصله دستگاه
        # ثبت کند. حالا اگر require_phone_verification فعال باشد (پیش‌فرض)، تا
        # وقتی مالکیت واقعی شماره با OTP اثبات نشده، امکان اتصال دستگاه نیست -
        # این دقیقاً همان چیزی است که مانع از "نصب نسخه‌ی هکر با شماره‌ی جعلی" می‌شود.
        if self.require_phone_verification and not user.phone_verified:
            raise PlatformError(
                f"کاربر {user_id} هنوز شماره‌اش تایید نشده (phone_verified=False)؛ "
                "قبل از ثبت دستگاه باید confirm_phone_verification را با موفقیت انجام دهد."
            )
        self.security.register_device(device_id, public_key_hex)
        user.device_ids.append(device_id)
        self.device_owner[device_id] = user_id

    # -----------------------------------------------------------------
    # مدیریت اپ‌ها (App Registry) - هر app_id مستقل از device_id است
    # -----------------------------------------------------------------
    def register_app(self, app_name: str, owner_user_id: str) -> AppRegistration:
        if owner_user_id not in self.users:
            raise PlatformError(f"کاربر ناشناس: {owner_user_id}")
        app_id = f"app_{uuid.uuid4().hex[:12]}"
        app = AppRegistration(app_id=app_id, app_name=app_name, owner_user_id=owner_user_id)
        self.apps[app_id] = app
        return app

    def suspend_app(self, app_id: str, reason: str = "") -> None:
        if app_id not in self.apps:
            raise PlatformError(f"اپ ناشناس: {app_id}")
        self.apps[app_id].status = "suspended"

    def record_app_request(self, app_id: str) -> Dict[str, Any]:
        """
        وقتی یک اپ بیرونی برای یک کاربر درخواست می‌فرستد (مثلاً 'کاربر X را
        بیدار کن که فلان کار را انجام دهد'). این تابع فقط request را نزد
        همان app_id ثبت می‌کند؛ خودِ بیدار شدن گوشی طبق معماری قبلی
        **هرگز از این مسیر اتفاق نمی‌افتد** - این صرفاً یک صف/اعلان برای
        دیدن در داشبورد است تا وقتی کاربر خودش دستی گوشی را بیدار کرد،
        ببیند چه درخواست‌هایی از چه اپ‌هایی در انتظارند.
        """
        if app_id not in self.apps:
            raise PlatformError(f"اپ ناشناس: {app_id}")
        app = self.apps[app_id]
        if app.status != "active":
            raise PlatformError(f"اپ {app_id} suspended است و نمی‌تواند درخواست ثبت کند")
        app.request_count += 1
        app.last_request_at = time.time()
        return {"ok": True, "app_id": app_id, "request_count": app.request_count}

    # -----------------------------------------------------------------
    # پرداخت (فقط ساختار/نیت - بدون تراکنش واقعی)
    # -----------------------------------------------------------------
    def create_payment_intent(self, user_id: str, app_id: str, amount_rials: int, purpose: str) -> PaymentIntent:
        if user_id not in self.users:
            raise PlatformError(f"کاربر ناشناس: {user_id}")
        if app_id not in self.apps:
            raise PlatformError(f"اپ ناشناس: {app_id}")
        if self.apps[app_id].status != "active":
            raise PlatformError("اپ suspended است، نمی‌تواند درخواست پرداخت ثبت کند")
        intent_id = f"pay_{uuid.uuid4().hex[:16]}"
        intent = PaymentIntent(intent_id, user_id, app_id, amount_rials, purpose)
        self.payment_intents[intent_id] = intent
        return intent

    # -----------------------------------------------------------------
    # خلاصه‌ی داشبورد - «کدام فعال، کدام خواب» طبق درخواست صریح
    # -----------------------------------------------------------------
    def dashboard_summary(self) -> Dict[str, Any]:
        device_status = {}
        for device_id in self.device_owner:
            revoked = device_id in self.security.revoked_devices
            forced_sleep = device_id in self.security.forced_sleep_flags
            device_status[device_id] = {
                "owner": self.device_owner[device_id],
                "revoked": revoked,
                "forced_sleep_pending": forced_sleep,
                "trust_strikes": self.security.trust_strikes.get(device_id, 0),
                "chain_length": len(self.security.device_chains.get(device_id, [])),
            }
        return {
            "total_users": len(self.users),
            "total_devices": len(self.device_owner),
            "total_apps": len(self.apps),
            "active_apps": sum(1 for a in self.apps.values() if a.status == "active"),
            "suspended_apps": sum(1 for a in self.apps.values() if a.status == "suspended"),
            "revoked_devices": sum(1 for d in device_status.values() if d["revoked"]),
            "devices": device_status,
            "pending_payment_intents": sum(1 for p in self.payment_intents.values() if p.status == "pending_gateway_integration"),
        }
