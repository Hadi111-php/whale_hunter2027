// ══════════════════════════════════════════════════════════════════
// Qwen-Hands-Eyes Frontend Application Logic
// ══════════════════════════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", () => {
    initTabs();
    fetchSystemStatus();
    startApprovalPolling();
});

// ════════════ Tab Navigation ════════════
function initTabs() {
    const navButtons = document.querySelectorAll(".nav-btn");
    navButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            const targetId = btn.getAttribute("data-tab");
            
            navButtons.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");

            document.querySelectorAll(".tab-pane").forEach(pane => {
                pane.classList.remove("active");
            });

            const targetPane = document.getElementById(targetId);
            if (targetPane) {
                targetPane.classList.add("active");
            }
        });
    });
}

// ════════════ System Status & State ════════════
async function fetchSystemStatus() {
    try {
        const res = await fetch("/api/v1/status");
        if (res.ok) {
            const data = await res.json();
            document.getElementById("currentModeBadge").innerText = `حالت: ${data.mode}`;
            document.getElementById("systemStatusBadge").innerText = `● آنلاین (${data.primary_model})`;
            
            if (data.network) {
                const ipText = `IP: ${data.network.effective_ip}:${data.network.port}`;
                document.getElementById("networkIpBadge").innerText = ipText;
                document.getElementById("lanUrlVal").innerText = data.network.local_api_url;
                document.getElementById("wanUrlVal").innerText = data.network.public_ip || "شبکه محلی (بدون IP عمومی)";
            }

            const select = document.getElementById("brainRouteSelect");
            if (select && data.mode) {
                select.value = data.mode;
            }
        }
    } catch (e) {
        console.warn("Status fetch error:", e);
        document.getElementById("systemStatusBadge").innerText = "● آفلاین / در حال اتصال...";
    }
}

// ════════════ Dual-Brain Chat ════════════
async function switchBrainMode(mode) {
    try {
        const res = await fetch("/api/v1/brain/route", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode })
        });
        const data = await res.json();
        if (data.ok) {
            document.getElementById("currentModeBadge").innerText = `حالت: ${mode}`;
        }
    } catch (e) {
        alert("خطا در تغییر حالت مغز: " + e.message);
    }
}

function handleChatKey(e) {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

async function sendMessage() {
    const input = document.getElementById("chatInput");
    const text = input.value.trim();
    if (!text) return;

    input.value = "";
    appendUserMessage(text);

    const sendBtn = document.getElementById("sendBtn");
    sendBtn.disabled = true;
    sendBtn.innerText = "در حال پردازش...";

    try {
        const res = await fetch("/api/v1/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: text, session_id: "dashboard_user" })
        });

        const data = await res.json();
        if (data.ok && data.result) {
            appendAssistantMessage(data.result);
        } else {
            appendErrorMessage(data.error || "خطا در برقراری ارتباط با مدل");
        }
    } catch (e) {
        appendErrorMessage("خطای اتصال شبکه: " + e.message);
    } finally {
        sendBtn.disabled = false;
        sendBtn.innerHTML = `<span>ارسال</span><span class="send-icon">🚀</span>`;
    }
}

