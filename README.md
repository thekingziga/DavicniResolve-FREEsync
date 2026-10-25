# 🎬 ResolveSync: DaVinci Resolve Universal Media & Project Sync

[![Release](https://img.shields.io/github/v/release/thekingziga/DavicniResolve-FREEsync?color=6366f1&label=Release&logo=github)](https://github.com/thekingziga/DavicniResolve-FREEsync/releases)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20(Apple%20Silicon%20%26%20Intel)-0284c7.svg)]()
[![DaVinci Resolve](https://img.shields.io/badge/DaVinci%20Resolve-Free%20%26%20Studio%20(18%2F19)-ea580c.svg)]()
[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.14-10b981.svg)]()
[![License](https://img.shields.io/badge/License-MIT-gray.svg)](LICENSE)

> **All the collaboration power of Blackmagic Cloud—100% Free, Private, and Self-Hosted on your own TrueNAS or local edit storage.**

**ResolveSync** is an open-source media synchronization and path-mapping ecosystem designed specifically for **DaVinci Resolve** (both **Free** and **Studio** editions). It bridges editing workstations across **Windows** and **macOS** with your central **TrueNAS SCALE / NAS server**, providing automated proxy synchronization, project database extraction, and seamless cross-platform path translation.

---

## ⚡ Why ResolveSync?

Blackmagic Cloud and DaVinci Resolve Studio offer cloud project libraries and presentation tools, but paid subscriptions ($5/month/library) add up, and DaVinci Resolve Free normally limits remote collaboration and scripting APIs.

**ResolveSync solves this by:**
1. **Working with DaVinci Resolve FREE & Studio:** No Studio license or dongle is required to inspect project media or sync clips.
2. **TrueNAS & NAS Centric:** Uses your existing local Gigabit / 10GbE network or remote WAN (DDNS / WireGuard) without monthly fees.
3. **Blackmagic Cloud Proxy Parity:** Syncs lightweight proxies (`_Proxy.mov`, ProRes / H.264) in seconds for editing on MacBook or travel laptop, while keeping massive 4K/8K/RAW camera originals safely on the NAS until color finishing.
4. **Auto-Resolving "Media Offline" Between Mac and PC:** Directly inspects and updates DaVinci Resolve's internal preference files (`.config.data` and `config.dat`), eliminating the dreaded red offline clip badges without manual relinking.

---

## ✨ Features at a Glance

| Feature | Description |
| :--- | :--- |
| ⚡ **Proxy-Only Syncing** | Sync only lightweight proxy clips to edit on laptops with 90% disk savings; easily pull RAW originals when grading. |
| 🔍 **Companion Proxy Auto-Discovery** | Automatically discovers companion proxies created by DaVinci Resolve (`Proxy/` subfolders or `_Proxy` naming), even though DaVinci Free doesn't record separate entries for proxies in PostgreSQL. |
| ⏹️ **Immediate Cancellation** | Stop transfers instantly (<1ms) without hanging on multi-gigabyte files; automatically cleans up stale partial `.part` files. |
| 🚀 **High-Speed Lag-Free Engine** | Throttled UI redraws (~12 FPS) and 2MB streaming buffers prevent GUI freezes during 100MB/s+ file transfers. |
| 🗄️ **Direct PostgreSQL Project Reader** | Connects directly to DaVinci PostgreSQL Project Libraries (e.g. TrueNAS Docker or BM Project Server) and extracts all media paths via binary Protobuf parsing—bypassing the need for DaVinci Resolve Studio. |
| 📋 **Selective Download Picker** | Review project footage before downloading: pick specific clips, search by filename, or 1-click select missing proxies or originals. |
| 🗺️ **DaVinci Mapped Mounts Assistant** | Reads and repairs DaVinci preference files on Windows and macOS, correcting trailing slashes and mapping drives (`D:\` $\leftrightarrow$ `/Users/...`). |
| 🎬 **Direct DaVinci Launcher** | Launch DaVinci Resolve directly from the app; automatically prompts to open your project and relink media right after synchronization completes. |
| 🔑 **1-Click `.resolvedbkey` Importer** | Drop or browse your DaVinci Resolve database key to auto-configure PostgreSQL host, database name, and credentials with LAN/WAN fallback. |
| 👑 **About Žiga (@thekingziga)** | Interactive creator tab featuring **Žiga Vodnjov Frelih** with direct links to YouTube (@zigavf), website (thekingziga.com), Twitch, and GitHub. |
| 🐛 **Toggleable Debug Logs** | Default clean logging (`INFO`/`ERROR` only) with instant live toggle for detailed `DEBUG` diagnostics. |
| 🖥️ **Native Desktop Applications** | Real Windows Setup installer (`.exe`), zero-install portable Windows package (`.zip`), and native Apple Silicon Mach-O `arm64` macOS application bundle (`.app`). |

---

## 🏗️ Architecture

```mermaid
flowchart LR
    subgraph TrueNAS["TrueNAS / Central Storage Server"]
        Hub["ResolveSync Hub (Docker / Flask)<br/>Port 5000"]
        PG["DaVinci Project Server<br/>(PostgreSQL 5432)"]
        PoolMedia["Central Storage Pool<br/>(/media)"]
        Hub --> PoolMedia
    end

    subgraph WinEdit["Windows Workstation"]
        WinApp["ResolveSync.exe (v1.2.0)"]
        DaVinciWin["DaVinci Resolve (Free/Studio)"]
        WinStorage["Local SSD (D:\DAVINCI)"]
        WinApp <--> DaVinciWin
        WinApp --> WinStorage
    end

    subgraph MacEdit["MacBook / Mac Studio (Apple Silicon)"]
        MacApp["ResolveSync.app (v1.0.0)"]
        DaVinciMac["DaVinci Resolve (Free/Studio)"]
        MacStorage["Local SSD (~/Movies/DaVinci Resolve)"]
        MacApp <--> DaVinciMac
        MacApp --> MacStorage
    end

    WinApp <== "HTTP Batch Stat & SFTP Transfer" ==> PoolMedia
    MacApp <== "HTTP Batch Stat & SFTP Transfer" ==> PoolMedia
    WinApp <.. "Direct Project Inspection" ..> PG
    MacApp <.. "Direct Project Inspection" ..> PG
```

---

## 🚀 Quickstart & Downloads

### Download Pre-Compiled Desktop Apps

Get the latest ready-to-run releases from the [**Releases Page**](https://github.com/thekingziga/DavicniResolve-FREEsync/releases):

- **Windows 10 / 11 (64-bit) Installer:** Download [`ResolveSync_Setup_v1.2.exe`](https://github.com/thekingziga/DavicniResolve-FREEsync/releases/latest) (Real Windows Setup wizard, Start Menu & Desktop shortcuts, clean uninstaller).
- **Windows Portable ZIP:** Download [`ResolveSync_Windows_v1.2.zip`](https://github.com/thekingziga/DavicniResolve-FREEsync/releases/latest) (Self-contained portable archive, extract and run anywhere).
- **macOS (Apple Silicon M1 / M2 / M3 / M4 & Intel):** Download [`ResolveSync_Mac_v1.1.zip`](https://github.com/thekingziga/DavicniResolve-FREEsync/releases/latest), unzip, and drag `ResolveSync.app` into `/Applications`.

### Or Run from Source

```bash
# Clone the repository
git clone https://github.com/thekingziga/DavicniResolve-FREEsync.git
cd DavicniResolve-FREEsync

# Install requirements
pip install -r requirements.txt

# Launch GUI on Windows or macOS
python desktop_app.py
```

---

## 🎬 Editing Workflows

### 🏎️ Travel & Laptop Workflow (Proxies Only)
1. Open **ResolveSync** and choose your active PostgreSQL project or `.drp` archive.
2. Under **Media Content**, select **⚡ Proxies Only (Fast)**.
3. Click **`🚀 Start Sync`** (or pick files via **`📋 Select Files...`**).
4. Missing proxy clips download rapidly over Wi-Fi.
5. In the post-sync dialog, click **🎬 Launch DaVinci Resolve**.
6. In DaVinci Resolve, verify **Playback $\rightarrow$ Proxy Handling $\rightarrow$ Prefer Proxies** is checked. Edit seamlessly with zero lag!

### 🎨 Finishing & Color Grading (Originals Only)
1. On your studio color grading workstation, open **ResolveSync**.
2. Select **🎥 Camera Originals Only** (or **🎬 All Media**).
3. Click **`🚀 Start Sync`** to fetch high-bitrate RAW/ProRes camera originals.
4. In DaVinci Resolve, toggle **Playback $\rightarrow$ Proxy Handling $\rightarrow$ Disable Proxies**. DaVinci immediately displays full-fidelity master media for color grading and final master export!

---

## 🗺️ Cross-Platform Path Mapping (Windows $\leftrightarrow$ Mac)

To share projects between Windows and macOS without relinking:

| Workstation OS | Remote Mount (Project Path) | Local Mount (Workstation Folder) |
|---|---|---|
| **macOS Workstation** | `D:\` (or `D:/`) | `/Users/<user>/Movies/DaVinci Resolve/D/` |
| **Windows Workstation** | `/Users/` | `D:\DAVINCI\Users\` |

> **1-Click Assistant:** ResolveSync includes a built-in **🗺️ Mapped Mounts Assistant** that reads DaVinci's `.config.data` and `config.dat` files, detects trailing slash issues, and automatically writes the exact mapped mount paths with a single click.

---

## 🐳 TrueNAS SCALE Hub Deployment

Deploy the lightweight HTTP/SFTP hub container on TrueNAS or Linux:

```yaml
# docker-compose.yml
services:
  resolvesync-hub:
    build: .
    container_name: resolvesync-hub
    restart: unless-stopped
    ports:
      - "5000:5000"
    volumes:
      - /mnt/tank/media:/media:rw
      - ./config.json:/app/config.json:ro
```

Run:
```bash
docker compose up -d
curl http://<TRUENAS_IP>:5000/api/health
```

---

## ⚙️ Configuration (`config.json`)

ResolveSync can be configured via the in-app **⚙️ Settings** modal or by creating a `config.json` file (see [`config.example.json`](config.example.json)):

```json
{
  "server": {
    "server_url": "http://192.168.1.100:5000",
    "host": "http://192.168.1.100:5000"
  },
  "postgres": {
    "enabled": true,
    "host": "192.168.1.100",
    "port": 5432,
    "user": "postgres",
    "password": "YOUR_PASSWORD",
    "dbname": "main"
  },
  "sync_root_folder": "D:\\DAVINCI",
  "sync_options": {
    "auto_map_unmatched": true,
    "confirm_sync_scope": true,
    "prompt_launch_davinci": true
  }
}
```

---

## 📜 Changelog

All versions from `v0.1.0` through `v1.2.0` are documented in detail in [**CHANGELOG.md**](CHANGELOG.md).

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
DaVinci Resolve and Blackmagic Design are registered trademarks of Blackmagic Design Pty. Ltd. ResolveSync is an independent open-source project and is not affiliated with Blackmagic Design.
