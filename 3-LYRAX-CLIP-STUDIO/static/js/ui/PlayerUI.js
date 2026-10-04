// static/js/ui/PlayerUI.js
export class PlayerUI {
    constructor(project, mediaController) {
        this.project = project;
        this.mediaController = mediaController;
        
        this.canvas = document.getElementById('previewCanvas');
        this.ctx = this.canvas.getContext('2d');
        this.slider = document.getElementById('timelineSlider');
        this.timeDisplay = document.getElementById('timeText');
        this.playBtn = document.getElementById('btnPlay');
        this.pauseBtn = document.getElementById('btnPause');

        this.setupEvents();
    }

    setupEvents() {
        this.slider.addEventListener('input', (e) => {
            const time = parseFloat(e.target.value);
            this.mediaController.seek(time);
        });

        this.playBtn.addEventListener('click', () => {
            this.mediaController.play();
            this.playBtn.style.display = 'none';
            this.pauseBtn.style.display = 'inline-flex';
        });

        this.pauseBtn.addEventListener('click', () => {
            this.mediaController.pause();
            this.pauseBtn.style.display = 'none';
            this.playBtn.style.display = 'inline-flex';
        });
    }

    formatTime(seconds) {
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        const ms = Math.floor((seconds % 1) * 10);
        return `${m >= 10 ? m : '0'+m}:${s >= 10 ? s : '0'+s}.${ms}`;
    }

    update(currentTime) {
        const dur = this.project.timeline.duration || 10.0;
        this.slider.max = dur;
        this.slider.value = currentTime;
        this.timeDisplay.innerText = `${this.formatTime(currentTime)} / ${this.formatTime(dur)}`;

        this.renderCanvas(currentTime);
    }

    renderCanvas(currentTime) {
        const w = this.canvas.width;
        const h = this.canvas.height;

        // Draw Background
        this.ctx.fillStyle = this.project.background || "#000000";
        this.ctx.fillRect(0, 0, w, h);

        const activeEvents = this.project.timeline.getActiveEvents(currentTime);

        // Sort visual elements so text is on top
        const visualEvents = activeEvents.filter(e => e.type === 'image' || e.type === 'video');
        const textEvents = activeEvents.filter(e => e.type === 'lyrics' || e.type === 'text');

        // Draw images placeholder/preview
        for (const ve of visualEvents) {
            this.ctx.fillStyle = "#2c3e50";
            const coord = ve.coordinate || { x: 0, y: 0, width: "100%", height: "100%" };
            
            const parseVal = (v, tot) => {
                if (typeof v === 'string' && v.endsWith('%')) {
                    return (parseFloat(v)/100) * tot;
                }
                return parseFloat(v) || 0;
            };

            const bx = parseVal(coord.x, w);
            const by = parseVal(coord.y, h);
            const bw = parseVal(coord.width, w) || w;
            const bh = parseVal(coord.height, h) || h;

            this.ctx.fillRect(bx, by, bw, bh);
            this.ctx.strokeStyle = "#FFF000";
            this.ctx.lineWidth = 2;
            this.ctx.strokeRect(bx, by, bw, bh);
            
            this.ctx.fillStyle = "#ffffff";
            this.ctx.font = "14px Vazirmatn";
            this.ctx.textAlign = "center";
            this.ctx.fillText(`[${ve.type}] ${ve.content}`, bx + bw/2, by + bh/2);
        }

        // Draw Persian Subtitles / Lyrics
        for (const te of textEvents) {
            const text = te.content || "";
            const style = te.style || { font_size: 56, color: "#FFF000", stroke_color: "#000000", stroke_width: 4 };
            
            // Scale font size from 1080p down to canvas width (preview canvas is ~270px wide, ratio is ~0.25)
            const scaleRatio = w / 1080;
            const previewFontSize = Math.max(14, Math.round((style.font_size || 56) * scaleRatio * 1.5));

            this.ctx.font = `bold ${previewFontSize}px Vazirmatn, Tahoma`;
            this.ctx.textAlign = "center";
            this.ctx.textBaseline = "middle";

            const coord = te.coordinate || { x: 0, y: "75%", width: "100%", height: "15%" };
            const parseVal = (v, tot) => {
                if (typeof v === 'string' && v.endsWith('%')) {
                    return (parseFloat(v)/100) * tot;
                }
                return parseFloat(v) || 0;
            };

            const tx = parseVal(coord.x, w) > 0 ? parseVal(coord.x, w) : w / 2;
            const ty = parseVal(coord.y, h) > 0 ? parseVal(coord.y, h) : h * 0.78;

            // Draw Black Outline
            this.ctx.strokeStyle = style.stroke_color || "#000000";
            this.ctx.lineWidth = Math.max(2, Math.round((style.stroke_width || 4) * scaleRatio * 2));
            this.ctx.strokeText(text, tx, ty);

            // Draw Lemon Fill
            this.ctx.fillStyle = style.color || "#FFF000";
            this.ctx.fillText(text, tx, ty);
        }
    }
}
