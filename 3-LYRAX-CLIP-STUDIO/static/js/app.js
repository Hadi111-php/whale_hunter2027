// static/js/app.js
import { Project } from './modules/Project.js';
import { MediaController } from './modules/MediaController.js';
import { LineHandler } from './handlers/LineHandler.js';
import { RenderHandler } from './handlers/RenderHandler.js';
import { EventFactory } from './modules/EventFactory.js';
import { PlayerUI } from './ui/PlayerUI.js';
import { EventListUI } from './ui/EventListUI.js';
import { LyricsUI } from './ui/LyricsUI.js';

document.addEventListener('DOMContentLoaded', async () => {
    console.log("🚀 سیستم ویرایشگر ماژولار ساخت کلیپ آماده است");

    const projectNameInput = document.getElementById('projectName');
    const btnLoadProject = document.getElementById('btnLoadProject');
    const btnSaveProject = document.getElementById('btnSaveProject');
    const btnRenderVideo = document.getElementById('btnRenderVideo');
    const fileInput = document.getElementById('fileUploadInput');
    const uploadArea = document.getElementById('uploadArea');
    const uploadedFilesList = document.getElementById('uploadedFilesList');
    const renderEngineSelect = document.getElementById('renderEngineSelect');

    let project = new Project(projectNameInput.value.trim() || "my_awesome_clip");

    // Initialize core controllers
    const mediaController = new MediaController(project, (currentTime) => {
        playerUI.update(currentTime);
    });

    const lineHandler = new LineHandler(project, () => {
        lyricsUI.updateDisplay();
    });

    // Initialize UI components
    const playerUI = new PlayerUI(project, mediaController);
    const eventListUI = new EventListUI(project);
    const lyricsUI = new LyricsUI(lineHandler, mediaController);

    // Timeline subscription
    project.timeline.subscribe((tl) => {
        eventListUI.render();
        playerUI.update(tl.currentTime);
    });

    // Load project function
    async function loadProjectData(name) {
        try {
            const res = await fetch(`/api/project/${name}`);
            const data = await res.json();
            if (data.status === 'success') {
                project.loadFromDict(data.project);
                projectNameInput.value = project.name;
                updateFilesListUI(data.files);
                eventListUI.render();
                playerUI.update(0);
            }
        } catch (e) {
            console.error("Load project error:", e);
        }
    }

    function updateFilesListUI(files) {
        uploadedFilesList.innerHTML = "";
        if (!files || files.length === 0) {
            uploadedFilesList.innerHTML = `<span style="color:var(--text-muted); font-size:0.85rem;">فایلی آپلود نشده است</span>`;
            return;
        }

        for (const f of files) {
            const div = document.createElement('div');
            div.className = 'file-item';
            div.innerHTML = `
                <span>${f.name}</span>
                <div style="display:flex; gap:6px; align-items:center;">
                    <span class="file-badge">${f.type.toUpperCase()}</span>
                    <button class="btn btn-sm btn-add-evt" data-name="${f.name}" data-type="${f.type}">+ تایم‌لاین</button>
                </div>
            `;
            uploadedFilesList.appendChild(div);
        }

        // Attach quick add buttons
        uploadedFilesList.querySelectorAll('.btn-add-evt').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const fname = e.target.dataset.name;
                const ftype = e.target.dataset.type;
                let newEvt;
                if (['mp3', 'wav'].includes(ftype)) {
                    newEvt = EventFactory.createAudioEvent(fname, 30.0);
                } else if (['jpg', 'jpeg', 'png'].includes(ftype)) {
                    newEvt = EventFactory.createImageEvent(fname, 0.0, 5.0);
                } else if (ftype === 'mp4') {
                    newEvt = EventFactory.createVideoEvent(fname, 0.0, 10.0);
                }
                if (newEvt) {
                    project.timeline.addEvent(newEvt);
                }
            });
        });
    }

    // Setup Top Bar Events
    btnLoadProject.addEventListener('click', () => {
        const name = projectNameInput.value.trim() || "default_project";
        project.name = name;
        loadProjectData(name);
    });

    btnSaveProject.addEventListener('click', () => {
        project.name = projectNameInput.value.trim() || "default_project";
        RenderHandler.saveProject(project);
    });

    btnRenderVideo.addEventListener('click', () => {
        project.name = projectNameInput.value.trim() || "default_project";
        const engine = renderEngineSelect.value;
        RenderHandler.startRender(project, engine);
    });

    // Upload Events
    uploadArea.addEventListener('click', () => fileInput.click());
    
    fileInput.addEventListener('change', async (e) => {
        if (!e.target.files || e.target.files.length === 0) return;
        const name = projectNameInput.value.trim() || "default_project";
        project.name = name;
        
        try {
            uploadArea.style.opacity = '0.5';
            const data = await RenderHandler.uploadFiles(name, e.target.files);
            uploadArea.style.opacity = '1';
            
            if (data.status === 'success') {
                updateFilesListUI(data.files);
                
                // Auto add first uploaded audio if none exists
                const audioUploaded = data.uploaded.find(f => f.endsWith('.mp3') || f.endsWith('.wav'));
                if (audioUploaded && !project.timeline.events.find(ev => ev.type === 'audio')) {
                    const audEvt = EventFactory.createAudioEvent(audioUploaded, 30.0);
                    project.timeline.addEvent(audEvt);
                }

                alert(`✅ ${data.uploaded.length} فایل با موفقیت آپلود شد.`);
            }
        } catch (err) {
            uploadArea.style.opacity = '1';
            alert("❌ خطا در آپلود فایل‌ها");
        }
    });

    // Drag and Drop Upload
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = 'var(--lemon)';
    });
    uploadArea.addEventListener('dragleave', () => {
        uploadArea.style.borderColor = 'var(--border-color)';
    });
    uploadArea.addEventListener('drop', async (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = 'var(--border-color)';
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            const name = projectNameInput.value.trim() || "default_project";
            project.name = name;
            try {
                const data = await RenderHandler.uploadFiles(name, e.dataTransfer.files);
                if (data.status === 'success') {
                    updateFilesListUI(data.files);
                }
            } catch (err) {
                console.error("Drop upload error:", err);
            }
        }
    });

    // Initial Load
    await loadProjectData(project.name);
});
