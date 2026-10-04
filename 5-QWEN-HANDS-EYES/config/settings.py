"""
Configuration and Settings Manager for Qwen-Hands-Eyes (SkyGround OS)
Parametric, modular, and extensible configuration with environment variable overrides.
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclasses.dataclass
class LLMModelConfig:
    provider: str = "ollama"  # ollama | vllm | llama_cpp | openai_compatible | deepseek_api
    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5:7b-instruct-q4_K_M"
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 0.9
    num_ctx: int = 8192
    api_key: str = ""
    timeout_sec: int = 120

    def to_dict(self) -> Dict[str, Any]:
        d = dataclasses.asdict(self)
        if d.get("api_key"):
            d["api_key"] = "***masked***"
        return d


@dataclasses.dataclass
class ReasoningBrainConfig:
    enabled: bool = True
    provider: str = "ollama"  # ollama | openai_compatible | deepseek_api
    base_url: str = "http://localhost:11434"
    model: str = "deepseek-r1:7b"
    temperature: float = 0.6
    max_tokens: int = 8192
    api_key: str = ""
    timeout_sec: int = 180
    auto_translate_persian: bool = True
    preserve_reasoning_tags: bool = True  # Preserve <think>...</think>
    trigger_mode: str = "auto"  # auto | always | manual | keywords
    routing_keywords: List[str] = dataclasses.field(
        default_factory=lambda: [
            "code", "algorithm", "math", "reasoning", "logic", "debug", "script", "function", "python", "fix",
            "کد", "برنامه‌نویسی", "الگوریتم", "ریاضی", "استدلال", "منطق", "دیباگ", "تحلیل", "محاسبه", "تابع", "پایتون", "اسکریپت"
        ]
    )

    def to_dict(self) -> Dict[str, Any]:
        d = dataclasses.asdict(self)
        if d.get("api_key"):
            d["api_key"] = "***masked***"
        return d


@dataclasses.dataclass
class EyesConfig:
    enabled: bool = True
    vlm_provider: str = "ollama"
    vlm_base_url: str = "http://localhost:11434"
    vlm_model: str = "qwen2-vl:7b"  # or llava:7b, minicpm-v
    vlm_api_key: str = ""
    screen_capture_interval: float = 1.0
    max_image_dimension: int = 1280
    ocr_engine: str = "vlm"  # vlm | tesseract | mock
    auto_observe_desktop: bool = False
    save_snapshots_dir: str = ".qwen_hands_eyes/snapshots"


@dataclasses.dataclass
class HandsConfig:
    enabled: bool = True
    safe_mode: bool = True
    require_approval: bool = True
    auto_approve_low_risk: bool = False
    mouse_speed: float = 0.2
    failsafe_corner: bool = True
    command_timeout_sec: int = 30
    max_file_read_chars: int = 20000
    create_backups: bool = True
    backup_dir: str = ".qwen_hands_eyes/backups"
    allowed_cwd_root: str = "."
    blocked_commands: List[str] = dataclasses.field(
        default_factory=lambda: [
            "rm -rf /", "rmdir /s /q c:\\", "mkfs", "dd if=", ":(){ :|:& };:",
            "format c:", "del /f /s /q c:\\windows", "shutdown", "reboot"
        ]
    )


@dataclasses.dataclass
class FeetConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8765
    static_ip: str = ""  # Static IP or domain if configured
    api_token: str = "skyground_secret_token_default"
    enable_cors: bool = True
    enable_websocket: bool = True
    mobile_friendly_payloads: bool = True
    push_webhook_url: str = ""


@dataclasses.dataclass
class MemoryConfig:
    sqlite_path: str = ".qwen_hands_eyes/memory.sqlite"
    dsa_fade_not_forget: bool = True
    dsa_lambda: float = 0.15
    dsa_gamma: float = 0.4
    dsa_min: float = 0.15
    max_recent_memories: int = 10
    max_search_results: int = 6


@dataclasses.dataclass
class AppConfig:
    agent_name: str = "Qwen-Hands-Eyes (SkyGround OS)"
    mode: str = "dual_brain"  # dual_brain | qwen_direct | deepseek_direct | api_bridge | hybrid_auto
    workspace_root: str = "."
    primary_brain: LLMModelConfig = dataclasses.field(default_factory=LLMModelConfig)
    reasoning_brain: ReasoningBrainConfig = dataclasses.field(default_factory=ReasoningBrainConfig)
    eyes: EyesConfig = dataclasses.field(default_factory=EyesConfig)
    hands: HandsConfig = dataclasses.field(default_factory=HandsConfig)
    feet: FeetConfig = dataclasses.field(default_factory=FeetConfig)
    memory: MemoryConfig = dataclasses.field(default_factory=MemoryConfig)

    @classmethod
    def load(cls, path: Optional[str | Path] = None) -> "AppConfig":
        config = cls()
        config_path = Path(path) if path else Path("config/config.json")
        if not config_path.exists():
            config_path = Path("config.json")

        if config_path.exists():
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
                config._apply_dict(data)
            except Exception as e:
                print(f"⚠️ Warning: Failed to parse config file {config_path}: {e}. Using defaults.")

        # Environment variable overrides
        config._apply_env_overrides()
        return config

    def _apply_dict(self, data: Dict[str, Any]) -> None:
        if "agent_name" in data:
            self.agent_name = str(data["agent_name"])
        if "mode" in data:
            self.mode = str(data["mode"])
        if "workspace_root" in data:
            self.workspace_root = str(data["workspace_root"])

        if "primary_brain" in data and isinstance(data["primary_brain"], dict):
            for k, v in data["primary_brain"].items():
                if hasattr(self.primary_brain, k):
                    setattr(self.primary_brain, k, v)

        if "reasoning_brain" in data and isinstance(data["reasoning_brain"], dict):
            for k, v in data["reasoning_brain"].items():
                if hasattr(self.reasoning_brain, k):
                    setattr(self.reasoning_brain, k, v)

        if "eyes" in data and isinstance(data["eyes"], dict):
            for k, v in data["eyes"].items():
                if hasattr(self.eyes, k):
                    setattr(self.eyes, k, v)

        if "hands" in data and isinstance(data["hands"], dict):
            for k, v in data["hands"].items():
                if hasattr(self.hands, k):
                    setattr(self.hands, k, v)

        if "feet" in data and isinstance(data["feet"], dict):
            for k, v in data["feet"].items():
                if hasattr(self.feet, k):
                    setattr(self.feet, k, v)

        if "memory" in data and isinstance(data["memory"], dict):
            for k, v in data["memory"].items():
                if hasattr(self.memory, k):
                    setattr(self.memory, k, v)

    def _apply_env_overrides(self) -> None:
        if os.getenv("AGENT_MODE"):
            self.mode = os.getenv("AGENT_MODE", self.mode)
        if os.getenv("OLLAMA_URL"):
            self.primary_brain.base_url = os.getenv("OLLAMA_URL", self.primary_brain.base_url)
            self.reasoning_brain.base_url = os.getenv("OLLAMA_URL", self.reasoning_brain.base_url)
            self.eyes.vlm_base_url = os.getenv("OLLAMA_URL", self.eyes.vlm_base_url)
        if os.getenv("PRIMARY_MODEL"):
            self.primary_brain.model = os.getenv("PRIMARY_MODEL", self.primary_brain.model)
        if os.getenv("REASONING_MODEL"):
            self.reasoning_brain.model = os.getenv("REASONING_MODEL", self.reasoning_brain.model)
        if os.getenv("DEEPSEEK_API_KEY"):
            self.reasoning_brain.api_key = os.getenv("DEEPSEEK_API_KEY", "")
        if os.getenv("AGENT_PORT"):
            try:
                self.feet.port = int(os.getenv("AGENT_PORT", "8765"))
            except ValueError:
                pass
        if os.getenv("AGENT_STATIC_IP"):
            self.feet.static_ip = os.getenv("AGENT_STATIC_IP", "")
        if os.getenv("AGENT_API_TOKEN"):
            self.feet.api_token = os.getenv("AGENT_API_TOKEN", self.feet.api_token)

    def save(self, path: Optional[str | Path] = None) -> None:
        config_path = Path(path) if path else Path("config/config.json")
        config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "agent_name": self.agent_name,
            "mode": self.mode,
            "workspace_root": self.workspace_root,
            "primary_brain": dataclasses.asdict(self.primary_brain),
            "reasoning_brain": dataclasses.asdict(self.reasoning_brain),
            "eyes": dataclasses.asdict(self.eyes),
            "hands": dataclasses.asdict(self.hands),
            "feet": dataclasses.asdict(self.feet),
            "memory": dataclasses.asdict(self.memory),
        }
        config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def to_safe_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "mode": self.mode,
            "workspace_root": self.workspace_root,
            "primary_brain": self.primary_brain.to_dict(),
            "reasoning_brain": self.reasoning_brain.to_dict(),
            "eyes": dataclasses.asdict(self.eyes),
            "hands": dataclasses.asdict(self.hands),
            "feet": dataclasses.asdict(self.feet),
            "memory": dataclasses.asdict(self.memory),
        }
