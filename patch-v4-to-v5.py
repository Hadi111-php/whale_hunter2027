#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
  LyraX v4 → v5 Auto-Patch Script
  داداش با این اسکریپت، تمام تغییرات v5 رو خودکار روی پروژه اعمال می‌کنی
================================================================================
"""

import os, sys, shutil, re
from datetime import datetime

R = '\033[0;31m'; G = '\033[0;32m'; Y = '\033[1;33m'; C = '\033[0;36m'; NC = '\033[0m'
def log(msg): print(f"{C}[LYRAX-PATCH]{NC} {msg}")
def ok(msg): print(f"{G}✅ {msg}{NC}")
def warn(msg): print(f"{Y}⚠️  {msg}{NC}")
def err(msg): print(f"{R}❌ {msg}{NC}")

# Find project
PROJECT_DIR = ""
for d in [os.path.expanduser("~/whale_hunter2027/3-LYRAX-CLIP-STUDIO"),
          "/sdcard/Download/whale_hunter2027/3-LYRAX-CLIP-STUDIO",
          "./3-LYRAX-CLIP-STUDIO", "."]:
    if os.path.isdir(d) and os.path.exists(os.path.join(d, "templates", "index.html")):
        PROJECT_DIR = d; break

if not PROJECT_DIR:
    err("Project not found! Expected: ~/whale_hunter2027/3-LYRAX-CLIP-STUDIO")
    sys.exit(1)

log(f"Project found: {PROJECT_DIR}")
os.chdir(PROJECT_DIR)

# Backup
backup_dir = f"backup_v4_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
os.makedirs(backup_dir, exist_ok=True)
for f in ["templates/index.html", "studio.html"]:
    if os.path.exists(f): shutil.copy2(f, backup_dir)
ok(f"Backup saved to: {backup_dir}/")

# Read HTML
HTML_PATH = "templates/index.html"
with open(HTML_PATH, "r", encoding="utf-8") as f:
    html = f.read()
log(f"Read {HTML_PATH}: {len(html)} bytes")

patches = 0

# ===== MODULE 1: lyrax-lightning.js =====
LIGHTNING_JS = """/*!
 * LyraX Lightning Module v5
 */
