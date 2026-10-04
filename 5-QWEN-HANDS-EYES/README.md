# Qwen-Hands-Eyes (SkyGround OS v2.5)
### Autonomous Offline AI Agent with Dual-Brain Orchestration, Eyes (Vision), Hands (OS Automation), and Feet (Mobile API Gateway)

Qwen-Hands-Eyes is a modular, parametric, offline-first personal autonomous agent framework designed to orchestrate local LLMs (Qwen 2.5 + DeepSeek R1) with system perception, safety gates, desktop automation, and mobile device connectivity.

## Features
- **Dual-Brain Router:** Qwen front orchestrator + DeepSeek R1 deep reasoning engine with prompt translation and `<think>` trace visualization.
- **Eyes (Vision):** High-speed screen capture, multi-monitor support, VLM grounding, and visual element locator.
- **Hands (Automation):** Mouse/keyboard controller with Unicode clipboard safety, sandboxed shell execution, atomic file editor with diff preview.
- **Feet (Mobile Gateway):** Standard REST & WebSocket server for Android mobile apps with Static IP / LAN auto-discovery.
- **DSA Memory Retention:** SQLite episodic memory engine powered by Fade-Not-Forget dynamics ($\lambda=0.15, \gamma=0.4, w_{min}=0.15$).

## Quickstart
```bash
# Install dependencies
pip install -r requirements.txt

# Start agent & dashboard on port 8765
python main.py --config config/config.json --port 8765
```

Open dashboard at `http://localhost:8765`.
