"""
Static IP and Network Discovery Helper ('Feet' Connectivity).
Detects local network IPs, WAN endpoints, and generates Android connection strings.
"""

from __future__ import annotations

import logging
import socket
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger("qwen_hands_eyes.static_ip")


class NetworkHelper:
    """Discovers IP addresses and formats mobile connection guides."""

    @staticmethod
    def get_local_ip() -> str:
        """Find the local machine IP on the LAN (e.g. 192.168.1.50)."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Doesn't have to be reachable; just triggers route selection
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        except Exception:
            ip = "127.0.0.1"
        finally:
            s.close()
        return ip

    @staticmethod
    def get_public_ip(timeout: int = 3) -> Optional[str]:
        """Query public WAN IP from an external echo endpoint."""
        services = ["https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"]
        for svc in services:
            try:
                req = urllib.request.Request(svc, headers={"User-Agent": "SkyGround-IPFinder/1.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    ip = resp.read().decode("utf-8").strip()
                    if ip:
                        return ip
            except Exception:
                continue
        return None

    @classmethod
    def get_connection_info(cls, port: int = 8765, static_ip_override: str = "") -> Dict[str, Any]:
        local_ip = cls.get_local_ip()
        public_ip = cls.get_public_ip()
        effective_ip = static_ip_override or local_ip

        return {
            "local_ip": local_ip,
            "public_ip": public_ip,
            "effective_ip": effective_ip,
            "port": port,
            "local_api_url": f"http://{local_ip}:{port}/api/v1",
            "effective_api_url": f"http://{effective_ip}:{port}/api/v1",
            "dashboard_url": f"http://{effective_ip}:{port}",
            "android_config": {
                "base_url": f"http://{effective_ip}:{port}",
                "chat_endpoint": f"/api/v1/chat",
                "eyes_endpoint": f"/api/v1/eyes/snapshot",
                "hands_endpoint": f"/api/v1/hands/action",
            },
        }
