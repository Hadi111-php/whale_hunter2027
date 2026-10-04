"""
Visual Element Grounding & Coordinate Locator.
Translates VLM bounding boxes and text queries into absolute pixel coordinates for mouse clicks.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("qwen_hands_eyes.visual_locator")

# Regex to detect coordinate patterns like [x, y], (x, y), {"x": 100, "y": 200}, or [ymin, xmin, ymax, xmax]
COORD_2D_RE = re.compile(r"\[\s*(\d+)\s*,\s*(\d+)\s*\]")
COORD_BOX_RE = re.compile(r"\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]")
JSON_BOX_RE = re.compile(r"\{[^{}]*\"x\"[^{}]*\}")


class VisualLocator:
    """Calculates screen coordinates from VLM visual analysis."""

    def __init__(self, screen_width: int = 1920, screen_height: int = 1080):
        self.screen_width = screen_width
        self.screen_height = screen_height

    def update_screen_dimensions(self, width: int, height: int) -> None:
        self.screen_width = max(1, width)
        self.screen_height = max(1, height)

    def parse_coordinates_from_vlm_output(self, vlm_text: str) -> Optional[Tuple[int, int]]:
        """Extracts target (x, y) coordinates from VLM text response."""
        # Check standard normalized bounding box [ymin, xmin, ymax, xmax] (0 to 1000 scale from Qwen-VL)
        box_match = COORD_BOX_RE.search(vlm_text)
        if box_match:
            y1, x1, y2, x2 = map(int, box_match.groups())
            # If coordinates are 0..1000 normalized
            if max(y1, x1, y2, x2) <= 1000:
                center_x = int(((x1 + x2) / 2.0 / 1000.0) * self.screen_width)
                center_y = int(((y1 + y2) / 2.0 / 1000.0) * self.screen_height)
                return center_x, center_y
            else:
                center_x = int((x1 + x2) / 2.0)
                center_y = int((y1 + y2) / 2.0)
                return min(center_x, self.screen_width), min(center_y, self.screen_height)

        # Check standard 2D point [x, y]
        point_match = COORD_2D_RE.search(vlm_text)
        if point_match:
            x, y = map(int, point_match.groups())
            if max(x, y) <= 1000:
                real_x = int((x / 1000.0) * self.screen_width)
                real_y = int((y / 1000.0) * self.screen_height)
                return real_x, real_y
            return min(x, self.screen_width), min(y, self.screen_height)

        # Try parsing JSON structure
        try:
            for match in re.finditer(r"\{.*?\}", vlm_text, re.DOTALL):
                data = json.loads(match.group(0))
                if "x" in data and "y" in data:
                    x, y = int(data["x"]), int(data["y"])
                    return min(x, self.screen_width), min(y, self.screen_height)
                if "point" in data and isinstance(data["point"], list) and len(data["point"]) == 2:
                    return int(data["point"][0]), int(data["point"][1])
        except Exception:
            pass

        return None
