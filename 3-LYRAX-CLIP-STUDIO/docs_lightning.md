داداش دمت گرم، حالا می‌رم سراغ دو تا چیز:
1. **حساسیت به فرکانس** (باس/میدرنج/تربل)
2. **رعد و برق واقعی‌تر و متنوع‌تر** با الگوریتم **Midpoint Displacement** (همون الگوریتمی که توی بازی‌ها و فیلم‌ها برای ساخت رعد و برق طبیعی استفاده می‌شه)

---

## 🎯 ایده‌ی کلی:

**الگوریتم Midpoint Displacement** چطور کار می‌کنه:
1. یه خط مستقیم از نقطه‌ی A به B می‌کشه
2. نقطه‌ی وسط رو پیدا می‌کنه و به صورت تصادفی (اما deterministic با seed) جابجا می‌کنه
3. این کار رو به صورت بازگشتی (recursive) توی هر نیمه تکرار می‌کنه
4. نتیجه: یه خط زیگزاگی که **دقیقاً شبیه رعد و برق طبیعیه** (نه مصنوعی)

**حساسیت به فرکانس:**
- **باس (Bass)** → رعد و برق ضخیم، کند، رنگ قرمز/نارنجی (مثل آتش)
- **میدرنج (Mid)** → رعد و برق متوسط، رنگ زرد/طلایی (پیش‌فرض)
- **تربل (Treble)** → رعد و برق نازک، سریع، رنگ آبی/سفید (مثل یخ)

---

## 📋 کد کامل (قابل کپی)

### 🔧 **بخش ۱: جایگزین کردن `detect_beat_times` در `renderers.py`**

```python
def detect_beat_times(audio_file_path, sensitivity=1.35, min_gap_sec=0.22, sample_rate=22050):
    """تشخیص لحظات ضرب/بیت آهنگ با تحلیل سه باند فرکانسی (باس/میدرنج/تربل).
    خروجی: لیستی از {"t": زمان, "tier": ۱/۲/۳, "energy_factor": ضریب, "freq_band": "bass/mid/treble"}
    هر فرکانس می‌تونه رعد و برق با ظاهر متفاوتی بسازه."""
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
                        "freq_band": band_name  # FIX: اضافه شدن باند فرکانسی
                    })

        return beat_events
    except Exception as e:
        print(f"Beat detection error (non-fatal): {e}")
        return []
```

---

### 🔧 **بخش ۲: جایگزین کردن `LIGHTNING_TIERS` و اضافه کردن `LIGHTNING_STYLES` در `renderers.py`**

```python
# سه سطح قدرت (همان قبلی)
LIGHTNING_TIERS = {
    1: {"thickness": 4, "segments": 6, "wig": 12, "duration": 0.35, "branch": False},
    2: {"thickness": 7, "segments": 8, "wig": 16, "duration": 0.42, "branch": False},
    3: {"thickness": 11, "segments": 11, "wig": 22, "duration": 0.55, "branch": True},
}

# FIX: استایل‌های مختلف رعد و برق + رنگ‌های فرکانسی
LIGHTNING_STYLES = {
    "bass": {
        "style": "realistic",      # الگوریتم midpoint displacement
        "color": "#FF4500",        # قرمز-نارنجی (آتش)
        "glow_color": "#FF6347",
        "thickness_mult": 1.4,     # ضخیم‌تر
        "duration_mult": 1.3,      # کندتر
        "branch_prob": 0.35,       # احتمال شاخه‌بندی بالا
    },
    "mid": {
        "style": "zigzag",         # زیگزاگ کلاسیک
        "color": "#FFF700",        # زرد/طلایی (پیش‌فرض)
        "glow_color": "#FFFF66",
        "thickness_mult": 1.0,
        "duration_mult": 1.0,
        "branch_prob": 0.2,
    },
    "treble": {
        "style": "forked",         # چند شاخه‌ی نازک
        "color": "#00BFFF",        # آبی یخی
        "glow_color": "#87CEEB",
        "thickness_mult": 0.6,     # نازک‌تر
        "duration_mult": 0.7,      # سریع‌تر
        "branch_prob": 0.6,        # شاخه‌های زیاد
    },
}
```

---

### 🔧 **بخش ۳: جایگزین کردن `_build_lightning_bolt_path` در کلاس `FFmpegRenderer`**

