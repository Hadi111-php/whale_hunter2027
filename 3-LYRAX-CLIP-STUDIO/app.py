import os
from flask import Flask, render_template, request, jsonify, send_from_directory
from backend.models import Project
from backend.services import FileService, TimelineService, RenderService

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__, 
    static_folder=os.path.join(BASE_DIR, "static"), 
    template_folder=os.path.join(BASE_DIR, "templates")
)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024 # 500 MB max upload

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(os.path.join(BASE_DIR, "static"), "manifest.webmanifest", mimetype="application/manifest+json")

@app.route("/sw.js")
def service_worker():
    return send_from_directory(os.path.join(BASE_DIR, "static"), "sw.js", mimetype="application/javascript")

@app.route("/icon.svg")
def app_icon():
    return send_from_directory(os.path.join(BASE_DIR, "static"), "icon.svg", mimetype="image/svg+xml")

@app.route("/api/projects", methods=["GET"])
def get_projects():
    projects = FileService.list_projects()
    return jsonify({"status": "success", "projects": projects})

@app.route("/api/project/<project_name>", methods=["GET"])
def get_project(project_name):
    proj = FileService.load_project_json(project_name)
    if not proj:
        proj = Project(name=project_name)
        FileService.save_project_json(proj)
        
    media_files = FileService.list_project_files(project_name)
    return jsonify({
        "status": "success",
        "project": proj.to_dict(),
        "files": media_files
    })

@app.route("/api/project/<project_name>/save", methods=["POST"])
def save_project(project_name):
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No JSON data provided"}), 400
        
    data["name"] = project_name
    proj = Project.from_dict(data)
    FileService.save_project_json(proj)
    return jsonify({"status": "success", "message": "پروژه با موفقیت ذخیره شد"})

@app.route("/api/project/<project_name>/upload", methods=["POST"])
def upload_files(project_name):
    if "files" not in request.files:
        return jsonify({"status": "error", "message": "هیچ فایلی انتخاب نشده است"}), 400
        
    files = request.files.getlist("files")
    saved_names = []
    for f in files:
        if f and f.filename:
            name = FileService.save_uploaded_file(project_name, f)
            saved_names.append(name)
            
    media_files = FileService.list_project_files(project_name)
    return jsonify({
        "status": "success",
        "message": f"{len(saved_names)} فایل با موفقیت آپلود شد",
        "uploaded": saved_names,
        "files": media_files
    })

@app.route("/api/project/<project_name>/render", methods=["POST"])
def start_render(project_name):
    data = request.get_json() or {}
    engine = data.get("engine", "ffmpeg") # 'ffmpeg' or 'moviepy'
    proj_data = data.get("project", None)
    
    if proj_data:
        proj_data["name"] = project_name
        proj = Project.from_dict(proj_data)
        FileService.save_project_json(proj)
    else:
        proj = FileService.load_project_json(project_name)
        if not proj:
            return jsonify({"status": "error", "message": "پروژه یافت نشد"}), 404
            
    job_id = RenderService.start_render_job(proj, engine_type=engine)
    return jsonify({"status": "success", "job_id": job_id})

@app.route("/api/render_status/<job_id>", methods=["GET"])
def render_status(job_id):
    status = RenderService.get_job_status(job_id)
    return jsonify(status)

@app.route("/api/project/<project_name>/media/<filename>")
def serve_media(project_name, filename):
    proj_dir = FileService.get_project_dir(project_name)
    return send_from_directory(proj_dir, filename)

@app.route("/api/project/<project_name>/download/<filename>")
def download_output(project_name, filename):
    proj_dir = FileService.get_project_dir(project_name)
    return send_from_directory(proj_dir, filename, as_attachment=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
