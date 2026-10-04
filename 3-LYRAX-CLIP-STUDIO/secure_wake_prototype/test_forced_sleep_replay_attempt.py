# -*- coding: utf-8 -*-
"""
🔁 تست حمله‌ی دیگر: Replay یک پاسخ قدیمیِ *واقعاً معتبر و امضاشده* از مرکز
(نه یک پاسخ دستکاری‌شده) که قبل از فعال شدن force_sleep صادر شده بود.

سناریو: مهاجم یک پاسخ قدیمی force_sleep=False را که در گذشته واقعاً از طرف
مرکز آمده و امضای درستی هم دارد، ذخیره کرده. حالا که مرکز flag زده و باید
گوشی بخوابد، مهاجم همان پاسخ قدیمی (با امضای معتبر ولی برای یک block_hash/
chain_length متفاوت) را دوباره به گوشی تزریق می‌کند تا فکر کند اجازه دارد کار کند.

این تست مشخص می‌کند که آیا سیستم فعلی در برابر این نوع حمله هم مقاوم است یا
فقط جلوی پاسخ‌های بی‌امضا/دستکاری‌شده را می‌گیرد.
"""
import sys
sys.path.insert(0, '/home/user/secure_wake_prototype')

from device_agent import DeviceAgent
from control_center import ControlCenter

center = ControlCenter()
phone = DeviceAgent(device_id="phone-replay-001", center_public_key_hex=center.center_public_key_bytes)
center.register_device(phone.device_id, phone.public_key_bytes)

print("=== مرحله ۱: یک پاسخ عادی و واقعی (force_sleep=False) از مرکز می‌گیریم و ذخیره می‌کنیم ===")
phone.wake_up()
block1 = phone.build_signed_request({"mission": "ماموریت عادی اول"})
old_valid_response = center.receive_block(block1)
print("پاسخ قدیمی (واقعی، امضای معتبر):", old_valid_response["directive"], "| chain_length:", old_valid_response["chain_length"])
phone.handle_center_response(old_valid_response)
print("is_awake بعد از پاسخ قدیمی:", phone.is_awake)
phone.sleep()

print("\n=== مرحله ۲: مرکز flag می‌زند (گوشی مشکوک تشخیص داده شده) ===")
center.flag_device_for_forced_sleep(phone.device_id, reason="فعالیت مشکوک شناسایی شد")

print("\n=== مرحله ۳: کاربر واقعی دوباره بیدار می‌کند و درخواست جدید می‌فرستد ===")
phone.wake_up()
block2 = phone.build_signed_request({"mission": "ماموریت دوم - باید بلاک شود"})
real_new_response = center.receive_block(block2)
print("پاسخ واقعی جدید مرکز:", real_new_response["directive"])

print("\n=== مرحله ۴: به‌جای پردازش پاسخ جدید، مهاجم پاسخ *قدیمیِ معتبر* (مرحله ۱) را تزریق می‌کند ===")
print("(این پاسخ واقعاً امضای معتبر مرکز را دارد، فقط برای یک لحظه‌ی متفاوت در گذشته صادر شده بود)")
phone.handle_center_response(old_valid_response)  # replay پاسخ قدیمی معتبر
print("is_awake بعد از replay پاسخ قدیمی:", phone.is_awake)
print("last_forced_sleep_reason:", phone.last_forced_sleep_reason)

# معیار درست: چون is_awake از قبل (مرحله‌ی ۳، wake_up دستی کاربر) True بود،
# صرفاً چک کردن is_awake کافی نیست. باید ببینیم آیا گوشی واقعاً پاسخ replay‌شده
# را «پردازش» کرد (یعنی به آن اعتماد کرد) یا آن را به‌خاطر عدم تطابق nonce/hash
# با آخرین درخواست خودش، نادیده گرفت.
replay_blocked = (phone.last_forced_sleep_reason == "IGNORED_STALE_OR_REPLAYED_RESPONSE")

if not replay_blocked:
    print("\n🚨 آسیب‌پذیری Replay تایید شد: یک پاسخ قدیمیِ کاملاً معتبر و امضاشده")
    print("   به‌عنوان پاسخ معتبر پردازش شد، درحالی‌که واقعاً پاسخ درخواست جدید نبود.")
    assert False, "رگرسیون امنیتی: پاسخ replay‌شده نباید پردازش شود"
else:
    print("\n✅ رفع آسیب‌پذیری تایید شد: چون nonce/hash پاسخ قدیمی با آخرین درخواستی")
    print("   که گوشی همین الان فرستاده بود مطابقت نداشت، گوشی این پاسخ را «کهنه/replay»")
    print("   تشخیص داد و کاملاً نادیده گرفت. فقط پاسخِ واقعیِ همان درخواست اخیر پذیرفته می‌شود.")

print("\n" + "=" * 70)
print("🔬 تست کنترلی: پردازش پاسخ *واقعی و تازه* (مرحله ۳) باید هنوز درست کار کند")
print("=" * 70)
phone.handle_center_response(real_new_response)
print("is_awake بعد از پردازش پاسخ واقعی و تازه:", phone.is_awake)
assert phone.is_awake is False
print("✅ رفتار صحیح دست‌نخورده باقی مانده: پاسخ تازه و امضاشده هنوز به‌درستی گوشی را می‌خواباند.")
