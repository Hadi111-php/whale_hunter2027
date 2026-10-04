# -*- coding: utf-8 -*-
"""
🦾 شبیه‌سازی «چشم و دست» روی گوشی کاربر (Device Agent)

این ماژول رفتار گوشی رو شبیه‌سازی می‌کنه:
- یک‌بار (موقع نصب) یک جفت کلید Ed25519 می‌سازه. کلید خصوصی هرگز از گوشی خارج نمی‌شه
  (در دنیای واقعی باید داخل Android Keystore / iOS Secure Enclave ساخته بشه، جوری که
  حتی خود سیستم‌عامل هم نتونه بایت‌های خام کلید رو بیرون بکشه، فقط بتونه ازش «امضا» بخواد).
- هر بار که کاربر دستی «بیدارش» می‌کنه، یک بلوک جدید به زنجیره‌ی محلی‌ش اضافه می‌کنه
  (دقیقاً مثل بلاکچین: هر بلوک هش بلوک قبلی رو داره؛ اگر یکی از وسط دستکاری بشه،
  همه‌ی بلوک‌های بعدی نامعتبر می‌شن).
- هر بلوک رو با کلید خصوصی امضا می‌کنه تا مرکز مطمئن بشه واقعاً همون گوشیه.
"""

import hashlib
import json
import time
import threading
import secrets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

GENESIS_HASH = "0" * 64
DEFAULT_MAX_AWAKE_SECONDS = 60  # واچ‌داگ پیش‌فرض: حداکثر مدت مجاز بیداری بدون فعالیت


