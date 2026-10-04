# -*- coding: utf-8 -*-
"""
🏢 شبیه‌سازی «مرکز کنترل» (Control Center)

مرکز:
- فقط منتظر می‌ماند تا گوشی (که خودش بیدار شده) به آن وصل شود؛ هرگز خودش گوشی را بیدار نمی‌کند.
- برای هر گوشی، فقط کلید عمومی‌اش را نگه می‌دارد (نه کلید خصوصی) — دقیقاً مثل SSH/WebAuthn.
- هر بلوک ورودی را از سه فیلتر رد می‌کند:
    ۱) بررسی امضا (Forge Protection)      → آیا واقعاً همین گوشی امضا کرده؟
    ۲) بررسی زنجیره‌ی هش (Tamper Protection) → آیا با تاریخچه‌ی قبلی همین گوشی سازگار است؟
    ۳) بررسی nonce/زمان (Replay Protection)  → آیا این یک درخواست تکراری/کهنه نیست؟
"""

import hashlib
import json
import time
from typing import Any, Dict
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

from content_safety import scan_payload

GENESIS_HASH = "0" * 64
NONCE_MAX_AGE_SEC = 30  # هر درخواست حداکثر ۳۰ ثانیه اعتبار دارد (ضد replay دیرهنگام)


def _canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


class SecurityError(Exception):
    pass


MAX_TRUST_STRIKES = 2  # بعد از این تعداد تخلف (محتوای ناامن یا نافرمانی از دستور خواب)، اعتماد برای همیشه نابود می‌شود


class DeviceRevokedError(SecurityError):
    """دستگاهی که اعتمادش برای همیشه نابود شده (trust suicide) دوباره تلاش کرده وصل شود."""
    pass


