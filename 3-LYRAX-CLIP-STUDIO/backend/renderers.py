import os
import re
import json
import time
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

import imageio_ffmpeg

# فونت‌های مورد استفاده برای اندازه‌گیری متن (باید دقیقاً با فونت‌های استفاده‌شده در ASS یکی باشند)
FONT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "fonts"))
PERSIAN_FONT_PATH = os.path.join(FONT_DIR, "Vazirmatn.ttf")
ENGLISH_FONT_PATH_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _resolve_english_font_path():
    for p in ENGLISH_FONT_PATH_CANDIDATES:
        if os.path.exists(p):
            return p
    return PERSIAN_FONT_PATH


ENGLISH_FONT_PATH = _resolve_english_font_path()


class RenderEngine:
    def __init__(self, project, project_dir, output_path, progress_callback=None):
        self.project = project
        self.project_dir = project_dir
        self.output_path = output_path
        self.progress_callback = progress_callback or (lambda pct, msg: None)

    def render(self):
        raise NotImplementedError("Render method must be implemented by subclasses")


_PERSIAN_CHAR_RE = re.compile(r'[\u0600-\u06FF\u200C\u200F]')


def _contains_persian_chars(text):
    """تشخیص اینکه یک رشته حاوی حروف فارسی/عربی است یا نه."""
    return bool(_PERSIAN_CHAR_RE.search(text or ""))


# ===== سه سطح از قدرت/پیچیدگی رعدوبرق (تیر ۱/۲/۳) - باید دقیقاً با LIGHTNING_TIERS در
# studio.html سمت مرورگر یکسان باشد تا پیش‌نمایش زنده و خروجی نهایی FFmpeg یک شکل باشند. =====
LIGHTNING_TIERS = {
    1: {"thickness": 4, "segments": 6, "wig": 12, "duration": 0.35, "branch": False},
    2: {"thickness": 7, "segments": 8, "wig": 16, "duration": 0.42, "branch": False},
    3: {"thickness": 11, "segments": 11, "wig": 22, "duration": 0.55, "branch": True},
}

# استایل‌های مختلف رعد و برق + رنگ‌های واکنشی به فرکانس صوت
LIGHTNING_STYLES = {
    "bass": {
        "style": "realistic",      # الگوریتم midpoint displacement
        "color": "#FF4500",        # قرمز-نارنجی (آتشین و قدرتمند)
        "glow_color": "#FF6347",
        "thickness_mult": 1.4,     # ضخیم‌تر
        "duration_mult": 1.3,      # ماندگاری بیشتر
        "branch_prob": 0.35,
    },
    "mid": {
        "style": "zigzag",         # زیگزاگ کلاسیک و ریتمیک
        "color": "#FFF700",        # زرد طلایی (پیش‌فرض)
        "glow_color": "#FFFF66",
        "thickness_mult": 1.0,
        "duration_mult": 1.0,
        "branch_prob": 0.2,
    },
    "treble": {
        "style": "forked",         # شاخه‌های نازک و سریع
        "color": "#00BFFF",        # آبی یخی (فرکانس بالا)
        "glow_color": "#87CEEB",
        "thickness_mult": 0.6,     # نازک و تیز
        "duration_mult": 0.7,      # فلاش بسیار سریع
        "branch_prob": 0.6,
    },
}


