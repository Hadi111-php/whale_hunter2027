# -*- coding: utf-8 -*-
"""
📱 احراز هویت با تایید مالکیت واقعی شماره/ایمیل (OTP - One-Time Password)

مشکلی که رفع می‌کند: در نسخه‌ی قبلی platform_center.py، هر کسی می‌توانست با
فقط *تایپ کردن* شماره‌ی یک نفر دیگر، ادعای مالکیت آن شماره را بکند - سیستم
هیچ کنترلی نداشت که واقعاً همان شخص، همان شماره را در دست دارد یا نه.

راه‌حل: دقیقاً مثل تایید شماره در واتساپ/تلگرام. کاربر شماره را اعلام
می‌کند (claim)، سرور یک کد یک‌بارمصرف کوتاه‌مدت می‌سازد و آن را (در دنیای
واقعی) با SMS به همان شماره می‌فرستد. فقط بعد از وارد کردن کد درست، شماره
"verified" می‌شود و به user_id قفل می‌گردد. دستگاه (چشم‌ودست) فقط به کاربرِ
دارای شماره‌ی verified متصل می‌شود.
"""
import secrets
import time
from typing import Dict, Optional

from platform_pii import fingerprint

OTP_LENGTH = 6
OTP_TTL_SECONDS = 300  # ۵ دقیقه
MAX_OTP_ATTEMPTS = 5   # بعد از این تعداد تلاش غلط، کد باطل می‌شود (ضد brute-force)
OTP_RESEND_COOLDOWN_SECONDS = 60  # حداقل فاصله‌ی مجاز بین دو درخواست OTP برای یک شماره (ضد DoS)


class VerificationError(Exception):
    pass


class PendingVerification:
    def __init__(self, contact_value: str, otp_code: str, expected_user_id: str):
        self.contact_fingerprint = fingerprint(contact_value)
        self.otp_code = otp_code
        self.expected_user_id = expected_user_id
        self.created_at = time.time()
        self.attempts = 0
        self.verified = False