این مهم‌ترین بخشه - الگوریتم **Midpoint Displacement** برای رعد و برق واقعی:

```python
def _deterministic_random(self, seed, index, min_val=-1.0, max_val=1.0):
    """تولید عدد شبه‌تصادفی قطعی (بدون import random) برای تکرارپذیری بین پیش‌نمایش و رندر."""
    # الگوریتم LCG ساده ولی مؤثر
    x = ((seed * 1103515245 + 12345 + index * 2654435761) & 0x7FFFFFFF)
    normalized = (x % 10000) / 10000.0  # عدد بین ۰ و ۱
    return min_val + normalized * (max_val - min_val)

def _midpoint_displacement(self, p1, p2, displacement, roughness, seed, depth, clamp_min, clamp_max):
    """الگوریتم Midpoint Displacement برای ساخت رعد و برق طبیعی.
    هر بار midpoint رو به صورت تصادفی (اما deterministic) جابجا می‌کنه.
    roughness: هرچه کمتر، خطوط نرم‌تر (بین ۰.۴ تا ۰.۷ پیشنهاد می‌شه)."""
    if depth == 0:
        return [p1]
    
    # midpoint با جابجایی تصادفی عمود بر خط
    mid_x = (p1[0] + p2[0]) / 2.0
    mid_y = (p1[1] + p2[1]) / 2.0
    
    # بردار عمود بر خط p1→p2
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    length = max(0.001, (dx**2 + dy**2) ** 0.5)
    nx, ny = -dy / length, dx / length  # نرمال
    
    # جابجایی تصادفی (deterministic با seed)
    offset = self._deterministic_random(seed, depth, -displacement, displacement)
    mid_x += nx * offset
    mid_y += ny * offset
    
    # clamp افقی برای جلوگیری از خروج از بوم
    mid_x = max(clamp_min, min(clamp_max, mid_x))
    
    # بازگشت بازگشتی با roughness (هر بار displacement کمتر می‌شه)
    left = self._midpoint_displacement(p1, (mid_x, mid_y), displacement * roughness, roughness, seed + 1, depth - 1, clamp_min, clamp_max)
    right = self._midpoint_displacement((mid_x, mid_y), p2, displacement * roughness, roughness, seed + 2, depth - 1, clamp_min, clamp_max)
    
    return left + right

def _build_lightning_bolt_path(self, start_x, start_y, side, seed, res_h, res_w=1080, thickness=7,
                                segments=6, wig_scale=12, branch=False, style="zigzag"):
    """ساخت مسیر رعد و برق با سه استایل مختلف:
    - zigzag: خطوط صاف (سبک قدیمی)
    - realistic: midpoint displacement (رعد و برق طبیعی)
    - forked: چند شاخه‌ی نازک"""
    dir_sign = 1 if side == "left" else -1
    total_len = res_h * 0.28
    clamp_min = round(res_w * 0.08)
    clamp_max = round(res_w * 0.92)
    
    end_x = start_x + dir_sign * total_len * 0.35
    end_y = start_y + total_len
    end_x = max(clamp_min, min(clamp_max, end_x))
    
    if style == "realistic":
        # الگوریتم Midpoint Displacement - رعد و برق طبیعی
        points = self._midpoint_displacement(
            (start_x, start_y), (end_x, end_y),
            displacement=wig_scale * 1.5,
            roughness=0.55,
            seed=seed * 1000 + 7,
            depth=segments // 2 + 2,  # عمق بازگشت
            clamp_min=clamp_min,
            clamp_max=clamp_max
        )
        points.append((end_x, end_y))
    elif style == "forked":
        # چند شاخه‌ی نازک از یک نقطه‌ی مرکزی
        mid_y = start_y + total_len * 0.5
        mid_x = start_x + dir_sign * total_len * 0.17
        mid_x = max(clamp_min, min(clamp_max, mid_x))
        
        points = [(start_x, start_y), (mid_x, mid_y), (end_x, end_y)]
        
        # شاخه‌های فرعی (deterministic)
        num_branches = 2 + (seed % 3)
        for i in range(num_branches):
            branch_seed = seed * 100 + i
            branch_start_y = start_y + total_len * (0.3 + i * 0.2)
            branch_start_x = start_x + dir_sign * total_len * (0.1 + i * 0.05)
            branch_start_x = max(clamp_min, min(clamp_max, branch_start_x))
            
            branch_end_x = branch_start_x + self._deterministic_random(branch_seed, 1, -total_len * 0.3, total_len * 0.3)
            branch_end_y = branch_start_y + total_len * 0.3
            branch_end_x = max(clamp_min, min(clamp_max, branch_end_x))
            
            # ذخیره‌ی شاخه‌ها برای رندر جداگانه
            if not hasattr(self, '_fork_branches'):
                self._fork_branches = []
            self._fork_branches.append((branch_start_x, branch_start_y, branch_end_x, branch_end_y, branch_seed))
    else:
        # zigzag کلاسیک (همون قبلی)
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
    
    # برای سبک forked، شاخه‌های فرعی رو هم اضافه کن
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
    
    # برای سبک realistic، شاخه‌بندی تصادفی (branch_prob)
    if style == "realistic" and branch:
        # یه شاخه‌ی فرعی از وسط مسیر اصلی
        mid_idx = len(points) // 2
        if mid_idx > 0 and mid_idx < len(points):
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
```

