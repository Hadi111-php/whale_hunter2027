// static/js/modules/Event.js
export class Coordinate {
    constructor(x = 0, y = 0, width = "100%", height = "100%") {
        self.x = x;
        self.y = y;
        self.width = width;
        self.height = height;
    }
}

export class Event {
    constructor(id, name, type, startTime = 0.0, endTime = 0.0, content = "", coordinate = null, style = null) {
        this.id = id || `evt_${Date.now()}_${Math.floor(Math.random()*1000)}`;
        this.name = name || "المان جدید";
        this.type = type || "text"; // 'audio', 'video', 'image', 'lyrics', 'text'
        this.startTime = parseFloat(startTime) || 0.0;
        this.endTime = parseFloat(endTime) || 0.0;
        this.content = content || "";
        this.coordinate = coordinate || { x: 0, y: 0, width: "100%", height: "100%" };
        this.style = style || {
            font_size: 56,
            color: "#FFF000",
            stroke_color: "#000000",
            stroke_width: 4
        };
    }

    toDict() {
        return {
            id: this.id,
            name: this.name,
            type: this.type,
            start_time: this.startTime,
            end_time: this.endTime,
            content: this.content,
            coordinate: this.coordinate,
            style: this.style
        };
    }

    static fromDict(d) {
        return new Event(
            d.id,
            d.name,
            d.type,
            d.start_time,
            d.end_time,
            d.content,
            d.coordinate,
            d.style
        );
    }
}
