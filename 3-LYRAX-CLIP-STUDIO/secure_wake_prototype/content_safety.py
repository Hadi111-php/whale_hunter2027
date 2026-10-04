# -*- coding: utf-8 -*-
"""
🛡️ فایروال محتوایی (Content Safety Layer)

این ماژول جدا از لایه‌ی احراز هویت (امضا/زنجیره/nonce) است. آن لایه فقط ثابت
می‌کند «این پیام واقعاً از همین دستگاه آمده»، ولی هیچ تضمینی درباره‌ی خطرناک
بودن *محتوای* پیام نمی‌دهد — چون حتی صاحب قانونی گوشی هم می‌تواند (چه هکر باشد
چه خودِ کاربر که دستگاهش هک شده) یک دستور مخرب امضاشده بفرستد.

طبق درخواست صریح: «دست‌وچشم و مرکز باید محیطشان امن باشد و درخواست باید چک
بشود که متن معمولی است، نه کد مخرب یا کرم اجرایی». این ماژول دقیقاً همین کار
را می‌کند: مستقل از هویت فرستنده، به خودِ محتوا مشکوک می‌شود.
"""
import re
import string

# دستورات/عبارت‌های شناخته‌شده‌ی مخرب که هرگز نباید در هیچ payload ای، حتی اگر
# امضای معتبر داشته باشد، پذیرفته شوند.
DANGEROUS_COMMAND_FRAGMENTS = (
    "rm -rf /", "rm -rf ~", "sudo rm", "mkfs", "format c:", "del /s /q",
    "rmdir /s",
    "shutdown", "reboot -f", "reg delete", "diskpart",
    "remove-item -recurse -force c:\\", "remove-item -recurse -force /",
    "dd if=/dev/zero", "dd if=/dev/random",
    "chmod -r 777 /", "chown -r",
    "> /dev/sda", "wget http", "curl http",  # دانلود/اجرای بی‌واسطه‌ی کد از اینترنت
)

# الگوهای شبه‌کرم/شبه‌اسکریپت که نشان می‌دهند این یک متن دستوری معمولی نیست
SUSPICIOUS_PATTERNS = (
    re.compile(r"#!\s*/(bin|usr)/(ba)?sh"),          # shebang اسکریپت
    re.compile(r"powershell\s+-enc(odedcommand)?", re.IGNORECASE),  # پی‌اس امضاشده/انکد
    re.compile(r"base64\s+-d\s*\|", re.IGNORECASE),  # دیکود+اجرای مستقیم base64
    re.compile(r"eval\s*\(", re.IGNORECASE),         # اجرای کد پویا
    re.compile(r"exec\s*\(", re.IGNORECASE),
    re.compile(r"/etc/(passwd|shadow)"),             # دستکاری فایل‌های حیاتی سیستم
    re.compile(r"\\x[0-9a-f]{2}(\\x[0-9a-f]{2}){8,}", re.IGNORECASE),  # shellcode خام
    # Fork bomb به سبک bash؛ فاصله‌های اختیاری بین توکن‌ها پوشش داده می‌شود چون
    # نسخه‌ی بدون‌فاصله (که در تست اول به اشتباه به‌عنوان رشته‌ی خام گذاشته شده
    # بود) با دستور واقعی که معمولاً با فاصله نوشته می‌شود مطابقت پیدا نمی‌کرد؛
    # این باگ با تست واقعی پیدا و همین‌جا با یک regex منعطف‌تر رفع شد.
    re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"),
)


def _printable_ratio(text: str) -> float:
    if not text:
        return 1.0
    printable = sum(1 for ch in text if ch in string.printable or ch.isprintable())
    return printable / len(text)


def scan_payload(payload) -> dict:
    """
    محتوای payload (dict/str) یک درخواست را بررسی می‌کند و اگر مشکوک به کد
    مخرب/کرم اجرایی/دستور فاجعه‌بار بود، safe=False برمی‌گرداند، همراه با دلیل.
    این تابع کاملاً مستقل از اینکه فرستنده چه کسی است (حتی صاحب قانونی گوشی)
    اجرا می‌شود؛ صرفاً به خودِ متن نگاه می‌کند.
    """
    text = payload if isinstance(payload, str) else str(payload)
    lowered = text.lower()

    for frag in DANGEROUS_COMMAND_FRAGMENTS:
        if frag in lowered:
            return {"safe": False, "reason": f"دستور شناخته‌شده‌ی مخرب/فاجعه‌بار شناسایی شد: «{frag}»"}

    for pattern in SUSPICIOUS_PATTERNS:
        if pattern.search(text):
            return {"safe": False, "reason": f"الگوی مشکوک به کد اجرایی/کرم شناسایی شد: {pattern.pattern}"}

    ratio = _printable_ratio(text)
    if ratio < 0.85:
        return {
            "safe": False,
            "reason": f"محتوا شبیه متن معمولی نیست (فقط {ratio*100:.0f}% کاراکترهای قابل‌چاپ) — احتمال محتوای باینری/کرم اجرایی",
        }

    if len(text) > 20000:
        return {"safe": False, "reason": "طول محتوا غیرعادی زیاد است (احتمال payload حجیم/شل‌کد)"}

    return {"safe": True, "reason": None}
