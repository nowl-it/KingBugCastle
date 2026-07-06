# King Bug Castle (KGC) - Reverse Engineering & Private Server

Welcome to the **King Bug Castle** repository. This project focuses on reverse-engineering the Unity IL2CPP game "King God Castle" (`com.awesomepiece.castle`) to build a fully functional, offline-capable private server for research and interoperability testing.

> **Disclaimer**: This is a fan-made project for educational and research purposes only. Not affiliated with Awesomepiece. Server-authoritative logic is emulated locally; the client is patched only to bypass certificate pinning and anti-cheat checks for local development.

## 🚀 Where to Start?

Depending on your role, head to the appropriate documentation:

- **👨‍💻 For Developers (Setting up the repo)**:
  Start at **[`server/README.md`](server/README.md)**. It contains the complete guide on installing prerequisites, obtaining the required base APKs, running the server, and building the patched client.

- **🎮 For Players (Running the pre-packaged zip)**:
  If you received a pre-built `.zip` release, read **[`README_PLAYER.md`](README_PLAYER.md)** for instructions on how to install the APKs and configure your device's `hosts` file to connect to the server.

- **🧠 For Reverse Engineering Research**:
  Check out **[`KNOWLEDGE.md`](KNOWLEDGE.md)** for in-depth findings on the game's architecture, data structures, and CDN mechanics.

## 📂 Repository Structure

Below is a high-level overview of the main directories in this repository:

- `server/`: The core FastAPI backend emulator and build scripts (`deploy.sh`, `rebuild_arm64.py`). **(Start your development here)**
- `api/`: Auxiliary APIs and integrations.
- `scripts/`: Various utility scripts for data extraction and automation.
- `xml_history/` & `scratchpad/`: Staging areas for live CDN XML bundles and temporary patching files.
- `apk/`: *(Git-ignored)* Directory where you must place the original game APKs for the build scripts to work.
- `il2cpp/` & `ghidra/`: IL2CPP dumps and Ghidra project files for static analysis.
- `unity/`: Unity project templates for asset bundle extraction/repacking.

## 🛠️ Tech Stack

- **Backend Emulator**: Python, FastAPI, Uvicorn
- **Client Patching**: LIEF, apktool, apksigner, Python scripts
- **Binary Analysis**: Ghidra, Il2CppDumper
