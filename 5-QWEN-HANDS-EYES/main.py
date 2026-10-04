#!/usr/bin/env python3
"""
═════════════════════════════════════════════════════════════════════════════════
  🧠 Qwen-Hands-Eyes (SkyGround OS) - Autonomous Dual-Brain Agent
  Offline-First Persian AI with Vision ('Eyes'), OS Automation ('Hands'),
  and Mobile Gateway ('Feet').
═════════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import AppConfig
from core.approval_guard import ApprovalGuard
from core.brain_router import DualBrainRouter
from core.memory_engine import MemoryEngine
from eyes.desktop_observer import DesktopObserver
from eyes.screen_capture import ScreenCaptureEngine
from eyes.vlm_client import VLMVisionClient
from feet.api_server import APIGatewayServer
from feet.static_ip_helper import NetworkHelper
from hands.command_executor import SafeCommandExecutor
from hands.file_manager import SafeFileManager
from hands.input_controller import InputController
from hands.web_operator import WebOperator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("qwen_hands_eyes")


def print_banner(config: AppConfig, net_info: dict) -> None:
    banner = f"""
╔═════════════════════════════════════════════════════════════════════════════════╗
║                   🧠 Qwen-Hands-Eyes (SkyGround OS v2.5)                       ║
║           مغز آفلاین دوزبانه با چشم (Eyes)، دست (Hands) و دروازه موبایل (Feet)   ║
╚═════════════════════════════════════════════════════════════════════════════════╝
 🚀 حالت اجرا (Mode): {config.mode}
 🧠 مدل اصلی (Primary): {config.primary_brain.model} ({config.primary_brain.provider})
 🔬 مدل استدلال (Reasoner): {config.reasoning_brain.model} ({'فعال' if config.reasoning_brain.enabled else 'غیرفعال'})
 👁️ چشم و بینایی (Eyes): {'فعال' if config.eyes.enabled else 'غیرفعال'} ({config.eyes.vlm_model})
 🖐️ دست‌ها و فرامین (Hands): {'فعال' if config.hands.enabled else 'غیرفعال'} (Safe Mode: {config.hands.safe_mode})
 🦶 پایگاه موبایل (Feet): http://{net_info['effective_ip']}:{config.feet.port}
 🌐 داشبورد زنده وب: http://localhost:{config.feet.port}