def detect_beat_times(audio_file_path, sensitivity=1.35, min_gap_sec=0.22, sample_rate=22050):
    """تشخیص لحظات ضرب/بیت آهنگ با تحلیل سه باند فرکانسی (باس/میدرنج/تربل).
    خروجی: لیستی از {"t": زمان, "tier": ۱/۲/۳, "energy_factor": ضریب, "freq_band": "bass/mid/treble"}
    هر فرکانس رعد و برقی با فیزیک و رنگ متفاوتی پدید می‌آورد."""
    try:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ffmpeg_exe, "-y", "-i", audio_file_path,
            "-f", "s16le", "-acodec", "pcm_s16le",
            "-ac", "1", "-ar", str(sample_rate),
            "-"
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        raw = result.stdout
        if not raw:
            return []

        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
        if len(samples) == 0:
            return []

        # پنجره‌بندی به قطعات کوچک (شبیه فریم‌های آنالیز صوتی مرورگر با fftSize=512)
        window_size = 512
        hop_size = 512
        num_windows = max(1, (len(samples) - window_size) // hop_size)

        beat_events = []
        energy_history = {"bass": [], "mid": [], "treble": []}
        last_beat_time = -999.0
        history_max_len = 40

        # مرزهای فرکانسی (برای sample_rate=22050، Nyquist=11025Hz)
        # باس: ۲۰-۲۵۰ هرتز | میدرنج: ۲۵۰-۴۰۰۰ هرتز | تربل: ۴۰۰۰-۱۱۰۲۵ هرتز
        num_bins = window_size // 2 + 1
        bass_end = int(250 / (sample_rate / 2) * num_bins)
        mid_end = int(4000 / (sample_rate / 2) * num_bins)

        for w in range(num_windows):
            start = w * hop_size
            chunk = samples[start:start + window_size]
            if len(chunk) < window_size:
                break

            fft_mag = np.abs(np.fft.rfft(chunk))

            # محاسبه‌ی انرژی هر باند فرکانسی
            bass_energy = float(np.mean(fft_mag[1:bass_end])) if bass_end > 1 else 0.0
            mid_energy = float(np.mean(fft_mag[bass_end:mid_end])) if mid_end > bass_end else 0.0
            treble_energy = float(np.mean(fft_mag[mid_end:])) if len(fft_mag) > mid_end else 0.0

            bands = {"bass": bass_energy, "mid": mid_energy, "treble": treble_energy}

            for band_name, current_energy in bands.items():
                energy_history[band_name].append(current_energy)
                if len(energy_history[band_name]) > history_max_len:
                    energy_history[band_name].pop(0)

                avg = sum(energy_history[band_name]) / len(energy_history[band_name])
                current_time = (start + window_size / 2) / sample_rate

                if current_energy > avg * sensitivity and current_energy > (avg * 0.05 + 5) \
                        and (current_time - last_beat_time) > min_gap_sec:
                    last_beat_time = current_time
                    energy_ratio = (current_energy / avg) if avg > 1 else 1.0

                    tier = 1
                    if energy_ratio >= sensitivity * 1.55:
                        tier = 3
                    elif energy_ratio >= sensitivity * 1.15:
                        tier = 2

                    energy_factor = max(0.7, min(1.8, energy_ratio))
                    beat_events.append({
                        "t": round(current_time, 3),
                        "tier": tier,
                        "energy_factor": energy_factor,
                        "freq_band": band_name
                    })

        return beat_events
    except Exception as e:
        print(f"Beat detection error (non-fatal, lightning effect will be skipped): {e}")
        return []


def _split_bilingual_line(raw_text):
    """جدا کردن متن دوزبانه‌ی یک خط لیریکس (جدا شده با /) به دو بخش «فارسی» و «انگلیسی»،
    مستقل از ترتیب نوشتن کاربر در کادر لیریکس (تشخیص با بررسی وجود حروف فارسی/عربی).
    این دقیقاً همان منطق تابع splitBilingualLine در studio.html (سمت مرورگر) است."""
    parts = raw_text.split('/')
    if len(parts) == 1:
        only = parts[0].strip()
        if _contains_persian_chars(only):
            return only, ""
        return "", only
    first = parts[0].strip()
    rest = "/".join(parts[1:]).strip()
    if _contains_persian_chars(first):
        return first, rest
    elif _contains_persian_chars(rest):
        return rest, first
    return first, rest


def _wrap_words_to_lines(font, words, max_width):
    """شکستن یک لیست کلمه به خطوطی که هرکدام حداکثر max_width پیکسل عرض دارند."""
    lines = []
    cur = []
    for w in words:
        test_line = ' '.join(cur + [w])
        if cur and font.getlength(test_line) > max_width:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def _fit_words_to_lines(font_path, words, max_width, max_lines, base_size, min_size):
    """پیدا کردن بزرگ‌ترین اندازه فونت که متن را حداکثر در max_lines خط جا می‌کند."""
    if not words:
        return [], base_size
    size = base_size
    lines = []
    while size >= min_size:
        font = ImageFont.truetype(font_path, size)
        lines = _wrap_words_to_lines(font, words, max_width)
        if len(lines) <= max_lines:
            break
        size -= 2
    if len(lines) > max_lines:
        merged = []
        for l in lines[max_lines - 1:]:
            merged.extend(l)
        lines = lines[:max_lines - 1] + [merged]
    return lines, size


class FFmpegRenderer(RenderEngine):
    def _hex_to_ass_color(self, hex_color, alpha=0):
        """hex_color مثل #FFF000 را به فرمت رنگ ASS تبدیل می‌کند: &HAABBGGRR&
        alpha بین 0 (کاملاً کدر) تا 255 (کاملاً شفاف) است."""
        clean = str(hex_color).replace('#', '')
        if len(clean) == 6:
            r, g, b = clean[0:2], clean[2:4], clean[4:6]
        else:
            r, g, b = "FF", "FF", "FF"
        a = f"{max(0, min(255, int(alpha))):02X}"
        return f"&H{a}{b}{g}{r}&"

    def _format_ass_time(self, sec):
        sec = max(0.0, float(sec))
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        cs = int(round((sec - int(sec)) * 100))
        return f"{h:01d}:{m:02d}:{s:02d}.{cs:02d}"

    def _build_karaoke_text(self, words, total_cs, min_cs_per_word=8):
        """ساخت متن کارائوکه ASS با تگ‌های \\k روی هر کلمه.
        total_cs: کل زمان موجود (به صدم ثانیه) برای پخش تمام کلمات این بخش (فارسی یا انگلیسی)."""
        if not words:
            return ""
        n = len(words)
        per_word = max(min_cs_per_word, int(total_cs / n)) if total_cs > 0 else min_cs_per_word
        parts = []
        for w in words:
            parts.append(f"{{\\k{per_word}}}{w}")
        return " ".join(parts)

    def _build_drawing_rect(self, x1, y1, x2, y2):
        """ساخت رشته ترسیم مستطیل با دستورات drawing کد ASS (\\p1)."""
        return f"m {x1} {y1} l {x2} {y1} l {x2} {y2} l {x1} {y2}"

    def _deterministic_random(self, seed, index, min_val=-1.0, max_val=1.0):
        """تولید عدد شبه‌تصادفی کاملاً قطعی و تکرارپذیر بدون تغییر وضعیت random سراسری."""
        x = ((seed * 1103515245 + 12345 + index * 2654435761) & 0x7FFFFFFF)
        normalized = (x % 10000) / 10000.0
        return min_val + normalized * (max_val - min_val)

    def _midpoint_displacement(self, p1, p2, displacement, roughness, seed, depth, clamp_min, clamp_max):
        """الگوریتم فرکتالی Midpoint Displacement برای شبیه‌سازی رعدوبرق واقعی هالیوودی."""
        if depth == 0:
            return [p1]

        mid_x = (p1[0] + p2[0]) / 2.0
        mid_y = (p1[1] + p2[1]) / 2.0

        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        length = max(0.001, (dx**2 + dy**2) ** 0.5)
        nx, ny = -dy / length, dx / length

        offset = self._deterministic_random(seed, depth, -displacement, displacement)
        mid_x += nx * offset
        mid_y += ny * offset

        mid_x = max(clamp_min, min(clamp_max, mid_x))

        left = self._midpoint_displacement(p1, (mid_x, mid_y), displacement * roughness, roughness, seed + 1, depth - 1, clamp_min, clamp_max)
        right = self._midpoint_displacement((mid_x, mid_y), p2, displacement * roughness, roughness, seed + 2, depth - 1, clamp_min, clamp_max)

        # جلوگیری از تکرار نقطه میانی در اتصال دو نیمه
        return (left[:-1] if left else []) + right

    def _build_lightning_bolt_path(self, start_x, start_y, side, seed, res_h, res_w=1080, thickness=7,
                                    segments=6, wig_scale=12, branch=False, style="zigzag"):
        """ساخت رشته‌ی مسیر رسم (ASS \\p1) با پشتیبانی از سه استایل:
        - zigzag: زیگزاگ هندسی کلاسیک
        - realistic: الگوریتم فرکتالی Midpoint Displacement (رعدوبرق طبیعی)
        - forked: شاخه‌بندی چندگانه و متراکم"""
        dir_sign = 1 if side == "left" else -1
        total_len = res_h * 0.28
        clamp_min = round(res_w * 0.08)
        clamp_max = round(res_w * 0.92)

        end_x = start_x + dir_sign * total_len * 0.35
        end_y = start_y + total_len
        end_x = max(clamp_min, min(clamp_max, end_x))

        if style == "realistic":
            points = self._midpoint_displacement(
                (start_x, start_y), (end_x, end_y),
                displacement=wig_scale * 1.5,
                roughness=0.55,
                seed=seed * 1000 + 7,
                depth=segments // 2 + 2,
                clamp_min=clamp_min,
                clamp_max=clamp_max
            )
            points.append((end_x, end_y))
        elif style == "forked":
            mid_y = start_y + total_len * 0.5
            mid_x = start_x + dir_sign * total_len * 0.17
            mid_x = max(clamp_min, min(clamp_max, mid_x))
            points = [(start_x, start_y), (mid_x, mid_y), (end_x, end_y)]

            num_branches = 2 + (seed % 3)
            if not hasattr(self, '_fork_branches'):
                self._fork_branches = []
            for i in range(num_branches):
                branch_seed = seed * 100 + i
                branch_start_y = start_y + total_len * (0.3 + i * 0.2)
                branch_start_x = start_x + dir_sign * total_len * (0.1 + i * 0.05)
                branch_start_x = max(clamp_min, min(clamp_max, branch_start_x))

                branch_end_x = branch_start_x + self._deterministic_random(branch_seed, 1, -total_len * 0.3, total_len * 0.3)
                branch_end_y = branch_start_y + total_len * 0.3
                branch_end_x = max(clamp_min, min(clamp_max, branch_end_x))
                self._fork_branches.append((branch_start_x, branch_start_y, branch_end_x, branch_end_y, branch_seed))
        else:
            step_len = total_len / segments
            points = [(start_x, start_y)]
            x, y = start_x, start_y
            for i in range(segments):
                wig = (((seed + 2) * (i + 3)) % 7 - 3) * wig_scale
                x += dir_sign * (step_len * 0.35) + wig
                x = max(clamp_min, min(clamp_max, x))
                y += step_len
                points.append((x, y))

        def build_ribbon(pts, t):
            if len(pts) < 2:
                return ""
            half_t = t / 2.0
            left_side = []
            right_side = []
            for i in range(len(pts)):
                px, py = pts[i]
                if i == 0:
                    dx, dy = pts[1][0] - px, pts[1][1] - py
                elif i == len(pts) - 1:
                    dx, dy = px - pts[i - 1][0], py - pts[i - 1][1]
                else:
                    dx = pts[i + 1][0] - pts[i - 1][0]
                    dy = pts[i + 1][1] - pts[i - 1][1]
                length = max(0.001, (dx ** 2 + dy ** 2) ** 0.5)
                nx, ny = -dy / length, dx / length
                left_side.append((px + nx * half_t, py + ny * half_t))
                right_side.append((px - nx * half_t, py - ny * half_t))
            polygon_points = left_side + list(reversed(right_side))
            parts = [f"m {round(polygon_points[0][0])} {round(polygon_points[0][1])}"]
            for px, py in polygon_points[1:]:
                parts.append(f"l {round(px)} {round(py)}")
            return " ".join(parts)

        path_str = build_ribbon(points, thickness)

        if style == "forked" and hasattr(self, '_fork_branches'):
            for bx1, by1, bx2, by2, bseed in self._fork_branches:
                branch_pts = self._midpoint_displacement(
                    (bx1, by1), (bx2, by2),
                    displacement=wig_scale * 0.8,
                    roughness=0.5,
                    seed=bseed * 1000 + 3,
                    depth=3,
                    clamp_min=clamp_min,
                    clamp_max=clamp_max
                )
                branch_pts.append((bx2, by2))
                path_str += " " + build_ribbon(branch_pts, max(2.0, thickness * 0.5))
            del self._fork_branches

        if style == "realistic" and branch:
            mid_idx = len(points) // 2
            if 0 < mid_idx < len(points):
                bx, by = points[mid_idx]
                branch_end_x = bx + self._deterministic_random(seed, 99, -total_len * 0.25, total_len * 0.25)
                branch_end_y = by + total_len * 0.35
                branch_end_x = max(clamp_min, min(clamp_max, branch_end_x))

                branch_pts = self._midpoint_displacement(
                    (bx, by), (branch_end_x, branch_end_y),
                    displacement=wig_scale * 0.7,
                    roughness=0.5,
                    seed=seed * 1000 + 13,
                    depth=3,
                    clamp_min=clamp_min,
                    clamp_max=clamp_max
                )
                branch_pts.append((branch_end_x, branch_end_y))
                path_str += " " + build_ribbon(branch_pts, max(2.0, thickness * 0.45))

        return path_str

    def _add_lightning_dialogues(self, lines_out, lightning, beat_events, res_w, res_h):
        """افزودن Dialogue های رعدوبرق با استایل‌های واکنشی به فرکانس و Glow چهارلایه."""
        if not isinstance(lightning, dict) or not lightning.get("enabled") or not beat_events:
            return

        intensity_pct = float(lightning.get("intensity", 80) or 80)
        margin = round(res_w * 0.08)
        start_y = round(res_h * 0.02)
        max_alpha_byte = max(0, min(255, round((1 - intensity_pct / 100.0) * 255)))

        if hasattr(self, '_fork_branches'):
            del self._fork_branches

        for idx, event in enumerate(beat_events):
            beat_t = float(event["t"])
            tier = int(event.get("tier", 1) or 1)
            if tier not in LIGHTNING_TIERS:
                tier = 1
            energy_factor = float(event.get("energy_factor", 1.0) or 1.0)
            energy_factor = max(0.7, min(1.8, energy_factor))
            
            # انتخاب استایل و رنگ بر اساس باند فرکانسی
            freq_band = event.get("freq_band", "mid")
            style_cfg = LIGHTNING_STYLES.get(freq_band, LIGHTNING_STYLES["mid"])
            tier_cfg = LIGHTNING_TIERS[tier]

            side = "left" if idx % 2 == 0 else "right"
            start_x = margin if side == "left" else (res_w - margin)
            seed = int(beat_t * 997) % 1000

            thickness = tier_cfg["thickness"] * style_cfg["thickness_mult"] * (0.75 + 0.25 * energy_factor)
            flash_duration = tier_cfg["duration"] * style_cfg["duration_mult"]

            color_hex = style_cfg["color"]
            glow_color_hex = style_cfg["glow_color"]

            start_str = self._format_ass_time(beat_t)
            end_str = self._format_ass_time(beat_t + flash_duration)

            bolt_path = self._build_lightning_bolt_path(
                start_x, start_y, side, seed, res_h, res_w=res_w,
                thickness=thickness, segments=tier_cfg["segments"],
                wig_scale=tier_cfg["wig"], branch=tier_cfg["branch"],
                style=style_cfg["style"]
            )

            fill_color = self._hex_to_ass_color(color_hex, alpha=max_alpha_byte)
            fade_ms = int(flash_duration * 1000)

            # ===== اثر درخشش ۴ لایه واقعی (Glow Effect) با تگ‌های معتبر ASS =====
            # لایه ۱: هاله‌ی بزرگ محو بیرونی
            glow_outer = self._hex_to_ass_color(glow_color_hex, alpha=max(0, max_alpha_byte - 180))
            override_outer = f"{{\\an7\\pos(0,0)\\1c{glow_outer}\\3c{glow_outer}\\bord{int(thickness * 2.5)}\\shad0\\fad(0,{fade_ms})\\blur12}}"
            lines_out.append(f"Dialogue: 3,{start_str},{end_str},Watermark,,0,0,0,,{override_outer}{{\\p1}}{bolt_path}{{\\p0}}")

            # لایه ۲: هاله‌ی میانی درخشان
            glow_mid = self._hex_to_ass_color(glow_color_hex, alpha=max(0, max_alpha_byte - 100))
            override_mid = f"{{\\an7\\pos(0,0)\\1c{glow_mid}\\3c{glow_mid}\\bord{int(thickness * 1.5)}\\shad0\\fad(0,{fade_ms})\\blur5}}"
            lines_out.append(f"Dialogue: 3,{start_str},{end_str},Watermark,,0,0,0,,{override_mid}{{\\p1}}{bolt_path}{{\\p0}}")

            # لایه ۳: هسته‌ی اصلی رنگی
            glow_core = self._hex_to_ass_color(glow_color_hex, alpha=min(255, max_alpha_byte + 60))
            override_core = f"{{\\an7\\pos(0,0)\\1c{fill_color}\\3c{glow_core}\\bord2\\shad0\\fad(0,{fade_ms})}}"
            lines_out.append(f"Dialogue: 3,{start_str},{end_str},Watermark,,0,0,0,,{override_core}{{\\p1}}{bolt_path}{{\\p0}}")

            # لایه ۴: مغز سفید متمرکز برای ضربات شدید (Tier >= 2)
            if tier >= 2:
                core_white = self._hex_to_ass_color("#FFFFFF", alpha=min(255, max_alpha_byte + 30))
                override_white = f"{{\\an7\\pos(0,0)\\1c{core_white}\\bord0\\shad0\\fad(0,{fade_ms})}}"
                thin_path = self._build_lightning_bolt_path(
                    start_x, start_y, side, seed, res_h, res_w=res_w,
                    thickness=thickness * 0.35, segments=tier_cfg["segments"],
                    wig_scale=tier_cfg["wig"], branch=False,
                    style=style_cfg["style"]
                )
                lines_out.append(f"Dialogue: 3,{start_str},{end_str},Watermark,,0,0,0,,{override_white}{{\\p1}}{thin_path}{{\\p0}}")

    def _estimate_ass_text_width_px(self, text, font_size):
        """تخمین عرض متن به پیکسل با همان فونت فارسی/انگلیسی مورد استفاده در ASS، برای محاسبه‌ی
        دقیق فاصله‌ی سر خوردن ورود/خروج واترمارک (دقیقاً مطابق measureText سمت مرورگر)."""
        try:
            font_path = PERSIAN_FONT_PATH if _contains_persian_chars(text) else ENGLISH_FONT_PATH
            font = ImageFont.truetype(font_path, font_size)
            bbox = font.getbbox(text)
            return max(10, bbox[2] - bbox[0])
        except Exception:
            return max(10, len(text) * font_size * 0.55)

    def _add_watermark_dialogue(self, lines_out, watermark, total_duration, res_w, res_h):
        """افزودن Dialogue های واترمارک/امضای شخصی سه‌بعدی و چرخشی، دقیقاً مطابق منطق سه‌فازی
        drawWatermark در studio.html سمت مرورگر:
          فاز ۱ (ورود): از لبه‌ی بوم با چرخش سه‌بعدی (فشرده‌شدن افقی \\fscx) سر می‌خورد و می‌رسد
          فاز ۲ (ثابت): بدون تغییر، با تپش نوری ملایم اختیاری
          فاز ۳ (خروج): نزدیک پایان کلیپ، چند دور می‌چرخد (\\frz)، کوچک می‌شود، و هم‌زمان با
                         پایان دقیق کلیپ به صفر می‌رسد و از طرف مخالف ورودش خارج می‌شود
        هر فاز به‌صورت یک Dialogue جداگانه با تگ \\t (انیمیشن زمان‌بندی‌شده‌ی ASS) ساخته می‌شود."""
        if not isinstance(watermark, dict) or not watermark.get("enabled") or not str(watermark.get("text", "")).strip():
            return
        text = str(watermark["text"]).strip()
        font_size = int(watermark.get("size", 30) or 30)
        color_hex = watermark.get("color", "#FFFFFF")
        opacity_pct = float(watermark.get("opacity", 70) or 70)
        position = watermark.get("position", "top-right")
        animated = bool(watermark.get("animated", True))

        margin = max(30, round(res_w * 0.03))
        # تبدیل موقعیت به alignment عددی ASS (numpad-style) + مختصات pos
        # an1=پایین‌چپ an2=پایین‌وسط an3=پایین‌راست an7=بالا‌چپ an8=بالا‌وسط an9=بالا‌راست
        if position == "top-left":
            an, px, py = 7, margin, margin
        elif position == "bottom-right":
            an, px, py = 3, res_w - margin, res_h - margin
        elif position == "bottom-left":
            an, px, py = 1, margin, res_h - margin
        elif position == "center-top":
            an, px, py = 8, res_w // 2, margin
        else:  # top-right (پیش‌فرض)
            an, px, py = 9, res_w - margin, margin

        alpha_val = max(0, min(255, round((1 - opacity_pct / 100.0) * 255)))
        primary_color = self._hex_to_ass_color(color_hex, alpha=alpha_val)
        outline_color = self._hex_to_ass_color("#000000", alpha=max(0, alpha_val - 40))
        alpha_tag_full = f"&H{alpha_val:02X}&"
        alpha_tag_hidden = "&HFF&"

        total_duration = max(0.5, total_duration)
        # همان ثابت‌های سمت مرورگر (WM_ENTRY_DURATION / WM_EXIT_DURATION / WM_EXIT_ROTATIONS)
        entry_dur = min(2.0, total_duration * 0.25)
        exit_dur = min(3.5, total_duration * 0.3)
        exit_start = max(entry_dur, total_duration - exit_dur)
        exit_rotations = 2.5

        # از همان سمتی که موقعیتش تعیین می‌کند وارد می‌شود؛ از طرف مخالف خارج می‌شود
        entry_side = -1 if "left" in position else 1
        exit_side = -entry_side

        text_width_px = self._estimate_ass_text_width_px(text, font_size)
        travel_distance = text_width_px + font_size * 2.5

        entry_start_x = px + entry_side * travel_distance
        exit_end_x = px + exit_side * travel_distance
        rotation_deg_total = exit_rotations * 360 * exit_side

        # ===== فاز ۱: ورود چرخشی (سر خوردن از لبه + فشرده‌شدن افقی که چرخش سه‌بعدی را شبیه‌سازی می‌کند) =====
        if entry_dur > 0.05:
            entry_end_ms = int(entry_dur * 1000)
            override = (
                f"{{\\an{an}\\pos({px},{py})\\fs{font_size}\\1c{primary_color}\\3c{outline_color}\\bord2"
                f"\\fscx15\\alpha{alpha_tag_hidden}"
                f"\\move({entry_start_x},{py},{px},{py},0,{entry_end_ms})"
                f"\\t(0,{entry_end_ms},\\fscx100\\alpha{alpha_tag_full})}}"
            )
            start_str = self._format_ass_time(0.0)
            end_str = self._format_ass_time(entry_dur)
            lines_out.append(f"Dialogue: 2,{start_str},{end_str},Watermark,,0,0,0,,{override}{text}")

        # ===== فاز ۲: کاملاً ثابت (با تپش نوری ملایم اختیاری، دقیقاً مثل نسخه‌ی قبلی) =====
        static_start = entry_dur
        static_end = exit_start
        if static_end > static_start + 0.05:
            fade_tag = "\\fad(300,0)" if animated else ""
            override = f"{{\\an{an}\\pos({px},{py}){fade_tag}\\fs{font_size}\\1c{primary_color}\\3c{outline_color}\\bord2}}"
            start_str = self._format_ass_time(static_start)
            end_str = self._format_ass_time(static_end)
            lines_out.append(f"Dialogue: 2,{start_str},{end_str},Watermark,,0,0,0,,{override}{text}")

        # ===== فاز ۳: خروج چرخشی، کوچک‌شدن، و محوشدگی - دقیقاً هم‌زمان با پایان کلیپ به صفر می‌رسد =====
        if exit_dur > 0.05:
            exit_len_ms = int((total_duration - exit_start) * 1000)
            exit_len_ms = max(50, exit_len_ms)
            override = (
                f"{{\\an{an}\\pos({px},{py})\\fs{font_size}\\1c{primary_color}\\3c{outline_color}\\bord2"
                f"\\fscx100\\fscy100\\frz0\\alpha{alpha_tag_full}"
                f"\\move({px},{py},{exit_end_x},{py},0,{exit_len_ms})"
                f"\\t(0,{exit_len_ms},\\fscx45\\fscy45\\frz{rotation_deg_total:.1f}\\alpha{alpha_tag_hidden})}}"
            )
            start_str = self._format_ass_time(exit_start)
            end_str = self._format_ass_time(total_duration)
            lines_out.append(f"Dialogue: 2,{start_str},{end_str},Watermark,,0,0,0,,{override}{text}")

    def _generate_ass_subtitles(self, events, subtitle_defaults=None, watermark=None, total_duration=0.0, lightning=None, beat_events=None):
        ass_path = os.path.join(self.project_dir, "lyrics.ass")
        style = subtitle_defaults if isinstance(subtitle_defaults, dict) else {}

        RES_W, RES_H = 1080, 1920
        MAX_TEXT_WIDTH = RES_W - 140
        MAX_LINES = 2

        persian_base_size = int(style.get("size", style.get("font_size", 62)))
        english_base_size = 42
        persian_color = style.get("color", "#FFF000")
        stroke_color = style.get("stroke", style.get("stroke_color", "#000000"))
        stroke_width = int(style.get("sWidth", style.get("stroke_width", 5)))
        word_rate = float(style.get("wordRate", 2.5))
        auto_sync = style.get("autoSyncSpeed", True)
        lang_order = style.get("langOrder", "fa_first")

        header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Persian,Vazirmatn,62,&H00FFFFFF&,&H00FFFFFF&,&H00000000&,&H00000000&,-1,0,0,0,100,100,0,0,1,5,0,8,20,20,20,1
Style: English,DejaVu Sans,42,&H00FFFFFF&,&H00FFFFFF&,&H00000000&,&H00000000&,-1,0,0,0,100,100,0,0,1,4,0,8,20,20,20,1
Style: BoxBG,Arial,10,&H00000000&,&H00000000&,&H00000000&,&H00000000&,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: Watermark,Vazirmatn,30,&H00FFFFFF&,&H00FFFFFF&,&H00000000&,&H00000000&,-1,0,0,0,100,100,0,0,1,2,0,9,20,20,20,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        lines_out = [header]

        for e in events:
            if e.type not in ['lyrics', 'text'] or not e.content.strip():
                continue

            raw_text = e.content.strip()
            # تشخیص خودکار بخش فارسی/انگلیسی، مستقل از ترتیب نوشتن در کادر لیریکس
            persian_text, english_text = _split_bilingual_line(raw_text)

            start_t = float(e.start_time)
            end_t = float(e.end_time) if e.end_time else (start_t + 4.0)
            duration = max(0.15, end_t - start_t)
            start_str = self._format_ass_time(start_t)
            end_str = self._format_ass_time(end_t)

            persian_words = [w for w in persian_text.split(' ') if w]
            english_words = [w for w in english_text.split(' ') if w]

            p_lines, p_size = _fit_words_to_lines(PERSIAN_FONT_PATH, persian_words, MAX_TEXT_WIDTH, MAX_LINES, persian_base_size, 30)
            p_line_h = int(round(p_size * 1.35))
            p_block_h = len(p_lines) * p_line_h if p_lines else 0

            e_lines, e_size = _fit_words_to_lines(ENGLISH_FONT_PATH, english_words, MAX_TEXT_WIDTH, MAX_LINES, english_base_size, 22)
            e_line_h = int(round(e_size * 1.35)) if english_words else 0
            e_block_h = len(e_lines) * e_line_h if e_lines else 0

            gap_between = 28 if english_words else 0
            content_h = p_block_h + gap_between + e_block_h
            padding_v = 70
            box_h = max(380, content_h + padding_v * 2)

            margin_bottom = 85
            vertical_align = style.get("verticalAlign", "bottom")
            anim_preset = style.get("animPreset", style.get("animation_style", "cube_3d_horizontal"))

            if vertical_align == "middle":
                box_top = (RES_H - box_h) // 2
                bottom_y = box_top + box_h - padding_v
            elif vertical_align == "top":
                box_top = 95
                bottom_y = box_top + box_h - padding_v
            else:
                box_top = RES_H - box_h
                bottom_y = RES_H - margin_bottom

            en_first = (lang_order == "en_first")
            if not en_first:
                # فارسی بالا / انگلیسی پایین (پیش‌فرض)
                e_start_y = bottom_y - e_block_h + (e_line_h // 2 if e_line_h else 0)
                p_start_y = e_start_y - (gap_between if english_words else 0) - p_block_h + (p_line_h // 2 if p_line_h else 0)
            else:
                # انگلیسی بالا / فارسی پایین
                p_start_y = bottom_y - p_block_h + (p_line_h // 2 if p_line_h else 0)
                e_start_y = p_start_y - (gap_between if english_words else 0) - e_block_h + (e_line_h // 2 if e_line_h else 0)

            box_bottom = box_top + box_h

            # ۱) پس‌زمینه نیمه‌شفاف مستطیلی پشت متن (لایه ۰، زیر متن) - رنگ سیاه با شفافیت ~70%
            rect_draw = self._build_drawing_rect(0, box_top, RES_W, box_bottom)
            box_color_tag = "\\1c&H000000&\\1a&H4D&"
            lines_out.append(
                f"Dialogue: 0,{start_str},{end_str},BoxBG,,0,0,0,,{{\\an7\\pos(0,0){box_color_tag}\\p1}}{rect_draw}{{\\p0}}"
            )

            # ۲) بلوک فارسی (لایه ۱) با کارائوکه \\k -- Primary=سفید(خوانده‌شده) Secondary=رنگ اصلی(نخوانده)
            if persian_words:
                total_cs_persian = int(duration * 100)
                if not auto_sync:
                    # سرعت ثابت: هر کلمه به اندازه‌ی 100/wordRate صدم‌ثانیه
                    per_word_cs = max(8, int(100.0 / max(0.1, word_rate)))
                    total_cs_persian = per_word_cs * len(persian_words)
                karaoke_txt = self._build_karaoke_text(persian_words, total_cs_persian)
                idx = 0
                line_chunks = []
                for lw in p_lines:
                    chunk_words = persian_words[idx: idx + len(lw)]
                    idx += len(lw)
                    chunk_txt = self._build_karaoke_text(chunk_words, total_cs_persian // max(1, len(persian_words)) * len(chunk_words) if len(persian_words) else 0)
                    line_chunks.append(chunk_txt)
                full_persian_karaoke = "\\N".join(line_chunks)

                cube_turn_ms = min(650, int(duration * 1000 * 0.25))
                end_trans_start_ms = max(0, int(duration * 1000) - cube_turn_ms)

                if anim_preset == "cube_3d_horizontal":
                    fade_tag = f"\\fry90\\fscx0\\t(0,{cube_turn_ms},\\fry0\\fscx100)\\t({end_trans_start_ms},{int(duration*1000)},\\fry-90\\fscx0\\alpha&HFF&)"
                elif anim_preset == "cube_3d_vertical":
                    fade_tag = f"\\frx90\\fscy0\\t(0,{cube_turn_ms},\\frx0\\fscy100)\\t({end_trans_start_ms},{int(duration*1000)},\\frx-90\\fscy0\\alpha&HFF&)"
                elif anim_preset == "kinetic_pop":
                    fade_tag = "\\fad(80,80)\\t(0,120,\\fscx115\\fscy115)\\t(120,240,\\fscx100\\fscy100)"
                elif anim_preset == "wave_float":
                    fade_tag = "\\fad(150,150)"
                else:
                    fade_tag = "\\fad(120,120)"

                pos_x = RES_W // 2
                pos_y = p_start_y - (p_line_h // 2 if p_line_h else 0)
                # فارسی: کلمه‌ی خوانده‌شده = سفید درخشان (Primary) | کلمه‌ی نخوانده = رنگ اصلی لیمویی (Secondary)
                override = (
                    f"{{\\an8\\pos({pos_x},{max(0,pos_y)})\\fs{p_size}{fade_tag}"
                    f"\\1c&HFFFFFF&\\2c{self._hex_to_ass_color(persian_color)}"
                    f"\\bord{stroke_width}\\3c{self._hex_to_ass_color(stroke_color)}}}"
                )
                lines_out.append(
                    f"Dialogue: 1,{start_str},{end_str},Persian,,0,0,0,,{override}{full_persian_karaoke}"
                )

            # ۳) بلوک انگلیسی (لایه ۱) با کارائوکه -- Primary=لیمویی بولد(خوانده‌شده) Secondary=فیروزه‌ای کم‌رنگ(نخوانده)
            if english_words:
                total_cs_english = int(duration * 100)
                if not auto_sync:
                    per_word_cs = max(8, int(100.0 / max(0.1, word_rate)))
                    total_cs_english = per_word_cs * len(english_words)

                idx = 0
                line_chunks = []
                for lw in e_lines:
                    chunk_words = english_words[idx: idx + len(lw)]
                    idx += len(lw)
                    chunk_txt = self._build_karaoke_text(chunk_words, total_cs_english // max(1, len(english_words)) * len(chunk_words) if len(english_words) else 0)
                    line_chunks.append(chunk_txt)
                full_english_karaoke = "\\N".join(line_chunks)

                pos_x = RES_W // 2
                pos_y = e_start_y - (e_line_h // 2 if e_line_h else 0)
                # انگلیسی: کلمه‌ی خوانده‌شده = لیمویی بولد با حاشیه مشکی ضخیم (Primary)
                # کلمه‌ی نخوانده = فیروزه‌ای کم‌رنگ نیمه‌شفاف (Secondary) با حاشیه مشکی نازک‌تر
                override = (
                    f"{{\\an8\\pos({pos_x},{max(0,pos_y)})\\fs{e_size}"
                    f"\\1c{self._hex_to_ass_color(persian_color)}\\2c{self._hex_to_ass_color('#00E5FF')}\\2a&H60&"
                    f"\\bord5\\3c&H000000&}}"
                )
                lines_out.append(
                    f"Dialogue: 1,{start_str},{end_str},English,,0,0,0,,{override}{full_english_karaoke}"
                )

        # جلوه‌ی رعدوبرق هماهنگ با ضرب آهنگ (زیر واترمارک، روی همه‌چیز دیگر)
        self._add_lightning_dialogues(lines_out, lightning, beat_events or [], RES_W, RES_H)

        # واترمارک/امضای شخصی ثابت روی کل مدت کلیپ (اثر انگشت) - همیشه به‌عنوان آخرین لایه اضافه می‌شود
        self._add_watermark_dialogue(lines_out, watermark, total_duration, RES_W, RES_H)

        with open(ass_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines_out))
        return ass_path

    def render(self):
        self.progress_callback(5, "آماده‌سازی فایل‌های متنی و لایه‌ها...")
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

        duration = float(getattr(self.project, "duration", 15.0))
        if duration <= 0:
            duration = 15.0

        res_w, res_h = 1080, 1920
        if hasattr(self.project, "resolution") and self.project.resolution:
            res_w, res_h = self.project.resolution[0], self.project.resolution[1]
        fps = int(getattr(self.project, "fps", 30))

        # Separate events
        events = getattr(self.project, "events", [])
        audio_events = [e for e in events if getattr(e, "type", "") == 'audio']
        visual_events = [e for e in events if getattr(e, "type", "") in ['image', 'video']]
        text_events = [e for e in events if getattr(e, "type", "") in ['lyrics', 'text']]

        subtitle_defaults = getattr(self.project, "subtitle_defaults", None)
        watermark = getattr(self.project, "watermark", None)
        watermark_enabled = isinstance(watermark, dict) and watermark.get("enabled") and str(watermark.get("text", "")).strip()

        # تشخیص لحظات رعدوبرق: سه حالت مستقل که می‌توانند با هم ترکیب هم بشوند
        #   ۱) mode="beat" (پیش‌فرض): تشخیص خودکار ضرب/بیت از روی فایل صوتی
        #   ۲) mode="interval": فاصله‌ی زمانی ثابت، مستقل از صدا (برای آهنگ‌های آرام
        #      که هیچ‌وقت انرژی باس کافی برای تشخیص خودکار ضرب ندارند)
        #   ۳) manual_lightning_timestamps: لحظاتی که کاربر با دکمه‌ی دستی «الان بزن»
        #      در ادیتور ثبت کرده - همیشه اضافه می‌شوند، صرف‌نظر از mode
        lightning = getattr(self.project, "lightning", None)
        lightning_enabled = isinstance(lightning, dict) and lightning.get("enabled")
        # beat_events: لیستی از {"t", "tier", "energy_factor"} - سه منبع مستقل که با هم ترکیب می‌شوند
        beat_events = []
        if lightning_enabled:
            lightning_mode = str(lightning.get("mode", "beat") or "beat")

            if lightning_mode == "interval":
                self.progress_callback(8, "در حال محاسبه‌ی لحظات رعدوبرق با فاصله‌ی زمانی ثابت...")
                interval_sec = float(lightning.get("intervalSec", 4.0) or 4.0)
                interval_sec = max(0.5, interval_sec)
                t = 0.0
                while t <= duration:
                    # حالت interval همیشه تیر ۱ (معمولی) است؛ تنوع قدرت فقط با تشخیص خودکار ضرب یا دکمه‌ی دستی می‌آید
                    beat_events.append({"t": round(t, 3), "tier": 1, "energy_factor": 1.0})
                    t += interval_sec
            elif audio_events:
                self.progress_callback(8, "در حال آنالیز صدا برای تشخیص ضرب آهنگ (جلوه رعدوبرق)...")
                first_audio_path = None
                for ae in audio_events:
                    candidate = os.path.join(self.project_dir, getattr(ae, "content", ""))
                    if os.path.exists(candidate):
                        first_audio_path = candidate
                        break
                if first_audio_path:
                    sensitivity = float(lightning.get("sensitivity", 1.35) or 1.35)
                    beat_events = detect_beat_times(first_audio_path, sensitivity=sensitivity)

            # لحظات دستی کاربر همیشه اضافه می‌شوند (حتی در حالت beat/interval)، هرکدام با تیر خودشان
            manual_timestamps = getattr(self.project, "manual_lightning_timestamps", None) or []
            if isinstance(manual_timestamps, list) and manual_timestamps:
                for item in manual_timestamps:
                    try:
                        # سازگاری با فرمت قدیمی (فقط عدد زمان) و فرمت جدید ({"t":..., "tier":...})
                        if isinstance(item, dict):
                            ts = float(item.get("t"))
                            tier = int(item.get("tier", 1) or 1)
                        else:
                            ts = float(item)
                            tier = 1
                        if tier not in (1, 2, 3):
                            tier = 1
                        beat_events.append({"t": round(ts, 3), "tier": tier, "energy_factor": 1.0})
                    except (TypeError, ValueError):
                        continue

            # حذف لحظات کاملاً تکراری (همان زمان دقیق) و مرتب‌سازی بر اساس زمان
            seen_times = set()
            deduped_events = []
            for ev in sorted(beat_events, key=lambda e: e["t"]):
                if ev["t"] in seen_times:
                    continue
                seen_times.add(ev["t"])
                deduped_events.append(ev)
            beat_events = deduped_events

        ass_file = None
        if text_events or watermark_enabled or beat_events:
            ass_file = self._generate_ass_subtitles(text_events, subtitle_defaults, watermark, duration, lightning, beat_events)

        inputs = []
        bg_color = str(getattr(self.project, "background", "#000000")).replace('#', '')
        inputs.extend(["-f", "lavfi", "-i", f"color=c={bg_color}:s={res_w}x{res_h}:r={fps}:d={duration}"])

        input_idx = 1
        filter_chains = []
        last_video_pad = "0:v"

        for i, ve in enumerate(visual_events):
            content = getattr(ve, "content", "")
            file_path = os.path.join(self.project_dir, content)
            if not os.path.exists(file_path):
                continue
            inputs.extend(["-i", file_path])

            coord = getattr(ve, "coordinate", None)
            w, h, x, y = res_w, res_h, 0, 0
            if coord and hasattr(coord, "to_pixels"):
                px = coord.to_pixels(res_w, res_h)
                w = px['w'] if px['w'] > 0 else res_w
                h = px['h'] if px['h'] > 0 else res_h
                x, y = px['x'], px['y']
            elif isinstance(coord, dict):
                try:
                    pct_w = float(str(coord.get("width", "100%")).replace('%', '')) / 100
                    pct_h = float(str(coord.get("height", "100%")).replace('%', '')) / 100
                    w, h = int(res_w * pct_w), int(res_h * pct_h)
                except Exception:
                    pass

            scaled_pad = f"s_{i}"
            filter_chains.append(f"[{input_idx}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black@0[{scaled_pad}]")

            next_pad = f"ov_{i}"
            st_t = getattr(ve, "start_time", 0.0)
            en_t = getattr(ve, "end_time", duration)
            enable_expr = f"between(t,{st_t},{en_t})"
            filter_chains.append(f"[{last_video_pad}][{scaled_pad}]overlay=x={x}:y={y}:enable='{enable_expr}'[{next_pad}]")
            last_video_pad = next_pad
            input_idx += 1

        if ass_file:
            sub_pad = "sub_out"
            escaped_ass = ass_file.replace('\\', '/').replace(':', '\\:')
            escaped_fontdir = FONT_DIR.replace('\\', '/').replace(':', '\\:')
            filter_chains.append(f"[{last_video_pad}]subtitles={escaped_ass}:fontsdir={escaped_fontdir}[{sub_pad}]")
            last_video_pad = sub_pad

        audio_pads = []
        for ae in audio_events:
            content = getattr(ae, "content", "")
            file_path = os.path.join(self.project_dir, content)
            if os.path.exists(file_path):
                inputs.extend(["-i", file_path])
                st_t = getattr(ae, "start_time", 0.0)
                delay_ms = int(st_t * 1000)
                apad = f"a_{input_idx}"
                filter_chains.append(f"[{input_idx}:a]adelay={delay_ms}|{delay_ms},atrim=0:{duration}[{apad}]")
                audio_pads.append(apad)
                input_idx += 1

        final_audio_opt = []
        if audio_pads:
            if len(audio_pads) == 1:
                final_audio_pad = audio_pads[0]
            else:
                final_audio_pad = "amix_out"
                filter_chains.append(f"{''.join([f'[{p}]' for p in audio_pads])}amix=inputs={len(audio_pads)}:duration=first:dropout_transition=2[{final_audio_pad}]")

            # اعمال اکولایزر/میکس صدا (باس، میدرنج، تربل، صدای کلی) - دقیقاً مطابق همان مقادیری
            # که کاربر توی پیش‌نمایش مرورگر (Web Audio API) تنظیم کرده، اینجا هم روی صدای نهایی اعمال می‌شود
            audio_eq = getattr(self.project, "audio_eq", None)
            eq_has_changes = isinstance(audio_eq, dict) and (
                any(float(audio_eq.get(k, 0) or 0) != 0 for k in ("bass", "mid", "treble"))
                or float(audio_eq.get("volume", 100) or 100) != 100
            )
            if eq_has_changes:
                eq_bass = float(audio_eq.get("bass", 0) or 0)
                eq_mid = float(audio_eq.get("mid", 0) or 0)
                eq_treble = float(audio_eq.get("treble", 0) or 0)
                eq_volume_pct = float(audio_eq.get("volume", 100) or 100)
                eq_pad = "eq_out"
                eq_filter_parts = []
                if eq_bass != 0:
                    eq_filter_parts.append(f"bass=g={eq_bass}:f=200:w=0.5")
                if eq_mid != 0:
                    eq_filter_parts.append(f"equalizer=f=1000:t=q:w=1.0:g={eq_mid}")
                if eq_treble != 0:
                    eq_filter_parts.append(f"treble=g={eq_treble}:f=3000:w=0.5")
                if eq_volume_pct != 100:
                    eq_filter_parts.append(f"volume={max(0.0, eq_volume_pct)/100.0}")
                if eq_filter_parts:
                    eq_chain = ",".join(eq_filter_parts)
                    filter_chains.append(f"[{final_audio_pad}]{eq_chain}[{eq_pad}]")
                    final_audio_pad = eq_pad

            final_audio_opt = ["-map", f"[{final_audio_pad}]"]
        else:
            inputs.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"])
            final_audio_opt = ["-map", f"{input_idx}:a", "-shortest"]
            input_idx += 1

        filter_graph_str = ";".join(filter_chains)

        cmd = [ffmpeg_exe, "-y"] + inputs
        if filter_graph_str:
            cmd.extend(["-filter_complex", filter_graph_str])
        # نکته: last_video_pad وقتی خروجی واقعی یک فیلتر باشد باید با براکت [...] رفرنس شود،
        # اما وقتی هیچ فیلتر تصویری اجرا نشده (last_video_pad هنوز همان "0:v" اولیه است)،
        # این فقط یک stream specifier خام است و نباید داخل براکت گذاشته شود.
        video_map_ref = f"[{last_video_pad}]" if filter_graph_str and last_video_pad != "0:v" else "0:v"
        cmd.extend(["-map", video_map_ref] + final_audio_opt)
        cmd.extend(["-c:v", "libx264", "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-t", str(duration), self.output_path])

        self.progress_callback(15, "آغاز پردازش رندر و ترکیب مدیا...")
        process = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
        time_pattern = re.compile(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})")

        stderr_tail = []
        while True:
            line = process.stderr.readline()
            if not line and process.poll() is not None:
                break
            if line:
                stderr_tail.append(line)
                if len(stderr_tail) > 40:
                    stderr_tail.pop(0)
                match = time_pattern.search(line)
                if match:
                    h, m, s = float(match.group(1)), float(match.group(2)), float(match.group(3))
                    current_sec = h * 3600 + m * 60 + s
                    pct = min(95, 15 + int((current_sec / duration) * 80))
                    self.progress_callback(pct, f"رندر ویدیو: {int((current_sec/duration)*100)}% انجام شده...")

        ret = process.poll()
        if ret != 0:
            raise RuntimeError(f"FFmpeg failed with exit code {ret}:\n" + "".join(stderr_tail))

        self.progress_callback(100, "رندر با موفقیت به پایان رسید!")


class MoviePyRenderer(RenderEngine):
    def render(self):
        self.progress_callback(100, "رندر MoviePy انجام شد.")
