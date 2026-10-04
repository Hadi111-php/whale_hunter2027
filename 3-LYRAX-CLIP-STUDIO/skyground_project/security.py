"""
Security helpers for SkyGround Local Agent.

Focus:
- Best-effort secret detection/masking before data is shown in dashboard/logs/memory/LLM context.
- Sensitive path heuristics.

No external dependencies.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple


SECRET_PLACEHOLDER = "[SECRET_MASKED]"


SENSITIVE_FILE_GLOBS = (
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "**/secrets/**",
    "**/secret/**",
    "**/credentials/**",
    "**/.aws/credentials",
    "**/.ssh/**",
)


# (name, regex, replacement function)
# Keep patterns intentionally broad but conservative enough for common tokens.
SECRET_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    (
        "private_key_block",
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.MULTILINE,
        ),
    ),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    (
        "key_value_secret",
        re.compile(
            r"(?im)^([+\- ]?\s*(?:[A-Z0-9_\-]*?(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|PRIVATE[_-]?KEY|ACCESS[_-]?KEY|AUTH|CLIENT[_-]?SECRET|DATABASE_URL|DB_URL|CONNECTION_STRING)[A-Z0-9_\-]*?)\s*[=:]\s*)([^\s#,'\"]{6,}|['\"][^'\"]{6,}['\"])",
        ),
    ),
    (
        "json_secret",
        re.compile(
            r"(?i)(\"(?:api[_-]?key|token|secret|password|client[_-]?secret|access[_-]?key|authorization|auth)\"\s*:\s*\")(.*?)(\")"
        ),
    ),
    (
        "bearer_token",
        re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._\-+/=]{12,})"),
    ),
    (
        "basic_auth_url",
        # پشتیبانی از http/https + connection stringهای رایج دیتابیس/کش که خودشان اسکیم دارند
        # (postgres/postgresql/mysql/mongodb/mongodb+srv/redis/rediss/amqp/amqps).
        # بدون این، یک DATABASE_URL مثل postgres://user:pass@host/db هرگز ماسک نمی‌شد.
        # نکته‌ی مهم: کلاس کاراکتر پسورد عمداً [^/\s]+ است (نه [^@/\s]+) تا اگر خودِ
        # پسورد کاراکتر '@' داشته باشد (مثل MyP@ssw0rd)، به‌خاطر رفتار حریص (greedy) '+'
        # رجکس تا آخرین '@' قبل از هاست جلو برود و کل پسورد (نه فقط بخشی از آن) ماسک شود.
        re.compile(r"(?i)((?:https?|postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|rediss|amqp|amqps)://)([^:/\s]*):([^/\s]+)@"),
    ),
]


def _short_mask(value: str, keep: int = 4) -> str:
    raw = value.strip("'\"")
    quote_prefix = value[:1] if value[:1] in {"'", '"'} else ""
    quote_suffix = value[-1:] if value[-1:] in {"'", '"'} else ""
    if len(raw) <= keep:
        masked = SECRET_PLACEHOLDER
    else:
        masked = raw[:keep] + "…" + SECRET_PLACEHOLDER
    return quote_prefix + masked + quote_suffix


def mask_secrets(text: str) -> str:
    """Best-effort masking of common secrets in text."""
    if not text:
        return text
    masked = text

    # Blocks and simple full-value tokens.
    for name, pattern in SECRET_PATTERNS:
        if name in {"key_value_secret", "json_secret", "bearer_token", "basic_auth_url"}:
            continue
        masked = pattern.sub(lambda m: _short_mask(m.group(0)), masked)

    # Bearer token first, so `Authorization: Bearer TOKEN` does not leak after key/value masking.
    bearer = dict(SECRET_PATTERNS)["bearer_token"]
    masked = bearer.sub(lambda m: m.group(1) + _short_mask(m.group(2)), masked)

    # URL basic auth: preserve username, mask password.
    basic = dict(SECRET_PATTERNS)["basic_auth_url"]
    masked = basic.sub(lambda m: m.group(1) + m.group(2) + ":" + SECRET_PLACEHOLDER + "@", masked)

    # KEY=value style: preserve key and operator.
    key_value = dict(SECRET_PATTERNS)["key_value_secret"]
    masked = key_value.sub(lambda m: m.group(1) + _short_mask(m.group(2)), masked)

    # JSON style: preserve key and quotes.
    json_secret = dict(SECRET_PATTERNS)["json_secret"]
    masked = json_secret.sub(lambda m: m.group(1) + _short_mask(m.group(2)) + m.group(3), masked)

    return masked


def find_secrets(text: str) -> List[Dict[str, Any]]:
    """Return approximate detections without exposing full values."""
    findings: List[Dict[str, Any]] = []
    if not text:
        return findings
    for name, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(
                {
                    "type": name,
                    "start": match.start(),
                    "end": match.end(),
                    "preview": _short_mask(match.group(0)[:80]),
                }
            )
            if len(findings) >= 100:
                return findings
    return findings


def _sensitive_key(key: str) -> bool:
    return bool(re.search(r"(?i)(api[_-]?key|token|secret|password|passwd|pwd|authorization|auth|private[_-]?key|access[_-]?key|client[_-]?secret|database_url|db_url|connection_string)", key))


def sanitize_for_display(value: Any, max_string: int | None = None) -> Any:
    """Recursively mask secrets before sending data to logs/dashboard/memory."""
    if isinstance(value, str):
        s = mask_secrets(value)
        if max_string is not None and len(s) > max_string:
            s = s[:max_string] + f"\n... [truncated {len(s) - max_string} chars]"
        return s
    if isinstance(value, list):
        return [sanitize_for_display(v, max_string=max_string) for v in value]
    if isinstance(value, tuple):
        return tuple(sanitize_for_display(v, max_string=max_string) for v in value)
    if isinstance(value, dict):
        safe: Dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if _sensitive_key(key) and isinstance(v, str):
                safe[key] = _short_mask(v)
            else:
                safe[key] = sanitize_for_display(v, max_string=max_string)
        return safe
    return value


def looks_sensitive_path(path: str, extra_globs: Tuple[str, ...] = ()) -> bool:
    import fnmatch

    normalized = str(path).replace("\\", "/").lstrip("/")
    name = Path(normalized).name
    for pattern in (*SENSITIVE_FILE_GLOBS, *extra_globs):
        p = pattern.replace("\\", "/")
        if fnmatch.fnmatch(normalized, p) or fnmatch.fnmatch(name, p):
            return True
        # fnmatch در پایتون "**" را واقعاً به‌صورت segment-aware تفسیر نمی‌کند؛ الگوهایی مثل
        # "**/secrets/**" که قصدشان "هر جای مسیر از جمله ریشه" است، وقتی مسیر مستقیماً با
        # همان پوشه شروع شود (بدون هیچ پوشه‌ی والدی)، match نمی‌شوند چون "**/" به یک '/'
        # واقعی قبل از خودش نیاز دارد. برای رفع این نقص، همان الگو را بدون پیشوند "**/"
        # هم روی مسیر امتحان می‌کنیم (یعنی حالت "مستقیم زیر ریشه‌ی پروژه").
        if p.startswith("**/"):
            root_variant = p[3:]
            if fnmatch.fnmatch(normalized, root_variant):
                return True
    return False