class IdentityVerificationService:
    """
    این سرویس هیچ SMS/ایمیل واقعی نمی‌فرستد (چون نیاز به یک provider واقعی
    و مجوز/هزینه دارد)؛ به‌جایش send_otp کد را برمی‌گرداند تا در پروتوتایپ/تست
    قابل مشاهده باشد. در دنیای واقعی، خط ارسال باید با Kavenegar/Twilio/... جایگزین شود.
    """

    def __init__(self):
        # contact_fingerprint -> PendingVerification
        self._pending: Dict[str, PendingVerification] = {}
        # contact_fingerprint -> user_id (فقط بعد از تایید موفق ثبت می‌شود)
        self.verified_contacts: Dict[str, str] = {}

    def send_otp(self, contact_value: str, user_id: str) -> Dict[str, str]:
        """
        شبیه‌سازی ارسال کد. contact_value می‌تواند شماره یا ایمیل باشد.
        در محیط واقعی، اینجا باید یک درخواست HTTP به provider واقعی SMS/ایمیل زده شود؛
        کد هرگز نباید در پاسخ API به کلاینت برگردد - اینجا فقط برای شفافیت تست است.

        --- رفع آسیب‌پذیری ۱ (کشف‌شده با تست واقعی): OTP Invalidation DoS ---
        قبلاً هر درخواست جدید OTP برای یک شماره، بی‌قید‌وشرط کد قبلی را جایگزین
        می‌کرد. یک مهاجم می‌توانست، بدون حدس زدن هیچ کدی، فقط با درخواست مکرر
        OTP برای شماره‌ی *یک نفر دیگر*، کد معتبر صاحب واقعی را باطل کند.
        راه‌حل: cooldown اجباری بین دو درخواست متوالی برای همان شماره.

        --- رفع آسیب‌پذیری ۲ (کشف‌شده با تست واقعی): OTP اکنون به user_id قفل می‌شود ---
        قبلاً OTP فقط بر اساس شماره ذخیره می‌شد، بدون دانستن اینکه برای کدام
        user_id است. این یعنی *هر کسی* (نه فقط کاربر واقعی) می‌توانست با
        فراخوانی confirm_otp برای همان شماره، از سهمیه‌ی «تلاش‌های مجاز»
        استفاده کند - و در نتیجه با ۵ حدس بی‌ربط، کاربر واقعی را هم قفل کند
        (یک DoS دیگر). راه‌حل: expected_user_id در لحظه‌ی send_otp ثبت می‌شود
        و confirm_otp تلاش‌های user_id غلط را *اصلاً پردازش نمی‌کند* (نه رد
        می‌کند و شمارنده را کم می‌کند، بلکه از همان ابتدا نادیده می‌گیرد).
        """
        fp = fingerprint(contact_value)
        existing = self._pending.get(fp)
        if existing is not None:
            age = time.time() - existing.created_at
            if age < OTP_RESEND_COOLDOWN_SECONDS:
                raise VerificationError(
                    f"یک کد فعال برای این شماره/ایمیل قبلاً ارسال شده؛ "
                    f"{int(OTP_RESEND_COOLDOWN_SECONDS - age)} ثانیه‌ی دیگر دوباره امتحان کن "
                    "(این محدودیت برای جلوگیری از حمله‌ی باطل‌سازی OTP توسط شخص ثالث است)"
                )
        code = "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))
        self._pending[fp] = PendingVerification(contact_value, code, expected_user_id=user_id)
        return {"ok": True, "message": f"کد تایید به {contact_value} ارسال شد (شبیه‌سازی)", "_debug_otp_for_test_only": code}

    def confirm_otp(self, contact_value: str, submitted_code: str, user_id: str) -> Dict[str, object]:
        fp = fingerprint(contact_value)
        pending = self._pending.get(fp)
        if pending is None:
            raise VerificationError("هیچ کد فعالی برای این شماره/ایمیل درخواست نشده است")

        # --- بررسی user_id قبل از هر چیز دیگر، و بدون مصرف کردن سهمیه‌ی تلاش ---
        # اگر این تماس اصلاً برای user_id دیگری غیر از expected_user_id باشد،
        # این حتی یک "تلاش نادرست روی کد درست" هم حساب نمی‌شود؛ فقط یعنی این
        # درخواست اصلاً مربوط به این OTP نیست، پس شمارنده دست‌نخورده می‌ماند.
        if user_id != pending.expected_user_id:
            raise VerificationError("این کد برای این کاربر ارسال نشده است")

        age = time.time() - pending.created_at
        if age > OTP_TTL_SECONDS:
            del self._pending[fp]
            raise VerificationError("کد منقضی شده؛ دوباره درخواست کد بده")

        pending.attempts += 1
        if pending.attempts > MAX_OTP_ATTEMPTS:
            del self._pending[fp]
            raise VerificationError("تعداد تلاش‌های مجاز تمام شد (ضد حدس‌زنی brute-force)؛ باید دوباره از صفر کد بگیری")

        if submitted_code != pending.otp_code:
            raise VerificationError(f"کد نادرست (تلاش {pending.attempts}/{MAX_OTP_ATTEMPTS})")

        # اگر این contact قبلاً به یک کاربر دیگر verified شده، نباید به کاربر جدید منتقل شود
        # مگر با یک فرآیند جداگانه‌ی "تغییر مالکیت" (که عمداً اینجا پیاده نشده - محافظه‌کارانه رد می‌کنیم)
        existing_owner = self.verified_contacts.get(fp)
        if existing_owner is not None and existing_owner != user_id:
            raise VerificationError(
                f"این شماره/ایمیل قبلاً برای کاربر دیگری تایید شده است؛ نمی‌تواند به کاربر جدید منتقل شود"
            )

        self.verified_contacts[fp] = user_id
        del self._pending[fp]
        return {"ok": True, "verified": True, "user_id": user_id}

    def is_verified_for(self, contact_value: str, user_id: str) -> bool:
        fp = fingerprint(contact_value)
        return self.verified_contacts.get(fp) == user_id
