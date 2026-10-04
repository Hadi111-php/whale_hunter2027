// static/js/ui/LyricsUI.js
export class LyricsUI {
    constructor(lineHandler, mediaController) {
        this.lineHandler = lineHandler;
        this.mediaController = mediaController;

        this.displayElem = document.getElementById('currentLyricBox');
        this.btnNext = document.getElementById('btnNextLine');
        this.btnPrev = document.getElementById('btnPrevLine');
        this.rawInput = document.getElementById('rawLyricsText');
        this.btnLoadRaw = document.getElementById('btnLoadLyrics');
        this.animSelect = document.getElementById('lyricAnimationSelect');

        this.setupEvents();
    }

    setupEvents() {
        if (this.btnLoadRaw) {
            this.btnLoadRaw.addEventListener('click', () => {
                const text = this.rawInput.value.trim();
                if (!text) {
                    alert("لطفاً ابتدا متن لیریکس را در کادر تایپ یا پیست کنید.");
                    return;
                }
                this.lineHandler.setRawLyrics(text);
                alert("✅ متن لیریکس بارگذاری شد! اکنون می‌توانید هنگام پخش موزیک، روی خط بعدی کلیک کنید.");
            });
        }

        if (this.btnNext) {
            this.btnNext.addEventListener('click', () => {
                const time = this.mediaController.project.timeline.currentTime;
                this.lineHandler.nextLine(time);
            });
        }

        if (this.btnPrev) {
            this.btnPrev.addEventListener('click', () => {
                const time = this.mediaController.project.timeline.currentTime;
                this.lineHandler.prevLine(time);
            });
        }

        if (this.animSelect) {
            this.animSelect.addEventListener('change', (e) => {
                this.lineHandler.setAnimationStyle(e.target.value);
            });
        }
    }

    updateDisplay() {
        if (this.displayElem) {
            const text = this.lineHandler.getCurrentLineText();
            this.displayElem.innerText = text;
        }
    }
}
