# Corrected System Architecture: Local AI Workstation + M7 Agent Sandbox Server

## 1. System Topology & Separation of Concerns

### System A: Main Desktop (Inference & Client Hub)
* **Hardware:** Intel Core i9-14900K, 64GB DDR5, NVIDIA RTX 3070 Ti (8GB VRAM).
* **Primary Role:** High-speed local LLM inference (Ollama), voice STT/TTS (Whisper/Piper), desktop telemetry collection (ActivityWatch), native UI dashboard (Tauri), and physical hardware/display control (sim racing vs. bed TV modes).
* **Security Boundary:** Trusted host. No untrusted code executes here. 

### System B: M7 Server (Agentic Sandbox & Data Vault)
* **Hardware:** CPU, motherboard, RAM, and a hardware-attached 5TB external storage drive.
* **Primary Role:** Houses all sandboxed agent environments (Rocky, Jarvis, Mother, Skynet), runs background cron jobs, handles API ingest (Gmail, Drive, GitHub, Calendar), manages git repos, and executes code via containerized runtimes (Docker/k3s) with internet access.
* **Security Boundary:** Fully isolated sandbox network. If an agent writes flawed code or runs a destructive script, it is strictly contained within M7 containers and cannot touch your main desktop.

---

## 2. Core Functional Workflows

1. **Voice & Inference Flow:** User speaks to desktop -> Desktop runs local Whisper STT -> Desktop hits local LLM (Qwen2.5 on RTX 3070 Ti) -> LLM generates response/tool call -> If tool call requires data or code execution, desktop safely queries M7 Server API -> M7 executes task in sandbox -> Response streams back to desktop -> Local Piper TTS plays Rocky's voice.
2. **Nightly Data Aggregation:** Cron on M7 Server pulls daily logs (activity, GitHub repos, calendar, emails, Half Full DB) -> M7 processes and summarizes data -> M7 updates local vector database on the 5TB drive.
3. **Claude Code 2FA Lease Gate:** Jarvis wants to make code changes -> Sends FCM push notification to user's phone -> User approves -> Temporary 2FA token granted to M7 sandbox for a strict 20-minute window.

---

## 3. Host Operating System Requirements

### For the Main Desktop (Inference & UI Host)
* **NVIDIA CUDA & Driver Support:** First-class proprietary NVIDIA driver support for CUDA acceleration on the RTX 3070 Ti.
* **Display & Audio Control:** Must expose reliable CLI tools or APIs to automate multi-monitor display cloning/switching ("Movie Mode" vs. "Racing Mode") and PipeWire audio routing.
* **Telemetry & Idle Hooks:** Must support background daemons (ActivityWatch) and expose user idle states so heavy background tasks can pause when the desktop is actively in use.

### For the M7 Server (Sandbox & Storage Host)
* **Robust Container Runtime:** Native, high-performance support for Docker / Podman / lightweight Kubernetes (k3s) to manage multi-container agent sandboxes.
* **Filesystem & Mount Stability:** Reliable mounting, permissions management, and automated backup routines for the attached 5TB external drive.
* **Headless Stability:** Low-overhead Linux distribution optimized for 24/7 headless server uptime, cron management, and secure API gateways.