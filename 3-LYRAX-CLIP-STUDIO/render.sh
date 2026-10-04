#!/usr/bin/env bash
# render.sh - Fast standalone FFmpeg clip renderer
# Usage: ./render.sh <project_folder_path_or_name>

set -e

PROJECT_ARG="$1"
if [ -z "$PROJECT_ARG" ]; then
    echo "خطا: لطفاً نام پروژه یا مسیر پوشه پروژه را وارد کنید."
    echo "مثال: ./render.sh projects/my_song"
    exit 1
fi

# Determine directory
if [ -d "$PROJECT_ARG" ]; then
    PROJ_DIR="$PROJECT_ARG"
elif [ -d "projects/$PROJECT_ARG" ]; then
    PROJ_DIR="projects/$PROJECT_ARG"
else
    echo "خطا: پوشه پروژه در مسیر $PROJECT_ARG یافت نشد."
    exit 1
fi

JSON_FILE="$PROJ_DIR/project.json"
if [ ! -f "$JSON_FILE" ]; then
    echo "خطا: فایل سناریو project.json در پوشه $PROJ_DIR یافت نشد."
    exit 1
fi

echo "=================================================="
echo "🎬 رندر سریع و مستقل کلیپ با FFmpeg"
echo "📂 مسیر پروژه: $PROJ_DIR"
echo "=================================================="

# Use python embedded snippet or ffmpeg direct to run the exact backend render logic
python3 -c "
import sys, os
sys.path.insert(0, os.path.abspath('.'))
from backend.models import Project
from backend.renderers import FFmpegRenderer
import json

proj_dir = os.path.abspath('$PROJ_DIR')
json_path = os.path.join(proj_dir, 'project.json')

with open(json_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

proj = Project.from_dict(data)
output_path = os.path.join(proj_dir, f'{proj.name}_standalone.mp4')

def cb(pct, msg):
    print(f'[{pct}%] {msg}')

renderer = FFmpegRenderer(proj, proj_dir, output_path, cb)
renderer.render()
print(f'\n✅ خروجی نهایی در مسیر زیر ذخیره شد:\n{output_path}')
"
