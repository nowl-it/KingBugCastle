<div align="center">
  <h1>🏰 King Bug Castle (KGC)</h1>
  <p><strong>A fully-featured Private Server & Reverse Engineering Toolkit for "King God Castle" (v170.1.00+)</strong></p>

  ![Python](https://img.shields.io/badge/Python-3.11+-blue.svg?style=flat&logo=python)
  ![FastAPI](https://img.shields.io/badge/FastAPI-0.103.1-009688.svg?style=flat&logo=fastapi)
  ![Reverse Engineering](https://img.shields.io/badge/Reverse_Engineering-IL2CPP-purple.svg?style=flat)
  ![Binary Patching](https://img.shields.io/badge/Patching-ARM64-red.svg?style=flat)
</div>

<br/>

> **⚠️ DISCLAIMER:** This is a fan-made, non-profit project created **strictly for educational, interoperability, and research purposes**. It is not affiliated with, endorsed by, or associated with Awesomepiece. The server-authoritative game logic is fully emulated locally. The client is only patched to bypass certificate pinning and local anti-cheat (XIGNCODE3) checks to allow for offline development and local traffic interception.

---

## 📖 Overview

**King Bug Castle** is an ambitious reverse-engineering project that reconstructs the entire backend API for the mobile game *King God Castle* (`com.awesomepiece.castle`). 

By dumping the IL2CPP metadata and intercepting network traffic, we have successfully mapped over **280+ REST API endpoints**, 400+ wire models, and recreated a local FastAPI server that fully emulates the `axis-game` infrastructure. This allows for complete offline gameplay, data manipulation (Gold, Gems, Levels), custom artifact testing, and deep-dive mechanics research without ever touching the live production servers.

## ✨ Core Features

* 🚀 **Full API Emulation**: A robust Python/FastAPI server replicating the exact behavior of `axis-game.awesomepiece.com` and `kgc-k8s-1.awesomepiece.com`.
* 🛡️ **Client Binary Patching (ARM64)**: Automated Python pipeline (`rebuild_arm64.py`) that patches `libil2cpp.so` to defeat SSL/TLS pinning and `CertificateHandler` checks.
* 👻 **XIGNCODE3 Bypass**: Emulates the Wellbia anti-cheat seed exchange (`/auth/xcdSeed`) to allow the client to boot without verification crashes.
* 🛠️ **`kgc-cli` Toolkit**: A proprietary command-line utility used for lightning-fast asset extraction, S3 CDN mirroring, and XML data diffing.
* 🗃️ **Hot-Reloading State**: Complete control over your account. Edit `state/player.json` or `data/*.json` to instantly manipulate currencies, decks, artifacts, and progression.

---

## 🗺️ Architecture & Workflow

```mermaid
graph TD
    Client[📱 Android Client / Emulator]
    FastAPI[⚡ Local FastAPI Server]
    CDN[📦 Local XML CDN]
    XIGNCODE[🛡️ Xigncode Stub]
    Data[(JSON Data & State)]

    Client -- "HTTPS (Bypassed TLS)" --> FastAPI
    Client -- "Fetch XML Updates" --> CDN
    FastAPI <--> Data
    Client <--> XIGNCODE
    
    style Client fill:#2D3748,stroke:#4A5568
    style FastAPI fill:#009688,stroke:#00796B
    style Data fill:#D69E2E,stroke:#B7791F
    style CDN fill:#3182CE,stroke:#2B6CB0
```

---

## 🧭 Documentation Hub

We have heavily documented the entire teardown and rebuild process. Depending on what you want to do, pick your path:

### 👨‍💻 For Backend Developers & Contributors
Want to spin up the local server, patch your own APK, and start modifying API responses?
👉 **Read the [Server Setup Guide & Workflow](server/README.md)**

### 🎮 For End-Users / Players
Did you just download the `.zip` release and want to know how to install it on your device/emulator?
👉 **Read the [Player Installation Guide](README_PLAYER.md)**

### 🧠 For Reverse Engineers
Want to understand how we dumped IL2CPP, mapped the 280+ routes, defeated SSL pinning, and how the S3 CDN delivers XML patches?
👉 **Read the [Knowledge Base & Teardown Notes](KNOWLEDGE.md)**

---

## 📂 Repository Layout

| Directory | Purpose |
| --- | --- |
| 📁 `server/` | The core FastAPI backend and automated ARM64 patching scripts (`rebuild_arm64.py`, `deploy.sh`). |
| 📁 `server/data/` | Static JSON models and response templates (Docs: [`server/data/README.md`](server/data/README.md)). |
| 📁 `api/` | Auxiliary integrations and external tool endpoints. |
| 📁 `scripts/` | Shell and Python automation scripts for fetching CDN data and extracting assets. |
| 📁 `xml_history/` | Historical staging area for live CDN XML bundles by patch date. |
| 📁 `il2cpp/` & `ghidra/` | Dumped metadata (`dump.cs`), string literals, and Ghidra project files. |
| 📁 `unity/` | Unity project files specifically created to repack `AssetBundles`. |
| ⚙️ `kgc-cli` | The core executable binary tool for data operations. |

---

## 🤝 Contributing

This project relies on continuous mapping as the game updates. If you find an unmapped route returning a `500` or an empty object, capture the real traffic using `mitmproxy`, find the matching model in `server/generated/models.json`, and add the override in `server.py` or `server/data/static_overrides.json`.
