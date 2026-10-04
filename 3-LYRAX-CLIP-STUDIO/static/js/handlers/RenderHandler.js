// static/js/handlers/RenderHandler.js
export class RenderHandler {
    static async saveProject(project) {
        try {
            const res = await fetch(`/api/project/${project.name}/save`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(project.toDict())
            });
            const data = await res.json();
            if (data.status === 'success') {
                alert("✅ پروژه و فایل سناریو (JSON) با موفقیت ذخیره شد!");
            } else {
                alert("❌ خطا در ذخیره پروژه: " + data.message);
            }
        } catch (err) {
            console.error("Save project error:", err);
            alert("❌ خطا در ارتباط با سرور هنگام ذخیره پروژه");
        }
    }

    static async uploadFiles(projectName, fileList) {
        const formData = new FormData();
        for (let i = 0; i < fileList.length; i++) {
            formData.append('files', fileList[i]);
        }

        try {
            const res = await fetch(`/api/project/${projectName}/upload`, {
                method: 'POST',
                body: formData
            });
            return await res.json();
        } catch (err) {
            console.error("Upload error:", err);
            throw err;
        }
    }

    static async startRender(project, engine = "ffmpeg", onProgress = null) {
        const modal = document.getElementById('progressModal');
        const fill = document.getElementById('progressFill');
        const msg = document.getElementById('renderMessage');

        modal.style.display = 'flex';
        fill.style.width = '5%';
        msg.innerText = "ارسال سناریو به سرور...";

        try {
            const res = await fetch(`/api/project/${project.name}/render`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    engine: engine,
                    project: project.toDict()
                })
            });
            const data = await res.json();
            
            if (data.status !== 'success') {
                throw new Error(data.message || "خطا در شروع رندر");
            }

            const jobId = data.job_id;

            // Poll progress
            const interval = setInterval(async () => {
                try {
                    const sRes = await fetch(`/api/render_status/${jobId}`);
                    const statusData = await sRes.json();

                    fill.style.width = `${statusData.progress || 0}%`;
                    msg.innerText = statusData.message || "در حال پردازش...";

                    if (onProgress) onProgress(statusData);

                    if (statusData.status === 'completed') {
                        clearInterval(interval);
                        msg.innerText = "✅ رندر با موفقیت به پایان رسید! در حال دانلود...";
                        setTimeout(() => {
                            modal.style.display = 'none';
                            // Trigger automatic download
                            window.location.href = `/api/project/${project.name}/download/${statusData.output_file}`;
                        }, 1500);
                    } else if (statusData.status === 'error') {
                        clearInterval(interval);
                        alert("❌ خطا در رندر: " + statusData.error);
                        modal.style.display = 'none';
                    }
                } catch (e) {
                    console.error("Polling error:", e);
                }
            }, 1000);

        } catch (err) {
            console.error("Render error:", err);
            alert("❌ خطا در رندر: " + err.message);
            modal.style.display = 'none';
        }
    }
}
