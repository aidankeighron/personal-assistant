# System Architecture & Host OS Requirements: Local Multi-Agent & Inference Workload

## 1. Project Overview
This workload is a locally hosted, multi-agent personal assistant and telemetry aggregation system that runs alongside daily desktop usage. The architecture splits duties between two machines:
* **Main Desktop (This Host):** Runs the GPU inference engine (LLMs, STT, TTS), active desktop telemetry trackers, a native dashboard UI, and local hardware/display control scripts.
* **Secondary Sandbox Server (M7):** Handles untrusted code execution, external API polling, cron-based nightly data aggregation, and attaches to a dedicated 5TB external storage drive.

All core services, agents, and Model Context Protocol (MCP) servers are heavily containerized to maintain strict isolation from the host filesystem.

---

## 2. Host Hardware Profile (Main Desktop)
* **CPU:** Intel Core i9-14900K (Hybrid P-core / E-core architecture)
* **GPU:** NVIDIA GeForce RTX 3070 Ti (8GB VRAM)
* **RAM:** 64GB DDR5 (Host must retain 30–40GB minimum for primary desktop tasks; up to 24–30GB available for containerized workloads during idle/nightly windows)
* **Peripherals & I/O:** Multiple displays (desktop monitors, secondary TVs/projector), USB audio/microphone inputs, and sim racing/controller peripherals.

---

## 3. Core Technical Requirements for the Host OS

### A. Containerization & GPU Passthrough
* **Container Runtime:** Heavy reliance on Docker, Podman, or lightweight Kubernetes (k3s) to orchestrate microservices (Ollama/vLLM, Whisper STT, Piper/XTTS, Vector DB, MCP servers).
* **NVIDIA Container Toolkit:** Must have first-class, low-overhead support for passing the RTX 3070 Ti (`nvidia-container-toolkit` / CDI) into multiple containers simultaneously without VRAM leaks or driver version mismatches.
* **Low Orchestration Overhead:** If Kubernetes is used, the control plane must not consume excessive CPU/RAM during daytime interactive desktop use.

### B. Display Server & Multi-Monitor Automation
* **Programmatic Display Switching:** The host must support instant, scriptable display topology changes (toggling specific TVs/projectors on/off, duplicating outputs for "Movie Mode" vs. "Racing Mode", and adjusting primary displays) via CLI or local API.
* **Audio Routing:** Must support programmatic switching of default audio sinks/sources (PipeWire / WirePlumber) when switching between desktop, bed TV, and racing rig profiles.

### C. Desktop Telemetry & Idle Detection
* **Window & Application Tracking:** Must allow a local telemetry daemon (e.g., ActivityWatch) to read active window titles and process names.
* **Idle Time Detection:** The host OS must expose user idle time (mouse/keyboard inactivity) to a local scheduler daemon so heavy GPU/RAM workloads only trigger when the desktop is AFK or during scheduled 5:00 AM batch windows.

### D. Kernel & Hardware Considerations
* **Linux Kernel 6.6+ Recommended:** Required for proper Intel Thread Director (i9-14900K P/E-core) scheduling so background container threads can be pinned to E-cores while keeping P-cores free for interactive/low-latency workloads.
* **Proprietary NVIDIA Drivers:** Needs reliable, up-to-date proprietary NVIDIA driver packaging (550+ series) for CUDA 12+ compatibility and Vulkan/NVENC support.

---

## 4. OS Constraint Matrix (Factors for Distro Selection)

### Factors Leaning Toward Specific Distro Families
* **Debian / Ubuntu-based (e.g., Ubuntu LTS, Pop!_OS, Debian):**
  * *Pros:* Official target for NVIDIA CUDA repositories and `nvidia-container-toolkit`; zero friction with Docker/k3s packages.
  * *Watchouts:* Older LTS kernels may underutilize 14th-gen Intel thread scheduling unless using an updated HWE kernel.
* **Fedora / RHEL-based (e.g., Fedora Workstation, Nobara, Silverblue/Bazzite):**
  * *Pros:* Ships with newer kernels, modern PipeWire audio, and native Podman integration; immutable variants (Silverblue/Bazzite) align well with a purely containerized workflow.
  * *Watchouts:* SELinux policies and `nvidia-container-toolkit` require explicit configuration for container device passthrough (`--security-opt label=disable` or CDI setup).
* **Arch-based (e.g., Arch, EndeavourOS, CachyOS):**
  * *Pros:* Bleeding-edge kernels and NVIDIA drivers; instant access to AUR packages for niche hardware/display utilities.
  * *Watchouts:* Rolling-release kernel updates can occasionally break `nvidia-dkms` or container runtime modules if unattended nightly updates are enabled.

### Critical Compatibility Friction Points to Resolve
1. **Wayland vs. X11:**
   * **Wayland** offers superior multi-monitor refresh rate handling and modern security isolation, *but* strict Wayland compositors block global window-title tracking (breaking ActivityWatch) and complicate idle detection unless compositor-specific extensions (e.g., KDE KWin scripts, Hyprland IPC, or GNOME extensions) are used.
   * **X11** makes window tracking (`xprop`/`wmctrl`), idle detection (`xprintidle`), and display switching (`xrandr`) trivial across all distros, but struggles with mixed-DPI / mixed-refresh-rate multi-monitor setups.
   * *Note for Decision Agent:* Whatever desktop environment/compositor is chosen must provide a CLI tool (like `kscreen-doctor` on KDE, `hyprctl` on Hyprland, or `xrandr` on X11) to automate display profiles and expose active window metadata.
2. **Docker/Podman vs. Kubernetes (k3s/k8s) for GPU Sharing:**
   * Standard Kubernetes enforces whole-GPU allocation per pod unless the NVIDIA GPU Operator with Time-Slicing or MPS (Multi-Process Service) is configured.
   * If this AI stack and another GPU-accelerated container (e.g., a containerized emulator system) run concurrently, the container runtime must either use **NVIDIA Time-Slicing** in k3s or run via **Docker Compose / Podman** where multiple containers can share `/dev/nvidia0` natively on demand.