═════════════════════════════════════════════════════════════════════════════════
"""
    print(banner)


def main() -> None:
    parser = argparse.ArgumentParser(description="Qwen-Hands-Eyes Autonomous Agent")
    parser.add_argument("--config", type=str, default="config/config.json", help="Path to config JSON")
    parser.add_argument("--mode", type=str, choices=["dual_brain", "qwen_direct", "deepseek_direct", "api_bridge", "hybrid_auto"], help="Override agent mode")
    parser.add_argument("--host", type=str, default=None, help="Server host IP (e.g. 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None, help="Server port (e.g. 8765)")
    parser.add_argument("--no-server", action="store_true", help="Do not start HTTP/Dashboard server")
    parser.add_argument("--interactive", action="store_true", default=sys.stdin.isatty(), help="Run interactive terminal chat")
    parser.add_argument("--server-only", action="store_true", help="Run HTTP/Dashboard server only in background")
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run mode (no actual mouse clicks)")
    args = parser.parse_args()

    if args.server_only:
        args.interactive = False

    # 1. Load Configuration
    config = AppConfig.load(args.config)
    if args.mode:
        config.mode = args.mode
    if args.host:
        config.feet.host = args.host
    if args.port:
        config.feet.port = args.port

    # 2. Initialize Core Subsystems
    memory = MemoryEngine(
        db_path=config.memory.sqlite_path,
        dsa_enabled=config.memory.dsa_fade_not_forget,
        dsa_lambda=config.memory.dsa_lambda,
        dsa_gamma=config.memory.dsa_gamma,
        dsa_min=config.memory.dsa_min,
    )

    approval_guard = ApprovalGuard(
        safe_mode=config.hands.safe_mode,
        require_approval=config.hands.require_approval,
        auto_approve_low_risk=config.hands.auto_approve_low_risk,
        blocked_commands=config.hands.blocked_commands,
    )

    brain_router = DualBrainRouter(config)

    # 3. Initialize Eyes Subsystem
    screen_capture = ScreenCaptureEngine(output_dir=config.eyes.save_snapshots_dir)
    vlm_client = VLMVisionClient(
        provider=config.eyes.vlm_provider,
        base_url=config.eyes.vlm_base_url,
        model=config.eyes.vlm_model,
        api_key=config.eyes.vlm_api_key,
    ) if config.eyes.enabled else None
    desktop_observer = DesktopObserver(screen_capture, vlm_client, snapshots_dir=config.eyes.save_snapshots_dir)

    # 4. Initialize Hands Subsystem
    input_controller = InputController(
        safe_mode=config.hands.safe_mode,
        mouse_speed=config.hands.mouse_speed,
        failsafe_corner=config.hands.failsafe_corner,
        dry_run=args.dry_run,
    )
    command_executor = SafeCommandExecutor(
        workspace_root=config.workspace_root,
        timeout_sec=config.hands.command_timeout_sec,
        approval_guard=approval_guard,
    )
    file_manager = SafeFileManager(
        workspace_root=config.workspace_root,
        max_read_chars=config.hands.max_file_read_chars,
        create_backups=config.hands.create_backups,
        backup_dir=config.hands.backup_dir,
        approval_guard=approval_guard,
    )
    web_operator = WebOperator()

    # Context Bundle
    context = {
        "config": config,
        "memory": memory,
        "approval_guard": approval_guard,
        "brain_router": brain_router,
        "screen_capture": screen_capture,
        "vlm_client": vlm_client,
        "desktop_observer": desktop_observer,
        "input_controller": input_controller,
        "command_executor": command_executor,
        "file_manager": file_manager,
        "web_operator": web_operator,
    }

    # 5. Start Feet (API Server & Dashboard)
    net_info = NetworkHelper.get_connection_info(config.feet.port, config.feet.static_ip)
    server = None
    if not args.no_server and config.feet.enabled:
        server = APIGatewayServer(context=context, host=config.feet.host, port=config.feet.port)
        server.start(block=False)

    # 6. Display Banner
    print_banner(config, net_info)

    # 7. Interactive Terminal Mode
    if args.interactive:
        print("💡 دستورات ویژه: /mode <name> | /eyes | /search <query> | /status | /exit")
        print("─────────────────────────────────────────────────────────────────────────────\n")

        session_id = f"cli_{int(time.time())}"
        while True:
            try:
                user_input = input("You > ").strip()
                if not user_input:
                    continue

                if user_input in {"/exit", "exit", "quit"}:
                    print("\n👋 خداحافظ داداش! سیستم خاموش شد.")
                    break

                if user_input.startswith("/mode"):
                    parts = user_input.split()
                    if len(parts) > 1:
                        res = brain_router.set_mode(parts[1])
                        print(f"🔄 Mode updated: {res}")
                    else:
                        print(f"Current mode: {config.mode}")
                    continue

                if user_input.startswith("/eyes"):
                    print("👁️ در حال گرفتن اسکرین‌شات و تحلیل...")
                    obs = desktop_observer.capture_and_inspect()
                    print(f"Window: {obs['active_window'].get('title')}")
                    print(f"Visual analysis: {obs.get('visual_analysis')}")
                    continue

                if user_input.startswith("/search"):
                    query = user_input[7:].strip()
                    print(f"🌐 در حال جستجو برای: '{query}'...")
                    s_res = web_operator.search(query, max_results=3)
                    for r in s_res.get("results", []):
                        print(f"• {r['title']}\n  {r['url']}\n  {r['snippet']}\n")
                    continue

                if user_input == "/status":
                    print(f"Agent: {config.agent_name} | Mode: {config.mode} | Port: {config.feet.port}")
                    continue

                # Process Chat with Dual-Brain Pipeline
                print("⏳ در حال پردازش...", end="\r", flush=True)
                history = memory.get_conversation_history(session_id, limit=4)
                memory.save_message(session_id, "user", user_input)

                res = brain_router.process(message=user_input, conversation_history=history)

                brain_name = "🔬 DeepSeek R1 ➔ Qwen" if res.get("routed_to") == "deepseek_reasoner" else "⚡ Qwen 2.5"
                print(f"\r[{brain_name}]:\n")

                if res.get("thought_process"):
                    print(f"─── 🔬 فرآیند تفکر عمیق (DeepSeek R1) ───\n{res['thought_process']}\n──────────────────────────────────────────")

                print(res.get("response", ""))
                print(f"\n(زمان: {res.get('elapsed_sec', 0)} ثانیه)\n")

                memory.save_message(session_id, "assistant", res.get("response", ""), metadata=res)

            except (KeyboardInterrupt, EOFError):
                if sys.stdin.isatty():
                    print("\n\n👋 خداحافظ داداش! سیستم با موفقیت متوقف شد.")
                    break
                else:
                    # Non-interactive / daemon mode: keep server alive
                    break
            except Exception as e:
                print(f"\n❌ خطا: {e}\n")

    # Keep server running if in background daemon mode
    if server and (not args.interactive or not sys.stdin.isatty()):
        try:
            while True:
                time.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            pass

    if server:
        server.stop()


if __name__ == "__main__":
    main()