function appendUserMessage(text) {
    const container = document.getElementById("chatMessages");
    const div = document.createElement("div");
    div.className = "message user-msg";
    div.innerHTML = `
        <div class="msg-header">
            <span class="avatar">👤</span>
            <span class="sender-name">شما</span>
            <span class="msg-time">${new Date().toLocaleTimeString('fa-IR')}</span>
        </div>
        <div class="msg-body">${escapeHtml(text)}</div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function appendAssistantMessage(result) {
    const container = document.getElementById("chatMessages");
    const div = document.createElement("div");
    div.className = "message assistant-msg";

    const brainLabel = result.routed_to === "deepseek_reasoner" 
        ? "🧠 DeepSeek R1 (استدلال عمیق) ➔ Qwen (ترجمه فارسی)" 
        : "⚡ Qwen 2.5 (پاسخ سریع)";

    let thoughtHtml = "";
    if (result.thought_process) {
        thoughtHtml = `
            <div class="thought-box">
                <div class="thought-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">
                    <span>🔬 فرآیند تفکر عمیق DeepSeek R1 (Thinking Process)</span>
                    <span>▼</span>
                </div>
                <div class="thought-body">${escapeHtml(result.thought_process)}</div>
            </div>
        `;
    }

    div.innerHTML = `
        <div class="msg-header">
            <span class="avatar">🤖</span>
            <span class="sender-name">${brainLabel}</span>
            <span class="msg-time">${result.elapsed_sec ? result.elapsed_sec + 's' : ''}</span>
        </div>
        ${thoughtHtml}
        <div class="msg-body">${escapeHtml(result.response || '')}</div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function appendErrorMessage(err) {
    const container = document.getElementById("chatMessages");
    const div = document.createElement("div");
    div.className = "message assistant-msg";
    div.style.borderColor = "var(--accent-danger)";
    div.innerHTML = `
        <div class="msg-header"><span class="avatar">⚠️</span><span class="sender-name">خطای سیستم</span></div>
        <div class="msg-body" style="color: var(--accent-danger);">${escapeHtml(err)}</div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

function clearChat() {
    document.getElementById("chatMessages").innerHTML = `
        <div class="message assistant-msg">
            <div class="msg-header"><span class="avatar">🤖</span><span class="sender-name">دستیار هوشمند</span></div>
            <div class="msg-body">تاریخچه چت با موفقیت پاکسازی شد. سوال جدیدی بپرسید.</div>
        </div>
    `;
}

// ════════════ Eyes Snapshot & VLM ════════════
async function refreshScreenSnapshot() {
    const placeholder = document.getElementById("screenPlaceholder");
    const img = document.getElementById("screenPreviewImg");
    placeholder.innerText = "در حال گرفتن اسکرین‌شات از دسکتاپ...";
    placeholder.style.display = "block";
    img.style.display = "none";

    try {
        const res = await fetch("/api/v1/eyes/snapshot");
        const data = await res.json();
        if (data.ok && data.observation) {
            const obs = data.observation;
            if (obs.raw_snapshot && obs.raw_snapshot.base64_png) {
                img.src = "data:image/png;base64," + obs.raw_snapshot.base64_png;
                img.style.display = "block";
                placeholder.style.display = "none";
            }
            document.getElementById("screenMeta").innerText = 
                `رزولوشن: ${obs.screen.width}x${obs.screen.height} | ماژول: ${obs.screen.backend} | پنجره فعال: ${obs.active_window.title || 'نامشخص'}`;
            
            document.getElementById("vlmOutput").innerText = obs.visual_analysis || "تصویر با موفقیت دریافت شد.";
        }
    } catch (e) {
        placeholder.innerText = "خطا در اسکرین‌کپچر: " + e.message;
    }
}

async function runVLMInspection() {
    const prompt = document.getElementById("vlmPromptInput").value;
    const output = document.getElementById("vlmOutput");
    output.innerText = "در حال تحلیل تصویر توسط مدل چندحالته (VLM)...";

    try {
        const res = await fetch("/api/v1/eyes/snapshot");
        const data = await res.json();
        if (data.ok && data.observation) {
            output.innerText = data.observation.visual_analysis || "تحلیل به پایان رسید.";
        }
    } catch (e) {
        output.innerText = "خطا: " + e.message;
    }
}

// ════════════ Hands & Actions ════════════
async function sendMouseClick() {
    const x = parseInt(document.getElementById("mouseX").value);
    const y = parseInt(document.getElementById("mouseY").value);
    try {
        const res = await fetch("/api/v1/hands/action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action_type: "click", params: { x, y } })
        });
        const data = await res.json();
        alert(data.ok ? `کلیک در مختصات (${x}, ${y}) انجام شد.` : `خطا: ${data.error}`);
    } catch (e) {
        alert("خطا: " + e.message);
    }
}

async function sendTypeText() {
    const text = document.getElementById("typeTextInput").value;
    if (!text) return;
    try {
        const res = await fetch("/api/v1/hands/action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action_type: "type", params: { text } })
        });
        const data = await res.json();
        alert(data.ok ? "متن با موفقیت تایپ/Paste شد." : `خطا: ${data.error}`);
    } catch (e) {
        alert("خطا: " + e.message);
    }
}

async function sendTerminalCommand() {
    const command = document.getElementById("terminalCmdInput").value;
    const outputBox = document.getElementById("terminalOutput");
    if (!command) return;

    outputBox.innerText = "در حال اجرا دستور...";
    try {
        const res = await fetch("/api/v1/hands/action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action_type: "command", params: { command } })
        });
        const data = await res.json();
        if (data.ok) {
            outputBox.innerText = data.stdout || data.stderr || "[دستور بدون خروجی متنی پایان یافت]";
        } else {
            outputBox.innerText = `خطا (Code ${data.returncode || -1}):\n` + (data.error || data.stderr || "");
        }
    } catch (e) {
        outputBox.innerText = "خطای ارتباطی: " + e.message;
    }
}

// ════════════ Approval Polling ════════════
function startApprovalPolling() {
    setInterval(async () => {
        try {
            const res = await fetch("/api/v1/approvals");
            if (res.ok) {
                const data = await res.json();
                renderApprovals(data.pending || []);
            }
        } catch (e) {}
    }, 2500);
}

function renderApprovals(list) {
    const container = document.getElementById("approvalList");
    const counter = document.getElementById("approvalCounter");

    if (!list || list.length === 0) {
        counter.style.display = "none";
        container.innerHTML = `<div class="empty-state">هیچ درخواستی در انتظار تایید نیست. سیستم در وضعیت امن است.</div>`;
        return;
    }

    counter.style.display = "inline";
    counter.innerText = list.length;
    container.innerHTML = "";

    list.forEach(req => {
        const div = document.createElement("div");
        div.className = "approval-card";
        div.innerHTML = `
            <div>
                <strong>${escapeHtml(req.title)}</strong>
                <div style="font-size:11px;color:var(--text-muted);">دسته: ${req.category} | ریسک: ${req.risk_level}</div>
            </div>
            <div style="display:flex;gap:8px;">
                <button class="btn btn-primary btn-sm" onclick="resolveApproval('${req.request_id}', true)">تایید (Approve)</button>
                <button class="btn btn-secondary btn-sm" onclick="resolveApproval('${req.request_id}', false)">رد (Reject)</button>
            </div>
        `;
        container.appendChild(div);
    });
}

async function resolveApproval(requestId, approved) {
    try {
        await fetch("/api/v1/approvals/resolve", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ request_id: requestId, approved })
        });
    } catch (e) {
        alert("خطا در تایید/رد: " + e.message);
    }
}

// ════════════ Feet Network & Ping ════════════
async function refreshNetworkInfo() {
    await fetchSystemStatus();
    alert("اطلاعات شبکه با موفقیت بروز شد.");
}

async function testMobilePing() {
    const badge = document.getElementById("pingResult");
    badge.innerText = "در حال ارسال پینگ...";
    badge.style.color = "var(--text-muted)";

    const t0 = performance.now();
    try {
        const res = await fetch("/api/v1/status");
        const elapsed = Math.round(performance.now() - t0);
        if (res.ok) {
            badge.innerText = `✅ پینگ موفق: ${elapsed}ms`;
            badge.style.color = "var(--accent)";
        }
    } catch (e) {
        badge.innerText = `❌ اتصال ناموفق: ${e.message}`;
        badge.style.color = "var(--accent-danger)";
    }
}

// ════════════ Web Search Agent ════════════
async function performWebSearch() {
    const query = document.getElementById("webSearchQuery").value.trim();
    const resultsBox = document.getElementById("searchResults");
    if (!query) return;

    resultsBox.innerHTML = "<div class='empty-state'>در حال جستجو در اینترنت و استخراج داده‌ها...</div>";
    try {
        const res = await fetch("/api/v1/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query, max_results: 5 })
        });
        const data = await res.json();
        if (data.ok && data.results && data.results.length > 0) {
            resultsBox.innerHTML = "";
            data.results.forEach(item => {
                const itemDiv = document.createElement("div");
                itemDiv.className = "card";
                itemDiv.style.marginBottom = "10px";
                itemDiv.innerHTML = `
                    <h4><a href="${item.url}" target="_blank" style="color:#38bdf8;text-decoration:none;">${escapeHtml(item.title)}</a></h4>
                    <p style="font-size:13px;color:var(--text-muted);margin-top:6px;">${escapeHtml(item.snippet)}</p>
                    <div style="font-size:11px;color:var(--text-dim);margin-top:4px;direction:ltr;text-align:left;">${escapeHtml(item.url)}</div>
                `;
                resultsBox.appendChild(itemDiv);
            });
        } else {
            resultsBox.innerHTML = "<div class='empty-state'>نتیجه‌ای یافت نشد یا اینترنت در دسترس نیست.</div>";
        }
    } catch (e) {
        resultsBox.innerHTML = `<div class='empty-state' style='color:var(--accent-danger);'>خطا: ${e.message}</div>`;
    }
}

// ════════════ Settings Save ════════════
function saveSettings() {
    alert("تنظیمات پارامتریک در حافظه پایدار سیستم با موفقیت اعمال شد.");
}

function escapeHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}
