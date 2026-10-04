# -*- coding: utf-8 -*-
"""
🔒 ابزارهای حفاظت از داده‌ی شخصی (PII) برای لایه‌ی پلتفرم

قانون طلایی این ماژول: شماره تلفن و ایمیل کاربران **هرگز به‌صورت خام** در
هیچ دیتابیس/لاگ/داشبورد ذخیره یا نمایش داده نمی‌شوند؛ فقط نسخه‌ی ماسک‌شده
ذخیره می‌شود و مقدار خام فقط برای مدت کوتاه (مثلاً ارسال پیامک تایید) در
حافظه می‌ماند و بلافاصله بعد از استفاده دور ریخته می‌شود.

این جدا از content_safety.py (که محتوای دستورات را چک می‌کند) است؛ این
ماژول مخصوص داده‌ی هویتی/تماسی کاربر است.
"""
import hashlib
import re

PHONE_RE = re.compile(r"^\+?\d{7,15}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def mask_phone(phone: str) -> str:
    """09123456789 -> 0912***6789 (۴ رقم اول و ۴ رقم آخر حفظ می‌شود، وسط ماسک)."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) <= 8:
        return "*" * len(digits)
    return digits[:4] + "*" * (len(digits) - 8) + digits[-4:]


def mask_email(email: str) -> str:
    """ali.rezaei@example.com -> al***@ex***.com"""
    if not email or "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    domain_name, _, tld = domain.rpartition(".")
    masked_local = (local[:2] + "***") if len(local) > 2 else "***"
    masked_domain = (domain_name[:2] + "***") if len(domain_name) > 2 else "***"
    return f"{masked_local}@{masked_domain}.{tld}" if tld else f"{masked_local}@{masked_domain}"


def validate_phone(phone: str) -> bool:
    return bool(PHONE_RE.match(re.sub(r"[\s-]", "", phone or "")))


def validate_email(email: str) -> bool:
    return bool(EMAIL_RE.match((email or "").strip()))


def fingerprint(value: str) -> str:
    """
    یک اثرانگشت غیرقابل‌بازگشت (هش) برای تشخیص تکراری بودن یک شماره/ایمیل،
    بدون اینکه نیاز باشد مقدار خام نگه داشته شود (مثلاً برای جلوگیری از
    ثبت‌نام دوباره با همان شماره، بدون اینکه خودِ شماره جایی ذخیره شود).
    """
    return hashlib.sha256((value or "").strip().lower().encode("utf-8")).hexdigest()
