import json
import os

class Coordinate:
    def __init__(self, x=0, y=0, width="100%", height="100%"):
        self.x = x
        self.y = y
        self.width = width
        self.height = height

    @staticmethod
    def _parse_val(val, total):
        if isinstance(val, str) and val.strip().endswith('%'):
            try:
                pct = float(val.strip()[:-1])
                return int((pct / 100.0) * total)
            except ValueError:
                return 0
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return 0

    def to_pixels(self, canvas_w, canvas_h):
        return {
            "x": self._parse_val(self.x, canvas_w),
            "y": self._parse_val(self.y, canvas_h),
            "w": self._parse_val(self.width, canvas_w),
            "h": self._parse_val(self.height, canvas_h)
        }

    def to_dict(self):
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height
        }


class Event:
    def __init__(self, event_id, name, event_type, start_time=0.0, end_time=0.0, content="", coordinate=None, style=None):
        self.id = event_id
        self.name = name
        self.type = event_type  # 'audio', 'video', 'image', 'lyrics', 'text'
        self.start_time = float(start_time)
        self.end_time = float(end_time)
        self.content = content  # filename or text string
        self.coordinate = coordinate if coordinate else Coordinate()
        self.style = style if style else {
            "font_size": 52,
            "color": "#FFF000",       # Lemon yellow
            "stroke_color": "#000000",# Black outline
            "stroke_width": 4
        }

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "content": self.content,
            "coordinate": self.coordinate.to_dict(),
            "style": self.style
        }

    @classmethod
    def from_dict(cls, d):
        coord_d = d.get("coordinate", {})
        coord = Coordinate(
            x=coord_d.get("x", 0),
            y=coord_d.get("y", 0),
            width=coord_d.get("width", "100%"),
            height=coord_d.get("height", "100%")
        )
        return cls(
            event_id=d.get("id", ""),
            name=d.get("name", ""),
            event_type=d.get("type", "text"),
            start_time=d.get("start_time", 0.0),
            end_time=d.get("end_time", 0.0),
            content=d.get("content", ""),
            coordinate=coord,
            style=d.get("style", None)
        )


class Project:
    def __init__(self, name="default_project", resolution=None, fps=30, background="#000000"):
        self.name = name
        self.resolution = resolution if resolution else [1080, 1920] # Vertical 9:16
        self.fps = int(fps)
        self.background = background
        self.events = []
        self.duration = 0.0

    def add_event(self, event: Event):
        self.events.append(event)
        if event.end_time > self.duration:
            self.duration = event.end_time

    def calculate_duration(self):
        max_t = 0.0
        for e in self.events:
            if e.end_time > max_t:
                max_t = e.end_time
        self.duration = max_t
        return self.duration

    def to_dict(self):
        return {
            "name": self.name,
            "resolution": self.resolution,
            "fps": self.fps,
            "background": self.background,
            "duration": self.duration,
            "events": [e.to_dict() for e in self.events]
        }

    @classmethod
    def from_dict(cls, d):
        proj = cls(
            name=d.get("name", "default_project"),
            resolution=d.get("resolution", [1080, 1920]),
            fps=d.get("fps", 30),
            background=d.get("background", "#000000")
        )
        for e_dict in d.get("events", []):
            proj.add_event(Event.from_dict(e_dict))
        proj.calculate_duration()

        # فیلدهای پویا/اختیاری که در __init__ رسمی نیستند ولی renderers.py با getattr
        # می‌خواندشان (subtitle_defaults, audio_eq, watermark, lightning,
        # manual_lightning_timestamps). قبلاً from_dict این‌ها را منتقل نمی‌کرد، یعنی
        # حتی اگر کاربر این تنظیمات را در JSON export/import کرده بود، در رندر نهایی
        # backend اصلاً دیده نمی‌شدند مگر مستقیماً روی آبجکت ست می‌شدند.
        for optional_key in (
            "subtitle_defaults", "audio_eq", "watermark", "lightning",
            "manual_lightning_timestamps",
        ):
            if optional_key in d:
                setattr(proj, optional_key, d[optional_key])

        return proj