(function (global) {
  'use strict';
  function clamp(v, a, b) { return v < a ? a : (v > b ? b : v); }
  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function hashString(s) {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
    return h >>> 0;
  }
  function round3(v) { return Math.round(v * 1000) / 1000; }

  const TIER_CONFIG = {
    1: { title: '⚡ رعد متوسط‌قوی', badgeText: '⚡ رعد ۱', badgeBg: 'rgba(255,247,0,0.18)', badgeColor: '#FFF700', displace: 110, branches: 1, branchProb: 0.18, width: 2.2, flashAlpha: 0.07, flashColor: '#FFF700', rain: false, duration: 0.38, echoCount: 2 },
    2: { title: '🌩️ رعد قوی (دو شاخه)', badgeText: '🌩️ رعد ۲', badgeBg: 'rgba(255,160,0,0.18)', badgeColor: '#FFA000', displace: 170, branches: 2, branchProb: 0.38, width: 2.8, flashAlpha: 0.12, flashColor: '#FFD54F', rain: false, duration: 0.52, echoCount: 3 },
    3: { title: '⛈️ رعد ویژه (چندشاخه + باران)', badgeText: '⛈️ رعد ۳', badgeBg: 'rgba(0,200,255,0.18)', badgeColor: '#00E5FF', displace: 260, branches: 5, branchProb: 0.58, width: 3.2, flashAlpha: 0.20, flashColor: '#B3E5FC', rain: true, duration: 0.85, echoCount: 4, rainDrops: 140, rainSpeedMin: 12, rainSpeedMax: 22, rainLenMin: 10, rainLenMax: 28 }
  };

  const rainCache = new Map();
  function getRainDrops(ev, W, H) {
    const key = ev.t.toFixed(3) + '|' + ev.tier;
    if (rainCache.has(key)) return rainCache.get(key);
    const cfg = TIER_CONFIG[ev.tier];
    const rnd = mulberry32(ev.seed + 999);
    const drops = [];
    const n = cfg.rainDrops || 0;
    for (let i = 0; i < n; i++) {
      drops.push({ x: rnd() * W, y: rnd() * H, len: cfg.rainLenMin + rnd() * (cfg.rainLenMax - cfg.rainLenMin), speed: cfg.rainSpeedMin + rnd() * (cfg.rainSpeedMax - cfg.rainSpeedMin), delay: rnd() * 0.4 });
    }
    rainCache.set(key, drops);
    return drops;
  }

  function drawLightningRec(ctx, x1, y1, x2, y2, displace, branches, width, color, rnd, depth) {
    if (displace < 2.5 || depth <= 0) {
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2);
      ctx.lineWidth = width; ctx.strokeStyle = color;
      ctx.shadowBlur = width * 3.5; ctx.shadowColor = color; ctx.stroke(); ctx.shadowBlur = 0; return;
    }
    const midX = (x1 + x2) / 2, midY = (y1 + y2) / 2;
    const nx = midX + (rnd() - 0.5) * displace, ny = midY + (rnd() - 0.5) * displace;
    drawLightningRec(ctx, x1, y1, nx, ny, displace / 2, branches, width, color, rnd, depth - 1);
    drawLightningRec(ctx, nx, ny, x2, y2, displace / 2, branches, width, color, rnd, depth - 1);
    if (branches > 0 && rnd() < TIER_CONFIG[3].branchProb * (depth / 5)) {
      const angle = rnd() * Math.PI * 2, branchLen = Math.hypot(x2 - x1, y2 - y1) * (0.25 + rnd() * 0.25);
      const branchColor = (color === '#ffffff' || color === '#B3E5FC') ? '#a8c0ff' : '#ffffff';
      drawLightningRec(ctx, nx, ny, nx + Math.cos(angle) * branchLen, ny + Math.sin(angle) * branchLen, displace / 2.5, branches - 2, width * 0.55, branchColor, rnd, depth - 2);
    }
  }

  function drawLightningBolt(ctx, startX, startY, endX, endY, tier, seed) {
    const cfg = TIER_CONFIG[tier], rnd = mulberry32(seed + 1), hue = rnd() > 0.7 ? cfg.flashColor : '#ffffff';
    for (let i = 0; i < cfg.echoCount; i++) {
      ctx.save(); ctx.globalAlpha = 0.25 - i * 0.06;
      drawLightningRec(ctx, startX, startY, endX, endY, cfg.displace, cfg.branches, cfg.width * (i + 1) * 0.45, hue, rnd, 7);
      ctx.restore();
    }
    ctx.save(); ctx.globalAlpha = 0.95;
    drawLightningRec(ctx, startX, startY, endX, endY, cfg.displace, cfg.branches, cfg.width, '#ffffff', rnd, 7);
    ctx.restore();
  }

  function drawRainLayer(ctx, elapsed, ev, W, H) {
    const cfg = TIER_CONFIG[ev.tier];
    if (!cfg.rain) return;
    const drops = getRainDrops(ev, W, H), env = Math.sin(Math.PI * clamp(elapsed / cfg.duration, 0, 1));
    if (env <= 0.01) return;
    ctx.save(); ctx.strokeStyle = 'rgba(174, 194, 224, 0.35)'; ctx.lineWidth = 1;
    for (const d of drops) {
      const local = elapsed - d.delay; if (local < 0) continue;
      const life = clamp(local / (cfg.duration - d.delay), 0, 1); if (life >= 1) continue;
      const y = d.y + life * (H + 60), x = d.x + Math.sin(life * 4 + d.delay) * 6;
      ctx.globalAlpha = env * (0.4 + (1 - life) * 0.6);
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x - 2, y + d.len); ctx.stroke();
    }
    ctx.restore();
  }

  function drawFlashLayer(ctx, elapsed, ev, W, H) {
    const cfg = TIER_CONFIG[ev.tier], p = clamp(elapsed / 0.12, 0, 1);
    if (p >= 1) return;
    ctx.save(); ctx.globalCompositeOperation = 'lighter'; ctx.globalAlpha = cfg.flashAlpha * Math.pow(1 - p, 1.4);
    ctx.fillStyle = cfg.flashColor; ctx.fillRect(0, 0, W, H); ctx.restore();
  }

  let lightningTimeline = [], firedKeys = new Set(), triggerHandler = null;

  function trigger(tier, t) {
    const cfg = TIER_CONFIG[tier]; if (!cfg) return null;
    const ev = { t: round3(Math.max(0, t || 0)), tier, duration: cfg.duration, seed: hashString('lightning|' + tier + '|' + round3(Math.max(0, t || 0)).toFixed(3)), title: cfg.title, badgeText: cfg.badgeText, badgeBg: cfg.badgeBg, badgeColor: cfg.badgeColor };
    lightningTimeline.push(ev); firedKeys.add(ev.t.toFixed(3) + '|' + ev.tier); return ev;
  }
  function getTimelineEvents() { return lightningTimeline.map(e => ({ t: e.t, tier: e.tier, duration: e.duration, title: e.title, badgeText: e.badgeText, badgeBg: e.badgeBg, badgeColor: e.badgeColor })); }
  function nudge(idx, delta) { const ev = lightningTimeline[idx]; if (ev) { ev.t = round3(Math.max(0, ev.t + delta)); firedKeys = new Set(); } }
  function update(idx, field, val) { const ev = lightningTimeline[idx]; if (ev) { if (field === 't') ev.t = round3(Math.max(0, parseFloat(val) || 0)); firedKeys = new Set(); } }
  function remove(idx) { if (idx >= 0 && idx < lightningTimeline.length) { const ev = lightningTimeline[idx]; rainCache.delete(ev.t.toFixed(3) + '|' + ev.tier); lightningTimeline.splice(idx, 1); firedKeys = new Set(); } }
  function clearAll() { lightningTimeline = []; rainCache.clear(); firedKeys = new Set(); }
  function restore(list) { if (!Array.isArray(list)) return; rainCache.clear(); lightningTimeline = list.filter(e => e && TIER_CONFIG[e.tier]).map(e => { const cfg = TIER_CONFIG[e.tier]; return { t: round3(parseFloat(e.t) || 0), tier: e.tier, duration: cfg.duration, seed: hashString('lightning|' + e.tier + '|' + (round3(parseFloat(e.t) || 0)).toFixed(3)), title: cfg.title, badgeText: cfg.badgeText, badgeBg: cfg.badgeBg, badgeColor: cfg.badgeColor }; }); firedKeys = new Set(); }
  function resetReplay() { firedKeys = new Set(); }
  function updateAndReplay(cur, dt) { if (!lightningTimeline.length) return; const win = Math.max(0.25, (dt || 0.03) * 2 + 0.06); for (let i = 0; i < lightningTimeline.length; i++) { const ev = lightningTimeline[i], key = ev.t.toFixed(3) + '|' + ev.tier; if (firedKeys.has(key)) continue; if (cur >= ev.t && (cur - ev.t) < win) firedKeys.add(key); else if (cur >= ev.t + 1.2) firedKeys.add(key); } }
  function drawAll(ctx, cur, W, H) {
    if (!lightningTimeline.length) return;
    for (let i = 0; i < lightningTimeline.length; i++) {
      const ev = lightningTimeline[i], elapsed = cur - ev.t; if (elapsed < 0 || elapsed > ev.duration) continue;
      const rnd = mulberry32(ev.seed + 42), sideToggle = Math.floor(ev.t * 3) % 2;
      const startX = sideToggle === 0 ? (rnd() * W * 0.3) : (W - rnd() * W * 0.3), startY = -20, endX = (0.2 + rnd() * 0.6) * W, endY = (0.3 + rnd() * 0.6) * H;
      try { drawFlashLayer(ctx, elapsed, ev, W, H); drawLightningBolt(ctx, startX, startY, endX, endY, ev.tier, ev.seed); drawRainLayer(ctx, elapsed, ev, W, H); } catch (err) {}
    }
  }
  function handleKey(e) { const map = { 'Digit1': 1, 'Digit2': 2, 'Digit3': 3 }; const tier = map[e.code]; if (!tier) return false; if (e.shiftKey || e.ctrlKey || e.metaKey || e.altKey) return false; if (typeof triggerHandler === 'function') { triggerHandler(tier); return true; } return false; }
  function setTriggerHandler(fn) { triggerHandler = fn; }

  global.LyraxLightning = { version: '2.0.0', TIER_CONFIG, trigger, getTimelineEvents, nudge, update, remove, clearAll, restore, resetReplay, updateAndReplay, drawAll, handleKey, setTriggerHandler };
})(window);
"""

modules_dir = os.path.join(PROJECT_DIR, "static", "js", "modules")
os.makedirs(modules_dir, exist_ok=True)
with open(os.path.join(modules_dir, "lyrax-lightning.js"), "w", encoding="utf-8") as f:
    f.write(LIGHTNING_JS)
ok("lyrax-lightning.js created")

# ===== MODULE 2: lyrax-rain.js =====
RAIN_JS = """/*!
 * LyraX Rain Module v5
 */
