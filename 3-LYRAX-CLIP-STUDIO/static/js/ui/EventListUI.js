// static/js/ui/EventListUI.js
import { Event } from '../modules/Event.js';

export class EventListUI {
    constructor(project) {
        this.project = project;
        this.tbody = document.getElementById('eventsTableBody');
        this.addBtn = document.getElementById('btnAddEvent');

        this.setupEvents();
    }

    setupEvents() {
        this.addBtn.addEventListener('click', () => {
            const newEvt = new Event(null, "المان سفارشی", "text", 0, 5, "متن تستی", { x: "10%", y: "40%", width: "80%", height: "20%" });
            this.project.timeline.addEvent(newEvt);
        });
    }

    render() {
        this.tbody.innerHTML = "";
        const events = this.project.timeline.events;

        if (events.length === 0) {
            this.tbody.innerHTML = `<tr><td colspan="8" style="color:var(--text-muted); padding:1.5rem;">هیچ المانی در تایم‌لاین وجود ندارد</td></tr>`;
            return;
        }

        for (const evt of events) {
            const tr = document.createElement('tr');
            tr.dataset.id = evt.id;

            const coord = evt.coordinate || { x: 0, y: 0, width: "100%", height: "100%" };

            tr.innerHTML = `
                <td>
                    <select class="evt-type" style="width:75px;">
                        <option value="audio" ${evt.type==='audio'?'selected':''}>صدا</option>
                        <option value="video" ${evt.type==='video'?'selected':''}>ویدیو</option>
                        <option value="image" ${evt.type==='image'?'selected':''}>تصویر</option>
                        <option value="lyrics" ${evt.type==='lyrics'?'selected':''}>لیریکس</option>
                        <option value="text" ${evt.type==='text'?'selected':''}>متن</option>
                    </select>
                </td>
                <td><input type="text" class="long-input evt-name" value="${evt.name || ''}" placeholder="نام"></td>
                <td><input type="text" class="long-input evt-content" value="${evt.content || ''}" placeholder="نام فایل یا متن"></td>
                <td><input type="number" step="0.1" class="evt-start" value="${evt.startTime}"></td>
                <td><input type="number" step="0.1" class="evt-end" value="${evt.endTime}"></td>
                <td>
                    <div style="display:flex; gap:2px; justify-content:center;">
                        <input type="text" class="evt-x" value="${coord.x}" title="X (px یا %)">
                        <input type="text" class="evt-y" value="${coord.y}" title="Y (px یا %)">
                    </div>
                </td>
                <td>
                    <div style="display:flex; gap:2px; justify-content:center;">
                        <input type="text" class="evt-w" value="${coord.width}" title="عرض">
                        <input type="text" class="evt-h" value="${coord.height}" title="ارتفاع">
                    </div>
                </td>
                <td>
                    <button class="btn btn-danger btn-sm btn-delete" title="حذف">🗑️</button>
                </td>
            `;

            // Attach input event listeners
            const bindUpdate = (selector, updater) => {
                const elem = tr.querySelector(selector);
                if (elem) {
                    elem.addEventListener('change', (e) => {
                        updater(e.target.value);
                        this.project.timeline.recalculateDuration();
                        this.project.timeline.notifyChange();
                    });
                }
            };

            bindUpdate('.evt-type', val => evt.type = val);
            bindUpdate('.evt-name', val => evt.name = val);
            bindUpdate('.evt-content', val => evt.content = val);
            bindUpdate('.evt-start', val => evt.startTime = parseFloat(val) || 0);
            bindUpdate('.evt-end', val => evt.endTime = parseFloat(val) || 0);

            bindUpdate('.evt-x', val => evt.coordinate.x = val);
            bindUpdate('.evt-y', val => evt.coordinate.y = val);
            bindUpdate('.evt-w', val => evt.coordinate.width = val);
            bindUpdate('.evt-h', val => evt.coordinate.height = val);

            tr.querySelector('.btn-delete').addEventListener('click', () => {
                this.project.timeline.removeEvent(evt.id);
            });

            this.tbody.appendChild(tr);
        }
    }
}
