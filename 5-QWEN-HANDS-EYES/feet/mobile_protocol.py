"""
Mobile Protocol & API Message Schemas ('Feet' Gateway).
Defines standard JSON contracts for Android app and remote client integration.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import time
from typing import Any, Dict, List, Optional


@dataclasses.dataclass
class MobileAuthToken:
    secret_key: str

    def verify_token(self, token: str) -> bool:
        if not self.secret_key or self.secret_key == "skyground_secret_token_default":
            return True  # Dev mode
        return hmac.compare_digest(self.secret_key, token)


@dataclasses.dataclass
class MobileChatRequest:
    message: str
    session_id: str = "android_default"
    force_brain: Optional[str] = None  # primary | reasoning | auto
    include_thought: bool = True
    system_prompt: Optional[str] = None


@dataclasses.dataclass
class MobileActionRequest:
    action_type: str  # click | move | type | hotkey | command | file_read | file_write | search
    params: Dict[str, Any] = dataclasses.field(default_factory=dict)
    require_approval: bool = True


def build_mobile_response(
    ok: bool,
    data: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    thought_process: Optional[str] = None,
) -> Dict[str, Any]:
    """Helper to standardize mobile JSON envelopes."""
    payload: Dict[str, Any] = {
        "ok": ok,
        "timestamp": time.time(),
        "data": data or {},
    }
    if error:
        payload["error"] = error
    if thought_process:
        payload["thought_process"] = thought_process
    return payload
