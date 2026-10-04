"""
Unit and Integration Tests for Qwen-Hands-Eyes Autonomous Agent Engine.
Tests all modular subsystems: Brain Router, Memory (DSA), Approval Guard, Eyes, Hands, and Feet.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from config.settings import AppConfig
from core.approval_guard import ApprovalGuard
from core.brain_router import DualBrainRouter
from core.memory_engine import MemoryEngine
from core.translator_bridge import DualBrainTranslatorBridge
from eyes.screen_capture import ScreenCaptureEngine
from eyes.visual_locator import VisualLocator
from feet.static_ip_helper import NetworkHelper
from hands.command_executor import SafeCommandExecutor
from hands.file_manager import SafeFileManager
from hands.input_controller import InputController


class TestQwenHandsEyes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config = AppConfig()
        self.config.workspace_root = self.temp_dir
        self.config.memory.sqlite_path = os.path.join(self.temp_dir, "test_memory.sqlite")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_config_load_and_defaults(self):
        cfg = AppConfig.load()
        self.assertEqual(cfg.mode, "dual_brain")
        self.assertTrue(cfg.eyes.enabled)
        self.assertTrue(cfg.hands.enabled)
        self.assertTrue(cfg.feet.enabled)
        self.assertEqual(cfg.memory.dsa_lambda, 0.15)
        self.assertEqual(cfg.memory.dsa_gamma, 0.4)
        self.assertEqual(cfg.memory.dsa_min, 0.15)

    def test_memory_engine_and_dsa_fade_not_forget(self):
        mem = MemoryEngine(
            db_path=self.config.memory.sqlite_path,
            dsa_enabled=True,
            dsa_lambda=0.15,
            dsa_gamma=0.4,
            dsa_min=0.15,
        )

        # Save conversation
        msg_id = mem.save_message("test_sess", "user", "سلام داداش")
        self.assertGreater(msg_id, 0)
        history = mem.get_conversation_history("test_sess")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["content"], "سلام داداش")

        # Save experience
        exp_id = mem.add_experience("trading", "تحلیل روند", "استراتژی فیوچرز بای‌بیت بر اساس مومنتوم", tags="crypto bybit")
        self.assertGreater(exp_id, 0)

        # Search experience
        results = mem.search_experiences("فیوچرز بای‌بیت")
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["category"], "trading")

        # DSA retention weight floor check
        weight = mem.calculate_dsa_weight("2020-01-01 10:00:00", access_count=1)
        self.assertGreaterEqual(weight, 0.15)

    def test_approval_guard(self):
        guard = ApprovalGuard(safe_mode=True, require_approval=True)
        # Blocked dangerous command
        res_blocked = guard.evaluate_command_risk("rm -rf /")
        self.assertFalse(res_blocked["allowed"])
        self.assertEqual(res_blocked["risk_level"], "critical")

        # Safe command
        res_safe = guard.evaluate_command_risk("echo hello")
        self.assertTrue(res_safe["allowed"])
        self.assertEqual(res_safe["risk_level"], "low")

        # Diff rendering
        diff = guard.render_diff("line1\n", "line1\nline2\n", "test.py")
        self.assertIn("+line2", diff)

    def test_visual_locator(self):
        locator = VisualLocator(screen_width=1920, screen_height=1080)
        # Test Qwen-VL normalized bounding box [ymin, xmin, ymax, xmax] in 0..1000 scale
        coords = locator.parse_coordinates_from_vlm_output("The button is located at [200, 300, 400, 500]")
        self.assertIsNotNone(coords)
        x, y = coords
        # center x = 400/1000 * 1920 = 768, center y = 300/1000 * 1080 = 324
        self.assertEqual(x, 768)
        self.assertEqual(y, 324)

    def test_screen_capture_engine(self):
        cap = ScreenCaptureEngine(output_dir=os.path.join(self.temp_dir, "snaps"))
        snap = cap.capture_screen(save_file=True)
        self.assertTrue(snap["ok"])
        self.assertGreater(snap["width"], 0)
        self.assertGreater(len(snap["base64_png"]), 10)

    def test_safe_file_manager(self):
        mgr = SafeFileManager(workspace_root=self.temp_dir, create_backups=True)
        # Write
        w_res = mgr.write_file("test.txt", "سلام دنیا", require_approval=False)
        self.assertTrue(w_res["ok"])

        # Read
        r_res = mgr.read_file("test.txt")
        self.assertTrue(r_res["ok"])
        self.assertEqual(r_res["content"], "سلام دنیا")

        # Edit
        e_res = mgr.edit_file("test.txt", "دنیا", "ایران")
        self.assertTrue(e_res["ok"])
        r_res2 = mgr.read_file("test.txt")
        self.assertEqual(r_res2["content"], "سلام ایران")

    def test_safe_command_executor(self):
        guard = ApprovalGuard(safe_mode=True, require_approval=False)
        executor = SafeCommandExecutor(workspace_root=self.temp_dir, approval_guard=guard)
        res = executor.execute("python3 -c \"print('SkyGround Test OK')\"")
        self.assertTrue(res["ok"])
        self.assertIn("SkyGround Test OK", res["stdout"])

    def test_brain_router_rules(self):
        router = DualBrainRouter(self.config)
        # Persian code task should route to reasoning brain
        should_route, reason = router.should_route_to_reasoning_brain("یک تابع پایتون برای تحلیل اندیکاتور RSI بنویس")
        self.assertTrue(should_route)
        self.assertIn("Keyword match", reason)

        # Simple greeting should route to Qwen
        should_route_simple, _ = router.should_route_to_reasoning_brain("سلام صبح بخیر")
        self.assertFalse(should_route_simple)

    def test_thought_extraction(self):
        bridge = DualBrainTranslatorBridge(primary_client=None)
        raw_text = "<think>\nStep 1: Calculate sum\nStep 2: Return result\n</think>\nThe answer is 42."
        thought, answer = bridge.extract_reasoning_and_answer(raw_text)
        self.assertIn("Step 1: Calculate sum", thought)
        self.assertEqual(answer, "The answer is 42.")

    def test_network_helper(self):
        info = NetworkHelper.get_connection_info(port=8765)
        self.assertIn("http://", info["local_api_url"])
        self.assertEqual(info["port"], 8765)


if __name__ == "__main__":
    unittest.main()