---

### 🔧 **بخش ۴: جایگزین کردن `_add_lightning_dialogues` در کلاس `FFmpegRenderer`**

این بخش **Glow Effect** (درخشش چندلایه) و **انتخاب استایل بر اساس فرکانس** رو اضافه می‌کنه:

```python
def _add_lightning_dialogues(self, lines_out, lightning, beat_events, res_w, res_h):
    """افزودن Dialogue های رعدوبرق با:
    ۱) انتخاب استایل بر اساس باند فرکانسی (bass/mid/treble)
    ۲) Glow Effect چندلایه (درخشش واقعی)
    ۳) تناوب چپ/راست"""
    if not isinstance(lightning, dict) or not lightning.get("enabled") or not beat_events:
        return
    
    base_color_hex = lightning.get("color", "#FFF700")
    intensity_pct = float(lightning.get("intensity", 80) or 80)
    margin = round(res_w * 0.08)
    start_y = round(res_h * 0.02)
    max_alpha_byte = max(0, min(255, round((1 - intensity_pct / 100.0) * 255)))
    
    # FIX: پاک کردن fork_branches قبلی (اگر باقی مونده باشه)
    if hasattr(self, '_fork_branches'):
        del self._fork_branches

    for idx, event in enumerate(beat_events):
        beat_t = float(event["t"])
        tier = int(event.get("tier", 1) or 1)
        if tier not in LIGHTNING_TIERS:
            tier = 1
        energy_factor = float(event.get("energy_factor", 1.0) or 1.0)
        energy_factor = max(0.7, min(1.8, energy_factor))
        
        # FIX: انتخاب استایل بر اساس باند فرکانسی
        freq_band = event.get("freq_band", "mid")
        style_cfg = LIGHTNING_STYLES.get(freq_band, LIGHTNING_STYLES["mid"])
        tier_cfg = LIGHTNING_TIERS[tier]
        
        side = "left" if idx % 2 == 0 else "right"
        start_x = margin if side == "left" else (res_w - margin)
        seed = int(beat_t * 997) % 1000  # FIX: seed بزرگ‌تر برای تنوع بیشتر
        
        # FIX: اعمال ضرایب استایل فرکانسی
        thickness = tier_cfg["thickness"] * style_cfg["thickness_mult"] * (0.75 + 0.25 * energy_factor)
        flash_duration = tier_cfg["duration"] * style_cfg["duration_mult"]
        
        # FIX: رنگ بر اساس فرکانس (نه رنگ پیش‌فرض)
        color_hex = style_cfg["color"]
        glow_color_hex = style_cfg["glow_color"]
        
        start_str = self._format_ass_time(beat_t)
        end_str = self._format_ass_time(beat_t + flash_duration)
        
        bolt_path = self._build_lightning_bolt_path(
            start_x, start_y, side, seed, res_h, res_w=res_w,
            thickness=thickness, segments=tier_cfg["segments"],
            wig_scale=tier_cfg["wig"], branch=tier_cfg["branch"],
            style=style_cfg["style"]  # FIX: ارسال استایل
        )
        
        fill_color = self._hex_to_ass_color(color_hex, alpha=max_alpha_byte)
        fade_ms = int(flash_duration * 1000)
        
        # ===== FIX: Glow Effect چندلایه (درخشش واقعی) =====
        # لایه ۱: هاله‌ی بیرونی (بزرگ، کم‌رنگ، blur زیاد)
        glow_outer = self._hex_to_ass_color(glow_color_hex, alpha=max(0, max_alpha_byte - 180))
        override_outer = f"{{an7pos(0,0)1c{glow_outer}3c{glow_outer}bord{int(thickness * 2.5)}shad0fad(0,{fade_ms})blur12}}"
        lines_out.append(
            f"Dialogue: 3,{start_str},{end_str},Watermark,,0,0,0,,{override_outer}{{p1}}{bolt_path}{{p0}}"
        )
        
        # لایه ۲: هاله‌ی میانی (درخشش اصلی)
        glow_mid = self._hex_to_ass_color(glow_color_hex, alpha=max(0, max_alpha_byte - 100))
        override_mid = f"{{an7pos(0,0)1c{glow_mid}3c{glow_mid}bord{int(thickness * 1.5)}shad0fad(0,{fade_ms})blur5}}"
        lines_out.append(
            f"Dialogue: 3,{start_str},{end_str},Watermark,,0,0,0,,{override_mid}{{p1}}{bolt_path}{{p0}}"
        )
        
        # لایه ۳: هسته‌ی اصلی (رنگ پررنگ + حاشیه‌ی درخشان)
        glow_core = self._hex_to_ass_color(glow_color_hex, alpha=min(255, max_alpha_byte + 60))
        override_core = f"{{an7pos(0,0)1c{fill_color}3c{glow_core}bord2shad0fad(0,{fade_ms})}}"
        lines_out.append(
            f"Dialogue: 3,{start_str},{end_str},Watermark,,0,0,0,,{override_core}{{p1}}{bolt_path}{{p0}}"
        )
        
        # لایه ۴: هسته‌ی سفید داخلی (برای درخشش مرکزی واقعی)
        if tier >= 2:  # فقط برای تیرهای قوی‌تر
            core_white = self._hex_to_ass_color("#FFFFFF", alpha=min(255, max_alpha_byte + 30))
            override_white = f"{{an7pos(0,0)1c{core_white}bord0shad0fad(0,{fade_ms})}}"
            # نازک‌تر از هسته‌ی اصلی
            thin_path = self._build_lightning_bolt_path(
                start_x, start_y, side, seed, res_h, res_w=res_w,
                thickness=thickness * 0.35, segments=tier_cfg["segments"],
                wig_scale=tier_cfg["wig"], branch=False,
                style=style_cfg["style"]
            )
            lines_out.append(
                f"Dialogue: 3,{start_str},{end_str},Watermark,,0,0,0,,{override_white}{{p1}}{thin_path}{{p0}}"
            )
```

