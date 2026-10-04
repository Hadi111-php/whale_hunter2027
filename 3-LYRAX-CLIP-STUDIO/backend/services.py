import os
import re
import json
import shutil
import threading
import time
from werkzeug.utils import secure_filename
from backend.models import Project

BASE_PROJECTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "projects"))

class FileService:
    @staticmethod
    def get_project_dir(project_name):
        safe_name = secure_filename(project_name) or "default_project"
        path = os.path.join(BASE_PROJECTS_DIR, safe_name)
        os.makedirs(path, exist_ok=True)
        return path

    @staticmethod
    def save_project_json(project: Project):
        proj_dir = FileService.get_project_dir(project.name)
        file_path = os.path.join(proj_dir, "project.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(project.to_dict(), f, ensure_ascii=False, indent=2)
        return file_path

    @staticmethod
    def load_project_json(project_name):
        proj_dir = FileService.get_project_dir(project_name)
        file_path = os.path.join(proj_dir, "project.json")
        if not os.path.exists(file_path):
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Project.from_dict(data)

    @staticmethod
    def list_projects():
        os.makedirs(BASE_PROJECTS_DIR, exist_ok=True)
        projects = []
        for name in os.listdir(BASE_PROJECTS_DIR):
            proj_path = os.path.join(BASE_PROJECTS_DIR, name)
            if os.path.isdir(proj_path):
                json_path = os.path.join(proj_path, "project.json")
                files = os.listdir(proj_path)
                projects.append({
                    "name": name,
                    "has_json": os.path.exists(json_path),
                    "files_count": len(files)
                })
        return projects

    @staticmethod
    def save_uploaded_file(project_name, file_storage):
        proj_dir = FileService.get_project_dir(project_name)
        original_name = file_storage.filename or "uploaded_media"
        
        # FIX: حفظ کاراکترهای یونیکد و نام‌های فارسی به صورت کاملاً امن
        safe_name = re.sub(r'[\\/:*?"<>|]', '_', original_name)
        
        dest_path = os.path.join(proj_dir, safe_name)
        counter = 1
        base, ext = os.path.splitext(safe_name)
        while os.path.exists(dest_path):
            safe_name = f"{base}_{counter}{ext}"
            dest_path = os.path.join(proj_dir, safe_name)
            counter += 1
        
        file_storage.save(dest_path)
        return safe_name

    @staticmethod
    def list_project_files(project_name):
        proj_dir = FileService.get_project_dir(project_name)
        media_files = []
        for f in os.listdir(proj_dir):
            if f == "project.json":
                continue
            ext = f.lower().split('.')[-1]
            if ext in ['mp4', 'mp3', 'wav', 'jpg', 'jpeg', 'png']:
                media_files.append({"name": f, "type": ext})
        return media_files


class TimelineService:
    @staticmethod
    def optimize_timeline(project: Project):
        # Sort events by start time
        project.events.sort(key=lambda x: x.start_time)
        project.calculate_duration()
        return project


class RenderService:
    _jobs = {} # job_id -> status dict
    _lock = threading.Lock() # FIX: قفل ایمنی نخ‌ها برای جلوگیری از Race Condition

    @classmethod
    def start_render_job(cls, project: Project, engine_type="ffmpeg"):
        job_id = f"job_{int(time.time() * 1000)}"
        with cls._lock: # FIX: ثبت اتمیک وضعیت شروع
            cls._jobs[job_id] = {
                "status": "rendering",
                "progress": 0,
                "message": "در حال آماده‌سازی رندر...",
                "output_file": None,
                "error": None,
                "created_at": time.time()
            }

        from backend.renderers import FFmpegRenderer, MoviePyRenderer

        def run():
            try:
                proj_dir = FileService.get_project_dir(project.name)
                output_filename = f"{project.name}_export.mp4"
                output_path = os.path.join(proj_dir, output_filename)

                def progress_cb(pct, msg):
                    with cls._lock: # FIX: به‌روزرسانی ایمن پیشرفت
                        if job_id in cls._jobs:
                            cls._jobs[job_id]["progress"] = int(pct)
                            cls._jobs[job_id]["message"] = msg

                if engine_type == "moviepy":
                    renderer = MoviePyRenderer(project, proj_dir, output_path, progress_cb)
                else:
                    renderer = FFmpegRenderer(project, proj_dir, output_path, progress_cb)

                renderer.render()

                with cls._lock:
                    cls._jobs[job_id].update({
                        "status": "completed",
                        "progress": 100,
                        "message": "رندر با موفقیت به اتمام رسید!",
                        "output_file": output_filename
                    })
            except Exception as e:
                with cls._lock:
                    cls._jobs[job_id].update({
                        "status": "error",
                        "error": str(e),
                        "message": f"خطا در رندر: {str(e)}"
                    })

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return job_id

    @classmethod
    def get_job_status(cls, job_id):
        with cls._lock: # FIX: خواندن ایمن وضعیت
            return cls._jobs.get(job_id, {"status": "not_found"})

    @classmethod
    def cleanup_old_jobs(cls, max_age_seconds=3600):
        """FIX: پاکسازی حافظه از کارهای قدیمی تکمیل‌شده"""
        now = time.time()
        with cls._lock:
            old_jobs = [jid for jid, data in cls._jobs.items() if now - data.get("created_at", 0) > max_age_seconds]
            for jid in old_jobs:
                del cls._jobs[jid]
