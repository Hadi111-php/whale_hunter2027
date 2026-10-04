// static/js/modules/MediaController.js
export class MediaController {
    constructor(project, onTimeUpdateCallback) {
        this.project = project;
        this.onTimeUpdateCallback = onTimeUpdateCallback || (() => {});
        this.audioElement = new Audio();
        this.isPlaying = false;
        this.activeAudioEvent = null;
        this.animFrameId = null;

        this.setupAudioListeners();
    }

    setupAudioListeners() {
        this.audioElement.addEventListener('ended', () => {
            this.pause();
            this.seek(0);
        });
    }

    syncWithTimeline() {
        // Find main audio event
        const audioEvt = this.project.timeline.events.find(e => e.type === 'audio');
        if (audioEvt && audioEvt !== this.activeAudioEvent) {
            this.activeAudioEvent = audioEvt;
            this.audioElement.src = `/api/project/${this.project.name}/media/${audioEvt.content}`;
            this.audioElement.load();
        }
    }

    play() {
        this.syncWithTimeline();
        this.isPlaying = true;
        this.project.timeline.isPlaying = true;

        if (this.audioElement.src && this.activeAudioEvent) {
            const audioOffset = Math.max(0, this.project.timeline.currentTime - this.activeAudioEvent.startTime);
            this.audioElement.currentTime = audioOffset;
            this.audioElement.play().catch(err => console.log("Audio play error:", err));
        }

        this.loop();
    }

    pause() {
        this.isPlaying = false;
        this.project.timeline.isPlaying = false;
        this.audioElement.pause();
        if (this.animFrameId) {
            cancelAnimationFrame(this.animFrameId);
            this.animFrameId = null;
        }
    }

    seek(timeSeconds) {
        this.project.timeline.currentTime = Math.min(timeSeconds, this.project.timeline.duration);
        if (this.activeAudioEvent && this.audioElement.src) {
            const audioOffset = Math.max(0, this.project.timeline.currentTime - this.activeAudioEvent.startTime);
            this.audioElement.currentTime = audioOffset;
        }
        this.onTimeUpdateCallback(this.project.timeline.currentTime);
    }

    loop() {
        if (!this.isPlaying) return;

        if (this.activeAudioEvent && !this.audioElement.paused) {
            this.project.timeline.currentTime = this.activeAudioEvent.startTime + this.audioElement.currentTime;
        } else {
            // Simulated timer if no audio
            this.project.timeline.currentTime += 1/60;
        }

        if (this.project.timeline.currentTime >= this.project.timeline.duration) {
            this.pause();
            this.seek(0);
        } else {
            this.onTimeUpdateCallback(this.project.timeline.currentTime);
            this.animFrameId = requestAnimationFrame(() => this.loop());
        }
    }
}