(function (global) {
  'use strict';
  function clamp(v, a, b) { return v < a ? a : (v > b ? b : v); }
  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function hashString(s) {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
    return h >>> 0;
  }
  function round3(v) { return Math.round(v * 1000) / 1000; }

  const RAIN_PRESETS = {
    light:  { title: '🌧️ باران ملایم', badgeText: '🌧️ باران', badgeBg: 'rgba(100,180,255,0.15)', badgeColor: '#90caf9', drops: 80,  speedMin: 8,  speedMax: 14, lenMin: 8,  lenMax: 18, alpha: 0.25 },
    medium: { title: '🌧️ باران متوسط', badgeText: '🌧️ باران', badgeBg: 'rgba(80,160,255,0.18)', badgeColor: '#64b5f6', drops: 140, speedMin: 12, speedMax: 20, lenMin: 12, lenMax: 24, alpha: 0.35 },
    heavy:  { title: '⛈️ باران سنگین', badgeText: '⛈️ باران', badgeBg: 'rgba(60,140,255,0.22)', badgeColor: '#42a5f5', drops: 220, speedMin: 16, speedMax: 28, lenMin: 16, lenMax: 32, alpha: 0.45 }
  };

  const dropCache = new Map();
  function getDrops(ev, W, H) {
    const key = ev.t.toFixed(3) + '|' + ev.preset;
    if (dropCache.has(key)) return dropCache.get(key);
    const cfg = RAIN_PRESETS[ev.preset] || RAIN_PRESETS.medium;
    const rnd = mulberry32(ev.seed);
    const drops = [];
    for (let i = 0; i < cfg.drops; i++) {
      drops.push({ x: rnd() * W, y: rnd() * H, len: cfg.lenMin + rnd() * (cfg.lenMax - cfg.lenMin), speed: cfg.speedMin + rnd() * (cfg.speedMax - cfg.speedMin), delay: rnd() * 0.5, sway: (rnd() - 0.5) * 1.5 });
    }
    dropCache.set(key, drops);
    return drops;
  }

  function drawRainLayer(ctx, elapsed, ev, W, H) {
    const cfg = RAIN_PRESETS[ev.preset] || RAIN_PRESETS.medium;
    const drops = getDrops(ev, W, H);
    const env = Math.sin(Math.PI * clamp(elapsed / (ev.duration || 2.0), 0, 1));
    if (env <= 0.01) return;
    ctx.save(); ctx.strokeStyle = 'rgba(174, 194, 224, ' + cfg.alpha + ')'; ctx.lineWidth = 1;
    for (const d of drops) {
      const local = elapsed - d.delay; if (local < 0) continue;
      const life = clamp(local / ((ev.duration || 2.0) - d.delay), 0, 1); if (life >= 1) continue;
      const y = d.y + life * (H + 80), x = d.x + Math.sin(life * 3 + d.delay) * d.sway * 4;
      ctx.globalAlpha = env * (0.5 + (1 - life) * 0.5);
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + d.sway, y + d.len); ctx.stroke();
    }
    ctx.restore();
  }

  let rainTimeline = [], firedKeys = new Set(), triggerHandler = null;
  function trigger(preset, t, duration) {
    const cfg = RAIN_PRESETS[preset]; if (!cfg) return null;
    const ev = { t: round3(Math.max(0, t || 0)), preset, duration: duration || 4.0, seed: hashString('rain|' + preset + '|' + round3(Math.max(0, t || 0)).toFixed(3)), title: cfg.title, badgeText: cfg.badgeText, badgeBg: cfg.badgeBg, badgeColor: cfg.badgeColor };
    rainTimeline.push(ev); firedKeys.add(ev.t.toFixed(3) + '|' + ev.preset); return ev;
  }
  function getTimelineEvents() { return rainTimeline.map(e => ({ t: e.t, preset: e.preset, duration: e.duration, title: e.title, badgeText: e.badgeText, badgeBg: e.badgeBg, badgeColor: e.badgeColor })); }
  function nudge(idx, delta) { const ev = rainTimeline[idx]; if (ev) { ev.t = round3(Math.max(0, ev.t + delta)); firedKeys = new Set(); } }
  function update(idx, field, val) { const ev = rainTimeline[idx]; if (ev) { if (field === 't') ev.t = round3(Math.max(0, parseFloat(val) || 0)); if (field === 'duration') ev.duration = Math.max(0.5, parseFloat(val) || 4.0); firedKeys = new Set(); } }
  function remove(idx) { if (idx >= 0 && idx < rainTimeline.length) { const ev = rainTimeline[idx]; dropCache.delete(ev.t.toFixed(3) + '|' + ev.preset); rainTimeline.splice(idx, 1); firedKeys = new Set(); } }
  function clearAll() { rainTimeline = []; dropCache.clear(); firedKeys = new Set(); }
  function restore(list) { if (!Array.isArray(list)) return; dropCache.clear(); rainTimeline = list.filter(e => e && RAIN_PRESETS[e.preset]).map(e => { const cfg = RAIN_PRESETS[e.preset]; return { t: round3(parseFloat(e.t) || 0), preset: e.preset, duration: parseFloat(e.duration) || 4.0, seed: hashString('rain|' + e.preset + '|' + (round3(parseFloat(e.t) || 0)).toFixed(3)), title: cfg.title, badgeText: cfg.badgeText, badgeBg: cfg.badgeBg, badgeColor: cfg.badgeColor }; }); firedKeys = new Set(); }
  function resetReplay() { firedKeys = new Set(); }
  function updateAndReplay(cur, dt) { if (!rainTimeline.length) return; const win = Math.max(0.25, (dt || 0.03) * 2 + 0.06); for (let i = 0; i < rainTimeline.length; i++) { const ev = rainTimeline[i], key = ev.t.toFixed(3) + '|' + ev.preset; if (firedKeys.has(key)) continue; if (cur >= ev.t && (cur - ev.t) < win) firedKeys.add(key); else if (cur >= ev.t + 1.2) firedKeys.add(key); } }
  function drawAll(ctx, cur, W, H) { if (!rainTimeline.length) return; for (let i = 0; i < rainTimeline.length; i++) { const ev = rainTimeline[i], elapsed = cur - ev.t; if (elapsed < 0 || elapsed > ev.duration) continue; try { drawRainLayer(ctx, elapsed, ev, W, H); } catch (err) {} } }
  function handleKey(e) { if (e.code !== 'KeyR') return false; if (e.shiftKey || e.ctrlKey || e.metaKey || e.altKey) return false; if (typeof triggerHandler === 'function') { triggerHandler('medium'); return true; } return false; }
  function setTriggerHandler(fn) { triggerHandler = fn; }

  global.LyraxRain = { version: '1.0.0', RAIN_PRESETS, trigger, getTimelineEvents, nudge, update, remove, clearAll, restore, resetReplay, updateAndReplay, drawAll, handleKey, setTriggerHandler };
})(window);
"""

with open(os.path.join(modules_dir, "lyrax-rain.js"), "w", encoding="utf-8") as f:
    f.write(RAIN_JS)
ok("lyrax-rain.js created")

# ===== PATCH HTML =====
# 1. Add script tags
if '/static/js/modules/lyrax-brand.js' in html and 'lyrax-lightning.js' not in html:
    html = html.replace(
        '<script src="/static/js/modules/lyrax-brand.js"></script>',
        '<script src="/static/js/modules/lyrax-brand.js"></script>\n    <script src="/static/js/modules/lyrax-lightning.js"></script>\n    <script src="/static/js/modules/lyrax-rain.js"></script>'
    )
    patches += 1; ok("Added module script tags")

# 2. Replace lightning buttons
old_btns = '<!-- سه دکمه‌ی سریع رعدوبرق، دقیقاً همین‌جا کنار تپ‌کردن خط‌ها -->'
if old_btns in html:
    html = html.replace(
        old_btns + '\n                    <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:0.3rem;">\n                        <button class="btn btn-warning" onclick="manualTriggerLightning(1)" style="flex:1; min-width:120px; font-weight:bold; font-size:1.02rem;">⚡ رعد قوی و کلفت</button>\n                        <button class="btn btn-danger" onclick="manualTriggerLightning(2)" style="flex:1; min-width:150px; font-weight:bold; font-size:1.05rem;">🌩️ رعد قوی و پیچیده (شاخه‌دار)</button>\n                    </div>',
        '<!-- سه دکمه‌ی سریع رعدوبرق v5 (۱=متوسط‌قوی ۲=قوی‌دو‌شاخه ۳=ویژه+باران) -->\n                    <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:0.3rem;">\n                        <button class="btn btn-warning" onclick="manualTriggerLightning(1)" style="flex:1; min-width:90px; font-weight:bold; font-size:0.92rem;">⚡ رعد ۱</button>\n                        <button class="btn btn-danger" onclick="manualTriggerLightning(2)" style="flex:1; min-width:90px; font-weight:bold; font-size:0.92rem;">🌩️ رعد ۲</button>\n                        <button class="btn btn-purple" onclick="manualTriggerLightning(3)" style="flex:1; min-width:90px; font-weight:bold; font-size:0.92rem;">️ رعد ۳ (باران)</button>\n                    </div>'
    )
    patches += 1; ok("Replaced lightning buttons")

# 3. Replace grid lightning buttons
old_grid = '⚡ افزودن رعد قوی در این ثانیه'
if old_grid in html:
    html = html.replace(
        '<button class="btn btn-warning btn-sm" onclick="addLightningAtCurrentTime(1)" style="padding:0.4rem 0.8rem; font-size:0.85rem;">⚡ افزودن رعد قوی در این ثانیه</button>\n                        <button class="btn btn-danger btn-sm" onclick="addLightningAtCurrentTime(2)" style="padding:0.4rem 0.8rem; font-size:0.85rem;">🌩️ افزودن رعد شاخه‌دار در این ثانیه</button>',
        '<button class="btn btn-warning btn-sm" onclick="addLightningAtCurrentTime(1)" style="padding:0.4rem 0.8rem; font-size:0.85rem;">⚡ رعد ۱</button>\n                        <button class="btn btn-danger btn-sm" onclick="addLightningAtCurrentTime(2)" style="padding:0.4rem 0.8rem; font-size:0.85rem;">🌩️ رعد ۲</button>\n                        <button class="btn btn-purple btn-sm" onclick="addLightningAtCurrentTime(3)" style="padding:0.4rem 0.8rem; font-size:0.85rem;">⛈️ رعد ۳</button>'
    )
    patches += 1; ok("Replaced grid lightning buttons")

# 4. Replace manualTriggerLightning
old_manual = 'function manualTriggerLightning(tier) {\n            tier = LIGHTNING_TIERS[tier] ? tier : 1;'
if old_manual in html:
    html = html.replace(
        old_manual + '\n            // اگر کاربر تیک «فعال‌سازی» را نزده باشد، با زدن دکمه‌ی دستی خودش روشن می‌شود\n            // (و همون لحظه هم روی کلیپ ثبت/رسم می‌شود) تا هیچ تپی هدر نره.\n            if (!lightningSettings.enabled) {\n                lightningSettings.enabled = true;\n                let cb = document.getElementById(\'lightningEnabled\');\n                if (cb) cb.checked = true;\n                showToast("⚡ جلوه‌ی رعدوبرق به‌صورت خودکار فعال شد.");\n            }\n            let cur = (audioFileObj && !audioElement.paused) ? audioElement.currentTime : simulatedTime;\n            // اگر آهنگی در حال پخش باشد، همان انرژی زنده‌ی لحظه (شبیه اکولایزر) هم روی ضخامت اثر می‌گذارد؛\n            // وگرنه یک ضریب خنثی (۱.۰) استفاده می‌شود.\n            updateLiveBassEnergyRatio();\n            triggerLightningFlash(cur, tier, liveBassEnergyRatio);\n            // این لحظه‌ی دستی (همراه با تیرش) را هم برای رندر نهایی ذخیره می‌کنیم (پایین‌تر توضیح داده می‌شود)\n            manualLightningTimestamps.push({ t: Math.round(cur * 1000) / 1000, tier });\n            showToast("⚡ رعدوبرق " + LIGHTNING_TIER_LABELS[tier] + " دستی ثبت شد در لحظه‌ی " + cur.toFixed(2) + "s");\n        }',
        'function manualTriggerLightning(tier) {\n            tier = (tier >= 1 && tier <= 3) ? tier : 1;\n            let cur = (audioFileObj && !audioElement.paused) ? audioElement.currentTime : simulatedTime;\n            if (window.LyraxLightning) {\n                window.LyraxLightning.trigger(tier, cur);\n                showToast("⚡ رعد " + tier + " ثبت شد در " + cur.toFixed(2) + "s");\n                renderDataGrid();\n            }\n        }'
    )
    patches += 1; ok("Replaced manualTriggerLightning")

# 5. Replace addLightningAtCurrentTime
old_add = 'function addLightningAtCurrentTime(tier) {\n            let cur = (audioFileObj && !audioElement.paused) ? audioElement.currentTime : simulatedTime;\n            let t = Math.round(cur * 100) / 100;\n            manualLightningTimestamps.push({ t, tier: tier || 1 });\n            renderDataGrid();\n        }'
if old_add in html:
    html = html.replace(
        old_add,
        'function addLightningAtCurrentTime(tier) {\n            let middleT = getMiddleTimeBetweenLines(currentLine);\n            if (middleT > 0 && window.LyraxLightning) {\n                window.LyraxLightning.trigger(tier || 1, middleT);\n                showToast("⚡ رعد " + (tier || 1) + " در وسط خطوط " + middleT.toFixed(2) + "s ثبت شد");\n                renderDataGrid();\n            } else {\n                manualTriggerLightning(tier);\n            }\n        }\n        function getMiddleTimeBetweenLines(lineIndex) {\n            if (!lyricsTimeline || lyricsTimeline.length === 0) return 0;\n            if (lineIndex <= 0) return lyricsTimeline[0] ? (lyricsTimeline[0].start || 0) : 0;\n            if (lineIndex >= lyricsTimeline.length) {\n                let last = lyricsTimeline[lyricsTimeline.length - 1];\n                return (last ? (last.end || last.start || 0) : 0) + 2;\n            }\n            let prevEnd = lyricsTimeline[lineIndex - 1] ? (lyricsTimeline[lineIndex - 1].end || lyricsTimeline[lineIndex - 1].start || 0) : 0;\n            let nextStart = lyricsTimeline[lineIndex] ? (lyricsTimeline[lineIndex].start || 0) : prevEnd + 2;\n            return prevEnd + (nextStart - prevEnd) / 2;\n        }'
    )
    patches += 1; ok("Replaced addLightningAtCurrentTime + added getMiddleTimeBetweenLines")

# 6. Add stopTime variable
old_vars = 'let isPlaying = false, startTime = 0, currentLine = 0, simulatedTime = 0;'
if old_vars in html:
    html = html.replace(old_vars, 'let isPlaying = false, startTime = 0, currentLine = 0, simulatedTime = 0, stopTime = 0;')
    patches += 1; ok("Added stopTime variable")

# 7. Modify stopPlayback
old_stop = 'function stopPlayback() {\n            if (!isPlaying) return;'
if old_stop in html:
    html = html.replace(old_stop, 'function stopPlayback() {\n            if (!isPlaying) return;\n            stopTime = currentTime; // v5: record stop time for render limit')
    patches += 1; ok("Modified stopPlayback")

# 8. Modify startPlaybackSync
old_start = 'function startPlaybackSync() {\n            if (isPlaying) return;'
if old_start in html:
    html = html.replace(old_start, 'function startPlaybackSync() {\n            if (isPlaying) return;\n            // v5: reset all module replays\n            if (window.LyraxLightning) window.LyraxLightning.resetReplay();\n            if (window.LyraxBrand) window.LyraxBrand.resetReplay();\n            if (window.LyraxFx) window.LyraxFx.resetReplay();\n            if (window.LyraxRain) window.LyraxRain.resetReplay();')
    patches += 1; ok("Modified startPlaybackSync")

# 9. Modify startCleanReRender
old_render = 'function startCleanReRender() {\n            if (isPlaying) { showToast("❌ ابتدا پخش را متوقف کنید"); return; }'
if old_render in html:
    html = html.replace(old_render, 'function startCleanReRender() {\n            if (isPlaying) { showToast("❌ ابتدا پخش را متوقف کنید"); return; }\n            // v5: محدود کردن رندر تا زمان توقف کاربر\n            let renderEndTime = stopTime || (audioFileObj ? audioElement.duration : 0) || 180;\n            let lastLyricEnd = 0;\n            if (lyricsTimeline.length > 0) {\n                lastLyricEnd = Math.max(...lyricsTimeline.map(l => l.end || 0));\n            }\n            renderEndTime = Math.min(renderEndTime, lastLyricEnd + 3);\n            if (renderEndTime <= 0) renderEndTime = 60;\n            showToast("🎬 رندر تا " + renderEndTime.toFixed(1) + "s");')
    patches += 1; ok("Modified startCleanReRender")

# 10. Add lightning/rain draw calls
old_draw = '// 🌊 رعدوبرق (دستی/خودکار)'
if old_draw in html and 'LyraxLightning' not in html[html.find(old_draw)-50:html.find(old_draw)+200]:
    html = html.replace(old_draw, '// 🌊 رعدوبرق v5 (ماژول LyraxLightning)\n            if (window.LyraxLightning) {\n                window.LyraxLightning.drawAll(offCtx, currentTime, W_FULL, H_FULL);\n            }\n            if (window.LyraxRain) {\n                window.LyraxRain.drawAll(offCtx, currentTime, W_FULL, H_FULL);\n            }\n            // 🌊 رعدوبرق قدیمی (fallback)')
    patches += 1; ok("Added lightning/rain draw calls")

# 11. Add auto-save + keyboard color fix
autosave_code = """\n\n        // ===== v5: ذخیره خودکار (Auto-Save) =====
        let autoSaveInterval = null;
        function startAutoSave() {
            if (autoSaveInterval) clearInterval(autoSaveInterval);
            autoSaveInterval = setInterval(function() {
                let projectName = document.getElementById('projectName').value || 'lyrax_project';
                let data = buildMasterProjectData();
                try {
                    localStorage.setItem('lyrax_autosave_' + projectName, JSON.stringify(data));
                    localStorage.setItem('lyrax_autosave_time', Date.now().toString());
                } catch(e) {}
            }, 10000);
        }
        function checkAutoSaveRecovery() {
            let projectName = document.getElementById('projectName').value || 'lyrax_project';
            let saved = localStorage.getItem('lyrax_autosave_' + projectName);
            if (saved) {
                let time = localStorage.getItem('lyrax_autosave_time');
                let dateStr = time ? new Date(parseInt(time)).toLocaleString('fa-IR') : 'نامشخص';
                if (confirm('🔁 پروژه ذخیره‌نشده یافت شد!\\n\\nآخرین ذخیره: ' + dateStr + '\\n\\nبرگردونم؟')) {
                    try { let data = JSON.parse(saved); loadProjectJSON(data); showToast('✅ پروژه از ذخیره خودکار بازیابی شد'); }
                    catch(e) { showToast('❌ خطا در بازیابی ذخیره خودکار'); }
                }
            }
        }
        window.addEventListener('load', function() { startAutoSave(); setTimeout(checkAutoSaveRecovery, 1500); });
        // فیکس رنگ صفحه‌کلید
        window.addEventListener('beforeunload', function() {
            document.documentElement.removeAttribute('style');
            document.body.style.backgroundColor = '';
            let meta = document.querySelector('meta[name="theme-color"]');
            if (meta) meta.content = '#0a0c0f';
        });
    """

last_script = html.rfind('</script>')
if last_script > 0 and 'startAutoSave' not in html:
    html = html[:last_script] + autosave_code + '\n    ' + html[last_script:]
    patches += 1; ok("Added auto-save + keyboard color fix")

# 12. Modify exportMasterProjectJSON
old_export = 'function exportMasterProjectJSON() {\n            let data = buildMasterProjectData();'
if old_export in html:
    html = html.replace(old_export, 'function exportMasterProjectJSON(download) {\n            if (download === undefined) download = true;\n            let data = buildMasterProjectData();\n            if (window.LyraxLightning) data.lightning_timeline = window.LyraxLightning.getTimelineEvents();\n            if (window.LyraxRain) data.rain_timeline = window.LyraxRain.getTimelineEvents();')
    patches += 1; ok("Modified exportMasterProjectJSON")

# 13. Modify buildMasterProjectData
old_build = 'function buildMasterProjectData() {\n            return {'
if old_build in html:
    html = html.replace(old_build, 'function buildMasterProjectData() {\n            let lightningData = window.LyraxLightning ? window.LyraxLightning.getTimelineEvents() : [];\n            let rainData = window.LyraxRain ? window.LyraxRain.getTimelineEvents() : [];\n            return { lightning_timeline: lightningData, rain_timeline: rainData,')
    patches += 1; ok("Modified buildMasterProjectData")

# 14. Modify loadProjectJSONFile
old_load = 'if (data.lyrics_timeline) {\n                    lyricsTimeline = data.lyrics_timeline;'
if old_load in html:
    html = html.replace(old_load, 'if (data.lyrics_timeline) {\n                    lyricsTimeline = data.lyrics_timeline;\n                    if (window.LyraxLightning && data.lightning_timeline) window.LyraxLightning.restore(data.lightning_timeline);\n                    if (window.LyraxRain && data.rain_timeline) window.LyraxRain.restore(data.rain_timeline);')
    patches += 1; ok("Modified loadProjectJSONFile")

# 15. Add rain checkbox
old_panel = '<label style="color:var(--text-muted); font-size:0.9rem; display:flex; align-items:center; gap:8px; cursor:pointer;">\n                            <input type="checkbox" id="lightningEnabled" onchange="updateLightningFromUI()" style="width:18px; height:18px; cursor:pointer;">\n                            فعال‌سازی جلوه‌ی رعدوبرق\n                        </label>'
if old_panel in html:
    html = html.replace(old_panel, old_panel + '\n                        <label style="color:var(--text-muted); font-size:0.9rem; display:flex; align-items:center; gap:8px; cursor:pointer; margin-top:6px;">\n                            <input type="checkbox" id="rainEnabled" onchange="updateRainFromUI()" style="width:18px; height:18px; cursor:pointer;">\n                            🌧️ باران همراه صاعقه (mood عاشقانه/غمگین)\n                        </label>')
    patches += 1; ok("Added rain checkbox")

# Write updated HTML
with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(html)
shutil.copy2(HTML_PATH, "studio.html")

ok(f"HTML patched: {patches} patches applied")
ok(f"Final size: {len(html)} bytes")

print("\n" + "="*50)
print(f"{G}  ✅ LyraX v5 Patch Complete!{NC}")
print("="*50)
print(f"{C}Backup:{NC} {backup_dir}/")
print(f"{C}Modules:{NC} static/js/modules/lyrax-lightning.js")
print(f"{C}         {NC} static/js/modules/lyrax-rain.js")
print(f"{C}HTML:{NC}    templates/index.html & studio.html")
print(f"\n{Y}🚀 Start with:{NC} python app.py")