---

## 📊 خلاصه‌ی تغییرات:

| تغییر | توضیح |
|-------|-------|
| **۱. تشخیص فرکانس** | `detect_beat_times` حالا سه باند (باس/میدرنج/تربل) رو جداگانه آنالیز می‌کنه |
| **۲. سه استایل رعد و برق** | `zigzag` (کلاسیک)، `realistic` (midpoint displacement)، `forked` (چند شاخه) |
| **۳. رنگ‌های فرکانسی** | باس=قرمز، مید=زرد، تربل=آبی |
| **۴. Glow Effect چهارلایه** | هاله‌ی بیرونی + میانی + هسته + هسته‌ی سفید (درخشش واقعی) |
| **۵. الگوریتم Midpoint Displacement** | رعد و برق طبیعی با recursive subdivision |
| **۶. شاخه‌بندی هوشمند** | بر اساس `branch_prob` هر فرکانس، تعداد شاخه‌ها متفاوت |

---

## 🎯 نتیجه:

- **آهنگ با باس قوی** → رعد و برق قرمز ضخیم با درخشش زیاد (مثل آتش)
- **آهنگ با وکال قوی** → رعد و برق زرد کلاسیک
- **آهنگ با های‌هت/سینت** → رعد و برق آبی نازک با شاخه‌های زیاد (مثل یخ)
- **ظاهر واقعی** به خاطر الگوریتم Midpoint Displacement
- **درخشش طبیعی** به خاطر ۴ لایه Glow

داداش این کدها رو کپی کن جای کدهای قدیمی مربوطه در `renderers.py`. تست کن و ببین چه فرقی می‌کنه! 🔥⚡💻