def _canonical_json(obj):
    """سریالایز قطعی (ترتیب کلیدها ثابت) تا هش/امضا همیشه یکسان محاسبه بشه."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


class DeviceAgent:
    def __init__(self, device_id: str, center_public_key_hex: str = None):
        self.device_id = device_id
        # --- شبیه‌سازی Secure Enclave / Android Keystore ---
        # در دنیای واقعی این کلید هرگز به‌صورت متن خام قابل استخراج از گوشی نیست.
        self._private_key = Ed25519PrivateKey.generate()
        self.public_key = self._private_key.public_key()
        self.public_key_bytes = self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        ).hex()

        # کلید عمومی مرکز، از قبل (مثلاً هنگام نصب اپ) روی گوشی جاسازی می‌شود تا
        # گوشی بتواند صحت هر پاسخی که ادعا می‌کند از طرف مرکز آمده را تایید کند.
        # بدون این، یک مهاجم Man-in-the-Middle می‌تواند دستور force_sleep را در
        # مسیر حذف/دستکاری کند (این آسیب‌پذیری با تست واقعی کشف و اینجا رفع شد).
        self._center_public_key_hex = center_public_key_hex
        self.last_forced_sleep_reason = None
        # آخرین nonce/hash بلوکی که خودِ همین گوشی فرستاده؛ برای تشخیص Replay
        # پاسخ‌های قدیمیِ معتبر مرکز لازم است (رفع آسیب‌پذیری‌ای که با تست کشف شد).
        self._last_sent_nonce = None
        self._last_sent_hash = None

        # زنجیره‌ی محلی بلوک‌ها (شبیه بلاکچین) - فقط همین گوشی نگهش می‌داره
        self.chain = []
        self.last_hash = GENESIS_HASH
        self.is_awake = False

        # --- واچ‌داگ خودکار (لایه‌ی دفاعی «خودکشیِ» نرم، نه قطعی) ---
        # این یک تایمر پس‌زمینه‌ی مستقل از توابع wake_up/sleep/handle_center_response
        # است: اگر گوشی بیش از max_awake_seconds بیدار بماند (چه به‌خاطر فراموشیِ
        # برنامه، چه قطعی شبکه، چه هر دلیل دیگری)، خودش را می‌خواباند - حتی اگر
        # هیچ پاسخی از مرکز نرسیده باشد. این یک fail-safe عمومی است، **نه** دفاع
        # در برابر هکری که خودِ کد گوشی را عمداً دستکاری می‌کند (چون در آن سناریو
        # هکر همین تایمر را هم می‌تواند غیرفعال کند - این محدودیت صادقانه در
        # README مستند شده و دلیل اصلیِ نیاز به لایه‌ی مکمل سمت مرکز است).
        self.max_awake_seconds = DEFAULT_MAX_AWAKE_SECONDS
        self._awake_since = None
        self._watchdog_thread = None
        self._watchdog_stop_event = threading.Event()
        self.watchdog_triggered_count = 0  # برای تست/مشاهده: چند بار واچ‌داگ واقعاً خواباند

    # ---------------------------------------------------------------
    # مرحله‌ی ۱: کاربر دستی دکمه‌ی «بیدار شو» رو می‌زند (Physical Trigger)
    # ---------------------------------------------------------------
    def wake_up(self):
        """فقط با اقدام دستی کاربر صدا زده می‌شود؛ هیچ سرور/پوشی نمی‌تواند این را از راه دور فراخوانی کند."""
        self.is_awake = True
        self._awake_since = time.time()
        self._start_watchdog()

    def sleep(self):
        self.is_awake = False
        self._awake_since = None
        self._stop_watchdog()

    # ---------------------------------------------------------------
    # واچ‌داگ داخلی: یک ترد پس‌زمینه‌ی سبک که هر چند صدم ثانیه چک می‌کند آیا
    # زمان مجاز بیداری تمام شده یا نه. عمداً به‌جای یک بار sleep() با تایمر
    # ساده، به‌صورت حلقه پیاده شده تا اگر max_awake_seconds در میانه‌ی راه
    # کوتاه‌تر شود (مثلاً توسط خودِ کاربر/تنظیمات امنیتی) هم بلافاصله اثر کند.
    # ---------------------------------------------------------------
    def _start_watchdog(self):
        self._stop_watchdog()  # اگر ترد قبلی مانده، اول تمیزش کن
        self._watchdog_stop_event = threading.Event()

        def _watch():
            while not self._watchdog_stop_event.is_set():
                if self.is_awake and self._awake_since is not None:
                    elapsed = time.time() - self._awake_since
                    if elapsed >= self.max_awake_seconds:
                        self.is_awake = False
                        self._awake_since = None
                        self.watchdog_triggered_count += 1
                        self.last_forced_sleep_reason = (
                            f"WATCHDOG_TIMEOUT: بیش از {self.max_awake_seconds} ثانیه بدون خوابیدن دستی/دستور مرکز بیدار مانده بود"
                        )
                        return
                self._watchdog_stop_event.wait(0.05)

        self._watchdog_thread = threading.Thread(target=_watch, daemon=True)
        self._watchdog_thread.start()

    def _stop_watchdog(self):
        self._watchdog_stop_event.set()
        self._watchdog_thread = None

    def _verify_center_signature(self, response: dict) -> bool:
        """
        صحت و دست‌نخوردگی پاسخ مرکز را با کلید عمومی مرکز تایید می‌کند.
        اگر کلید عمومی مرکز روی گوشی جاسازی نشده باشد (سناریوی قدیمی/ناقص)،
        به‌صورت محافظه‌کارانه False برمی‌گردانیم؛ یعنی گوشی نباید کورکورانه به
        directive اعتماد کند مگر امضا را واقعاً بتواند تایید کند.
        """
        if not self._center_public_key_hex:
            return False
        signature_hex = response.get("center_signature")
        if not signature_hex:
            return False
        # نکته‌ی مهم: این حذف باید دقیقاً همان فیلدهایی باشد که سمت مرکز در
        # ControlCenter.SIGNATURE_META_FIELDS حذف می‌کند، وگرنه دو طرف روی دو
        # payload متفاوت حساب می‌کنند و امضای درست هم نامعتبر تشخیص داده می‌شود.
        payload_for_signing = {k: v for k, v in response.items() if k != "center_signature"}
        body_bytes = _canonical_json(payload_for_signing)
        digest = hashlib.sha256(body_bytes).digest()
        try:
            pubkey = Ed25519PublicKey.from_public_bytes(bytes.fromhex(self._center_public_key_hex))
            pubkey.verify(bytes.fromhex(signature_hex), digest)
            return True
        except (InvalidSignature, ValueError):
            return False

    def handle_center_response(self, response: dict) -> None:
        """
        بعد از دریافت جواب مرکز، گوشی باید directive.force_sleep را رعایت کند —
        اما فقط اگر امضای مرکز روی این پاسخ معتبر باشد. این تنها راهی است که مرکز
        می‌تواند «خواب» را تحمیل کند: نه با وصل شدن مستقیم به گوشی (که اصلاً ممکن
        نیست، چون گوشی پورتی باز نگه نمی‌دارد)، بلکه با گذاشتن این دستور داخل
        جوابِ همان درخواستی که خودِ گوشی با تصمیم کاربر شروع کرده بود؛ و برای اینکه
        این کانال توسط یک مهاجم میان‌راه قابل‌دستکاری نباشد، پاسخ باید امضا شده باشد.
        """
        if not self._verify_center_signature(response):
            # پاسخ بدون امضای معتبر مرکز است؛ به هیچ directive ای اعتماد نمی‌کنیم
            # (نه force_sleep=True قلابی را قبول می‌کنیم، نه false قلابی را).
            self.last_forced_sleep_reason = "IGNORED_UNSIGNED_OR_INVALID_RESPONSE"
            return

        # --- رفع آسیب‌پذیری Replay پاسخ‌های قدیمیِ معتبر ---
        # حتی اگر امضا کاملاً درست باشد، این پاسخ فقط زمانی قابل‌اعتماد است که واقعاً
        # پاسخ *همین* درخواست اخیر گوشی باشد، نه یک پاسخ قدیمی که یک مهاجم ذخیره و
        # بعداً دوباره تزریق کرده. برای همین nonce/hash پاسخ باید با آخرین درخواستی
        # که خودِ گوشی فرستاده دقیقاً یکسان باشد.
        response_nonce = response.get("in_response_to_nonce")
        response_hash = response.get("in_response_to_hash")
        if response_nonce != self._last_sent_nonce or response_hash != self._last_sent_hash:
            self.last_forced_sleep_reason = "IGNORED_STALE_OR_REPLAYED_RESPONSE"
            return

        directive = (response or {}).get("directive") or {}
        if directive.get("force_sleep"):
            self.is_awake = False
            self._awake_since = None
            self._stop_watchdog()
            self.last_forced_sleep_reason = directive.get("reason", "")

    # ---------------------------------------------------------------
    # مرحله‌ی ۲: ساخت یک بلوک جدید امضاشده و ارسال درخواست به مرکز
    # ---------------------------------------------------------------
    def build_signed_request(self, payload: dict) -> dict:
        if not self.is_awake:
            raise RuntimeError("دستگاه خواب است؛ نمی‌تواند درخواست بسازد (کاربر باید دستی بیدارش کند).")

        nonce = secrets.token_hex(16)          # عدد یک‌بارمصرف تصادفی (ضد replay)
        timestamp = time.time()

        block_body = {
            "device_id": self.device_id,
            "index": len(self.chain),
            "prev_hash": self.last_hash,
            "timestamp": timestamp,
            "nonce": nonce,
            "payload": payload,
        }
        block_hash = hashlib.sha256(_canonical_json(block_body)).hexdigest()

        # امضا با کلید خصوصی (که هرگز از گوشی خارج نمی‌شود)
        signature = self._private_key.sign(bytes.fromhex(block_hash)).hex()

        block = dict(block_body)
        block["hash"] = block_hash
        block["signature"] = signature

        # فقط اگر واقعاً ارسال موفق بود این را به زنجیره‌ی محلی اضافه می‌کنیم
        self.chain.append(block)
        self.last_hash = block_hash
        self._last_sent_nonce = nonce
        self._last_sent_hash = block_hash
        return block