class ControlCenter:
    def __init__(self):
        self.registered_devices = {}   # device_id -> public_key_hex
        self.device_chains = {}        # device_id -> [blocks تأییدشده]
        self.seen_nonces = {}          # device_id -> set(nonce) برای جلوگیری از replay
        self.forced_sleep_flags = {}   # device_id -> {"reason": str, "flagged_at": float}

        # --- «خودکشیِ اعتماد» سمت مرکز (Trust Suicide / Permanent Revocation) ---
        # این لایه دقیقاً برای همان نگرانی طراحی شده: اگر گوشی هک شده باشد، هکر
        # می‌تواند تابع sleep()/handle_center_response() را در کد خودِ گوشی دستکاری
        # کند تا هرگز واقعاً نخوابد. چون مرکز به کد گوشی دسترسی ندارد، نمی‌تواند
        # آن را «مجبور» کند بخوابد؛ ولی می‌تواند کاری کند که خوابیدن یا نخوابیدنش
        # دیگر اهمیتی نداشته باشد: با ثبت strike به‌ازای هر تخلف (نافرمانی از دستور
        # خواب یا فرستادن محتوای ناامن)، و بعد از رسیدن به سقف مجاز، device_id را
        # برای همیشه از registered_devices حذف می‌کند. این حذف غیرقابل‌بازگشت است
        # (باید دوباره از صفر و با بررسی دستی ثبت‌نام شود) و کاملاً سمت مرکز اجرا
        # می‌شود - هکر هیچ راهی برای جلوگیری از آن ندارد، چون به کد مرکز دسترسی ندارد.
        self.trust_strikes = {}        # device_id -> int
        self.revoked_devices = {}      # device_id -> {"revoked_at": float, "reason": str}

        # --- کلید امضای خودِ مرکز (رفع آسیب‌پذیری MITM روی پاسخ) ---
        # قبلاً فقط درخواست گوشی امضا می‌شد، نه پاسخ مرکز. این یعنی اگر ارتباط
        # روی یک کانال ناامن رد و بدل شود، یک مهاجم می‌تواند directive.force_sleep
        # را در راه حذف کند. با امضای پاسخ توسط مرکز، گوشی می‌تواند قبل از اعتماد
        # به هر دستوری (خصوصاً force_sleep=False) صحت و دست‌نخوردگی پاسخ را با
        # کلید عمومی مرکز (که از قبل، مثلاً هنگام نصب اپ، در گوشی جاسازی شده) تایید کند.
        self._center_private_key = Ed25519PrivateKey.generate()
        self.center_public_key = self._center_private_key.public_key()
        self.center_public_key_bytes = self.center_public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        ).hex()

    # فیلد(های) متا که فقط برای حمل امضا اضافه می‌شوند و نباید جزو «محتوای امضاشده»
    # حساب شوند؛ هم سمت مرکز (امضا) و هم سمت گوشی (تایید) باید دقیقاً همین یک
    # لیست را برای حذف از payload_for_signing استفاده کنند، وگرنه دو طرف روی دو
    # بایت متفاوت حساب می‌کنند و امضای درست هم نامعتبر تشخیص داده می‌شود
    # (این دقیقاً همان باگی بود که با تست واقعی پیدا و همین‌جا رفع شد).
    SIGNATURE_META_FIELDS = ("center_signature",)

    def _sign_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """پاسخ را با کلید خصوصی مرکز امضا می‌کند تا گوشی بتواند صحتش را تایید کند."""
        payload_for_signing = {k: v for k, v in response.items() if k not in self.SIGNATURE_META_FIELDS}
        body_bytes = _canonical_json(payload_for_signing)
        digest = hashlib.sha256(body_bytes).digest()
        signature = self._center_private_key.sign(digest).hex()
        signed = dict(response)
        signed["center_signature"] = signature
        return signed

    def register_device(self, device_id: str, public_key_hex: str):
        """مرحله‌ی ثبت‌نام یک‌باره (مثلاً موقع نصب اپ روی گوشی)."""
        self.registered_devices[device_id] = public_key_hex
        self.device_chains[device_id] = []
        self.seen_nonces[device_id] = set()
        self.trust_strikes[device_id] = 0

    def _register_strike(self, device_id: str, reason: str) -> bool:
        """
        یک strike به دستگاه اضافه می‌کند. اگر به سقف رسید، اعتماد را برای همیشه
        نابود می‌کند (trust suicide) و True برمی‌گرداند (یعنی از این لحظه به بعد
        revoked است). این تابع کاملاً مستقل از رفتار خودِ گوشی اجرا می‌شود.
        """
        self.trust_strikes[device_id] = self.trust_strikes.get(device_id, 0) + 1
        if self.trust_strikes[device_id] >= MAX_TRUST_STRIKES:
            self.registered_devices.pop(device_id, None)
            self.revoked_devices[device_id] = {"revoked_at": time.time(), "reason": reason}
            return True
        return False

    # -----------------------------------------------------------------
    # کلید امنیتی این بخش: مرکز نمی‌تواند به گوشی وصل شود یا بیدارش کند،
    # ولی می‌تواند (از طریق پنل ادمین/سامانه‌ی امنیتی، نه یک هکر بیرونی)
    # یک "پرچم خواب اجباری" روی یک device_id بگذارد. این پرچم فقط زمانی اثر
    # می‌کند که خودِ گوشی (با تصمیم کاربر) بیدار شود و یک درخواست معتبر
    # بفرستد؛ مرکز آن‌وقت داخل *همان جواب* به گوشی می‌گوید فوراً بخواب.
    # یعنی مرکز هرگز ارتباط را آغاز نمی‌کند، فقط از ارتباطی که خودِ گوشی
    # شروع کرده «سواری می‌گیرد» (piggyback) تا دستور خواب را برساند.
    # -----------------------------------------------------------------
    def flag_device_for_forced_sleep(self, device_id: str, reason: str) -> Dict[str, Any]:
        if device_id not in self.registered_devices:
            raise SecurityError(f"دستگاه ناشناس: {device_id}")
        self.forced_sleep_flags[device_id] = {"reason": reason, "flagged_at": time.time()}
        return {"ok": True, "device_id": device_id, "reason": reason, "message": "دستگاه برای خواب اجباری در اولین ارتباط بعدی علامت‌گذاری شد."}

    def clear_forced_sleep_flag(self, device_id: str) -> Dict[str, Any]:
        self.forced_sleep_flags.pop(device_id, None)
        return {"ok": True, "device_id": device_id, "message": "پرچم خواب اجباری برداشته شد."}

    def receive_block(self, block: dict) -> dict:
        """
        این تابع دقیقاً شبیه اندپوینت API مرکز است که گوشیِ بیدارشده به آن وصل می‌شود.
        اگر هرکدام از سه لایه‌ی امنیتی رد شود، SecurityError پرتاب می‌شود.

        نکته‌ی مهم: حتی وقتی همه‌چیز معتبر است، اگر device_id برای خواب اجباری
        علامت‌گذاری شده باشد، جواب شامل directive.force_sleep=True خواهد بود و
        payload/ماموریت اصلی پردازش نمی‌شود (dispatch نمی‌شود) - گوشی موظف است
        فوراً بخوابد، صرف‌نظر از خواسته‌ی کاربر.
        """
        device_id = block.get("device_id")

        # --- لایه‌ی منفی‌یک: آیا این دستگاه قبلاً برای همیشه از رده خارج شده؟ ---
        # این چک قبل از هر بررسی دیگری انجام می‌شود؛ حتی اگر امضا/زنجیره/nonce
        # این بلوک کاملاً معتبر باشند، یک دستگاه revoked دیگر هرگز شنیده نمی‌شود.
        if device_id in self.revoked_devices:
            raise DeviceRevokedError(
                f"دستگاه {device_id} به‌طور دائمی از رده خارج شده (trust suicide) - "
                f"دلیل: {self.revoked_devices[device_id]['reason']}. باید از صفر و با بررسی دستی دوباره ثبت‌نام شود."
            )

        # --- لایه‌ی صفر: آیا اصلاً این گوشی ثبت‌نام‌شده است؟ ---
        if device_id not in self.registered_devices:
            raise SecurityError(f"دستگاه ناشناس: {device_id}")

        pubkey_hex = self.registered_devices[device_id]
        pubkey = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pubkey_hex))

        # --- لایه‌ی ۱: بررسی امضا (Forge Protection) ---
        # هش را دوباره از روی بدنه‌ی بلوک (بدون فیلدهای hash/signature) محاسبه می‌کنیم
        # تا مطمئن شویم هش ادعاشده دستکاری نشده.
        block_body = {k: v for k, v in block.items() if k not in ("hash", "signature")}
        recomputed_hash = hashlib.sha256(_canonical_json(block_body)).hexdigest()

        if recomputed_hash != block.get("hash"):
            raise SecurityError("هش بلوک با محتوای واقعی همخوانی ندارد (احتمال دستکاری محتوا)")

        try:
            pubkey.verify(bytes.fromhex(block["signature"]), bytes.fromhex(recomputed_hash))
        except InvalidSignature:
            raise SecurityError("امضای دیجیتال نامعتبر است (جعل هویت / کلید نادرست)")

        # --- لایه‌ی ۲: بررسی زنجیره‌ی هش (Tamper-Evidence مثل بلاکچین) ---
        chain = self.device_chains[device_id]
        expected_index = len(chain)
        expected_prev_hash = chain[-1]["hash"] if chain else GENESIS_HASH

        if block["index"] != expected_index:
            raise SecurityError(
                f"ترتیب بلوک نامعتبر است (انتظار index={expected_index}، دریافت={block['index']}) "
                f"— ممکن است بلوکی حذف/جابه‌جا شده باشد"
            )
        if block["prev_hash"] != expected_prev_hash:
            raise SecurityError(
                "زنجیره پاره شده / دستکاری‌شده! prev_hash با آخرین بلوک تأییدشده مطابقت ندارد. "
                "این یعنی یا یک بلوک قبلی دستکاری شده یا کلا زنجیره‌ای جعلی است."
            )

        # --- لایه‌ی ۳: بررسی nonce و زمان (Replay Protection) ---
        nonces = self.seen_nonces[device_id]
        if block["nonce"] in nonces:
            raise SecurityError("حمله‌ی Replay شناسایی شد: این nonce قبلاً استفاده شده است!")

        age = time.time() - block["timestamp"]
        if age > NONCE_MAX_AGE_SEC:
            raise SecurityError(f"درخواست منقضی شده (سن={age:.1f}s > {NONCE_MAX_AGE_SEC}s) — احتمال replay کهنه")

        # --- همه‌ی لایه‌ها پاس شد: بلوک را می‌پذیریم و در زنجیره ثبت می‌کنیم ---
        # نکته: حتی محتوای خطرناک هم در زنجیره ثبت می‌شود (برای audit trail کامل و
        # غیرقابل‌انکار)، فقط dispatch نمی‌شود. این یعنی زنجیره «هرچه اتفاق افتاد»
        # را نشان می‌دهد، نه فقط «هرچه مجاز بود».
        nonces.add(block["nonce"])
        chain.append(block)

        # --- لایه‌ی چهارم و مستقل: فایروال محتوایی (Content Safety) ---
        # طبق تاکید صریح: این لایه ربطی به هویت فرستنده ندارد. حتی اگر امضا/زنجیره/
        # nonce کاملاً معتبر باشند (یعنی واقعاً همان کاربر قانونی گوشی است، حتی اگر
        # آن کاربر خودش هکر باشد یا گوشی‌اش آلوده شده باشد)، اگر خودِ محتوای پیام
        # شبیه کد مخرب/کرم اجرایی/دستور فاجعه‌بار باشد، ماموریت هرگز dispatch
        # نمی‌شود و دستگاه بلافاصله (و برای همیشه، تا بررسی دستی) برای خواب اجباری
        # علامت‌گذاری می‌شود - این خودِ رفتار «چشم و دست دیدن محتوای مشکوک و نخوابیدن
        # روی آن» است که درخواست شده بود.
        safety = scan_payload(block.get("payload"))
        if not safety["safe"]:
            self.forced_sleep_flags[device_id] = {
                "reason": f"محتوای درخواست ناامن تشخیص داده شد: {safety['reason']}",
                "flagged_at": time.time(),
                "auto_flagged": True,
            }
            # --- ثبت strike: محتوای ناامن یک تخلف جدی است ---
            # بعد از رسیدن به MAX_TRUST_STRIKES، این دستگاه برای همیشه از
            # registered_devices حذف می‌شود، مستقل از اینکه خودش بخوابد یا نه.
            just_revoked = self._register_strike(
                device_id, reason=f"محتوای ناامن تکراری: {safety['reason']}"
            )
            response = {
                "status": "rejected_unsafe_content",
                "device_id": device_id,
                "chain_length": len(chain),
                "in_response_to_nonce": block["nonce"],
                "in_response_to_hash": block["hash"],
                "directive": {"force_sleep": True, "reason": safety["reason"]},
                "trust_strikes": self.trust_strikes.get(device_id, 0),
                "revoked": just_revoked,
                "message": (
                    f"🚫 بلوک #{block['index']} از نظر هویتی معتبر بود (واقعاً همین دستگاه فرستاده)، "
                    f"اما محتوای درخواست ناامن تشخیص داده شد: {safety['reason']}. "
                    "ماموریت هرگز dispatch نمی‌شود و دستگاه تا بررسی دستی برای خواب اجباری علامت‌گذاری شد."
                    + (" ⚠️ سقف تخلف رسید: اعتماد این دستگاه برای همیشه نابود شد (trust suicide)." if just_revoked else "")
                ),
            }
            return self._sign_response(response)

        # --- بررسی پرچم خواب اجباری (Kill-Switch نامتقارن) ---
        # نکته‌ی امنیتی مهم: هر دو نوع پاسخ (عادی و force_sleep) با _sign_response
        # امضا می‌شوند، نه فقط یکی. اگر فقط پاسخ force_sleep امضا می‌شد، یک مهاجم
        # می‌توانست به‌سادگی تشخیص دهد کدام پاسخ‌ها «حساس» هستند. امضای همیشگی و
        # یکسان باعث می‌شود مهاجم نتواند از روی وجود/عدم امضا چیزی حدس بزند.
        # نکته‌ی امنیتی مهم دوم (رفع آسیب‌پذیری Replay پاسخ‌های قدیمی): هر پاسخ باید
        # به‌طور غیرقابل‌جعل به همان درخواستی که باعث تولیدش شده «قفل» شود. برای این کار
        # nonce و hash همان بلوک درخواستی را داخل پاسخِ امضاشده می‌گنجانیم. گوشی موظف
        # است قبل از اعتماد به هر directive، این دو مقدار را با درخواستی که خودش همین
        # الان فرستاده مقایسه کند؛ اگر مطابقت نداشت، یعنی این یک پاسخ قدیمی replay‌شده
        # است، حتی اگر امضایش کاملاً معتبر و اصیل باشد.
        flag = self.forced_sleep_flags.get(device_id)
        if flag is not None:
            # --- تشخیص «نافرمانی از دستور خواب» ---
            # اولین باری که مرکز force_sleep را اعلام می‌کند، صرفاً یک اطلاع‌رسانی
            # است (شاید گوشی هنوز خبر نداشت). ولی اگر این *دومین یا بیشتر* تماسی
            # است که با وجود flag فعال دریافت می‌شود، یعنی گوشی قبلاً یک‌بار این
            # دستور را گرفته و باز هم دوباره وصل شده - این دقیقاً همان «نافرمانی از
            # دستور خواب» است (چه به‌خاطر هک عمدی sleep()/handle_center_response،
            # چه به‌خاطر یک باگ/حلقه‌ی خودکار در گوشی) و باید strike بگیرد.
            already_notified = flag.get("notified", False)
            just_revoked = False
            if already_notified:
                just_revoked = self._register_strike(
                    device_id, reason="نافرمانی از دستور خواب اجباری (تماس مجدد پس از اطلاع قبلی)"
                )
            flag["notified"] = True

            response = {
                "status": "accepted_but_force_sleep",
                "device_id": device_id,
                "chain_length": len(chain),
                "in_response_to_nonce": block["nonce"],
                "in_response_to_hash": block["hash"],
                "directive": {"force_sleep": True, "reason": flag["reason"]},
                "trust_strikes": self.trust_strikes.get(device_id, 0),
                "revoked": just_revoked,
                "message": (
                    f"⚠️ بلوک #{block['index']} از نظر امنیتی معتبر بود و ثبت شد، اما این دستگاه برای خواب "
                    f"اجباری علامت‌گذاری شده (دلیل: {flag['reason']}). ماموریت اجرا نمی‌شود؛ گوشی باید فوراً بخوابد."
                    + (" ⚠️ این دومین/چندمین باری بود که با وجود اطلاع قبلی دوباره تماس گرفت؛ این یک strike ثبت شد."
                       if already_notified else "")
                    + (" 🔴 سقف تخلف رسید: اعتماد این دستگاه برای همیشه نابود شد (trust suicide)." if just_revoked else "")
                ),
            }
            return self._sign_response(response)

        response = {
            "status": "accepted",
            "device_id": device_id,
            "chain_length": len(chain),
            "in_response_to_nonce": block["nonce"],
            "in_response_to_hash": block["hash"],
            "directive": {"force_sleep": False},
            "message": f"✅ بلوک #{block['index']} تأیید و ماموریت به دستگاه ابلاغ می‌شود."
        }
        return self._sign_response(response)

