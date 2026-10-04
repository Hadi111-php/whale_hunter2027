"""
Desktop State Observer ('Eyes' Integration Layer).
Combines visual screen snapshots, active window detection, and application log observation.
"""

from __future__ import annotations

import datetime as dt
import logging
import platform
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from eyes.screen_capture import ScreenCaptureEngine
from eyes.visual_locator import VisualLocator
from eyes.vlm_client import VLMVisionClient

logger = logging.getLogger("qwen_hands_eyes.desktop_observer")


class DesktopObserver:
    """Provides real-time multimodal perception of the host operating system."""

    def __init__(
        self,
        capture_engine: ScreenCaptureEngine,
        vlm_client: Optional[VLMVisionClient] = None,
        snapshots_dir: str = ".qwen_hands_eyes/snapshots",
    ):
        self.capture_engine = capture_engine
        self.vlm_client = vlm_client
        self.locator = VisualLocator()
        self.observed_logs: List[Path] = []
        self.history: List[Dict[str, Any]] = []

    def get_active_window_info(self) -> Dict[str, str]:
        """Detect current active window title and process name."""
        system = platform.system().lower()
        if system == "windows":
            try:
                ps_cmd = (
                    "Add-Type @'\n"
                    "using System;\n"
                    "using System.Runtime.InteropServices;\n"
                    "public class User32 {\n"
                    "    [DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow();\n"
                    "    [DllImport(\"user32.dll\")] public static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder text, int count);\n"
                    "}\n"
                    "'@\n"
                    "$hwnd = [User32]::GetForegroundWindow()\n"
                    "$sb = New-Object System.Text.StringBuilder 256\n"
                    "[User32]::GetWindowText($hwnd, $sb, 256) | Out-Null\n"
                    "$sb.ToString()"
                )
                proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True, timeout=3)
                title = proc.stdout.strip()
                return {"title": title, "platform": "windows", "status": "active"}
            except Exception as e:
                return {"title": "Unknown", "error": str(e), "platform": "windows"}
        elif system == "linux":
            try:
                proc = subprocess.run(["xdotool", "getactivewindow", "getwindowname"], capture_output=True, text=True, timeout=3)
                if proc.returncode == 0:
                    return {"title": proc.stdout.strip(), "platform": "linux", "status": "active"}
            except Exception:
                pass
            return {"title": "Linux Desktop / Headless Session", "platform": "linux", "status": "unknown"}

        return {"title": f"{platform.system()} Desktop", "platform": system, "status": "unknown"}

    def capture_and_inspect(
        self,
        prompt: str = "Analyze screen and describe open windows, text, and actionable buttons.",
        save_file: bool = True,
    ) -> Dict[str, Any]:
        """Take a screenshot, get window info, and query VLM for semantic understanding."""
        snap = self.capture_engine.capture_screen(save_file=save_file)
        self.locator.update_screen_dimensions(snap["width"], snap["height"])
        win_info = self.get_active_window_info()

        vlm_res = {}
        if self.vlm_client and snap.get("base64_png"):
            vlm_res = self.vlm_client.analyze_image(
                base64_image=snap["base64_png"],
                prompt=prompt,
            )

        observation = {
            "timestamp": time.time(),
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "screen": {
                "width": snap["width"],
                "height": snap["height"],
                "file_path": snap.get("file_path", ""),
                "backend": snap.get("backend", ""),
            },
            "active_window": win_info,
            "visual_analysis": vlm_res.get("response", "VLM not configured or offline"),
            "raw_snapshot": snap if not save_file else None,
        }

        self.history.append(observation)
        self.history = self.history[-50:]
        return observation
