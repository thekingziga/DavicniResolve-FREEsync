# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.2.0] - 2026-10-25 - Real Windows Installer (Setup .exe), Portable ZIP & Application Icon

### Added
- **Full Windows Setup Installer (`ResolveSync_Setup_v1.2.exe`)**:
  - Built with Inno Setup 6 featuring modern wizard styling and LZMA2 ultra solid compression.
  - Installs cleanly into standard User Program Files (`%LOCALAPPDATA%\Programs\ResolveSync`) requiring no administrator UAC prompt.
  - Automatically creates Start Menu and optional Desktop shortcuts with the custom application icon.
  - Registers full Windows uninstallation support with Control Panel / "Apps & Features" integration.
  - Includes post-installation option to launch ResolveSync immediately upon setup completion.
- **Portable Windows ZIP Package (`ResolveSync_Windows_v1.2.zip`)**:
  - Self-contained, zero-install portable release archive for USB drives, portable setups, or environments without installer privileges.
  - Bundles `ResolveSync.exe`, `config.example.json`, `README.md`, `LICENSE`, and `app_icon.ico`.
- **Custom Application Icon & Visual Identity**:
  - High-resolution multi-size icon (`app_icon.ico` supporting 16x16, 32x32, 48x48, 64x64, 128x128, and 256x256 formats) featuring modern DaVinci Resolve colorway palette (cyan/indigo/amber) with synchronization arrows.
  - Embedded directly into compiled Windows executable binary, application taskbar window, and installer package.
  - High-res 512x512 PNG master asset (`app_icon.png`) for documentation and packaging.

---

## [1.1.0] - 2026-10-24 - Immediate Cancel, Performance Boost, Creator Info & Debug Toggle

### Added
- **Instant Synchronization Cancellation**:
  - `[⏹️ Cancel]` button now halts active file transfers immediately (<1ms) rather than waiting for large multi-GB files to finish.
  - Added chunk-level cancellation checks (`SyncCancelledError`) inside HTTP chunked download streams, upload chunk readers, and SFTP callbacks.
  - Automatically cleans up and removes incomplete `.part` temporary files on local disk and remote storage upon cancellation.
  - Instant UI feedback changing cancel button to "Stopping..." and updating status labels immediately.
- **High-Throughput Transfer Performance & UI Throttling**:
  - Fixed application freezing and sluggishness during upload/download by throttling GUI progress updates to ~12.5 FPS (every 80ms), completely preventing event loop congestion.
  - Upgraded HTTP streaming buffer to 2MB for smooth high-speed disk I/O on 1GbE / 10GbE local networks.
  - Throttled upload stream reader callbacks to avoid generating hundreds of thousands of GUI redraw events on large files.
- **Dedicated "About Žiga (@thekingziga)" Creator Tab & Header Shortcut**:
  - Brand new interactive profile tab honoring creator **Žiga Vodnjov Frelih** (online alias: **thekingziga** / **TheKingZiga**), video editor, software developer, and homelab enthusiast from Domžale, Slovenia.
  - Documents the project's founding story: bringing Blackmagic Cloud parity to DaVinci Resolve Free and Studio without recurring monthly fees.
  - 1-Click interactive launch buttons for verified online channels:
    - 🌐 Website: [thekingziga.com](https://www.thekingziga.com)
    - 🐙 GitHub: [@thekingziga](https://github.com/thekingziga)
    - 📺 YouTube: [@zigavf](https://www.youtube.com/@zigavf)
    - 🎮 Twitch: [thekingziga](https://www.twitch.tv/thekingziga)
  - Homelab & tech architecture overview (Proxmox VE, TrueNAS SCALE, Docker, pfSense, 10GbE storage pool).
  - One-click `[👑 About Žiga]` shortcut button in the main application top bar.
- **Configurable Debug Logging (Default: OFF)**:
  - Added `Debug Logs` switch directly in the console header to toggle verbose debug logging on and off at runtime.
  - Defaults to **OFF** (standard `INFO` and `ERROR` logs only), preventing console and log file spam.
  - Persistent preference saved in `config.json` (`"debug_logging": false`).
  - Added `[🧹 Clear]` and `[📄 Open File]` quick-action buttons in the console header.

---

## [1.0.0] - 2026-10-24 - Production Release (Windows & macOS)

### Added
- **Direct DaVinci Resolve Launcher**:
  - One-click `[🎬 Open DaVinci]` buttons in the top navigation bar and sync control center.
  - Automatic cross-platform application discovery (`open -a "DaVinci Resolve"` on macOS; candidate lookup in `%PROGRAMFILES%\Blackmagic Design\DaVinci Resolve\Resolve.exe` on Windows).
  - Optional project opening directly into the active `.drp` archive.
- **Post-Sync Launch Modal Dialog (`PostSyncLaunchDialog`)**:
  - Automatically prompts user upon sync completion: *"Sync Complete! Would you like to open DaVinci Resolve now to start editing?"*
  - Instant one-click launch with seamless background relinking.
- **Proxy-Only & Selective Media Synchronization (DaVinci Cloud Parity)**:
  - Three user-selectable sync modes:
    1. **🎬 All Media (Both)**: Synchronizes full-resolution camera originals and proxies.
    2. **⚡ Proxies Only (Fast)**: Syncs only proxy media files (`_Proxy.mov`, `Proxy/` subfolders, ProRes/H.264 offline media) for lightning-fast transfers over remote Wi-Fi and laptop editing.
    3. **🎥 Camera Originals Only**: Synchronizes high-resolution RAW and master footage, skipping proxies.
  - Automatic DaVinci Companion Proxy Discovery:
    - Automatically discovers local companion proxies generated by DaVinci Resolve (in `Proxy/`, `Proxies/`, `ProxyMedia/`, or adjacent `<stem>_proxy.<ext>`) even though DaVinci does not write separate records for proxies in PostgreSQL `Sm2MpMedia`.
    - Queries TrueNAS remote candidate proxy paths via batch `/api/media/check`, enabling seamless bidirectional proxy discovery between Windows PC and macOS.
  - Dedicated media breakdown stats displaying proxy vs. original file counts and byte sizes.
- **Selective Sync & Pre-Sync Scope Selection Dialog (`SyncScopeDialog` & `FileSelectionModalDialog`)**:
  - Pre-sync prompt asking whether to transfer all missing files or hand-pick specific items before starting.
  - "Always sync everything" preference option to bypass the dialog if desired.
  - Interactive file selection modal featuring:
    - Real-time filename / path search filter.
    - Quick-select filter pills (*Select All, Deselect All, ⚡ Proxies Only, 🎥 Originals Only, ⬇️ Needs Download, ⬆️ Needs Upload*).
    - Status badges, file sizes, and selected transfer byte tally.
  - Dedicated `[📋 Select Files...]` toolbar button for immediate selective syncing.
- **Spacious & De-cluttered Modern Dark UI**:
  - Segmented Project Source Selector: cleanly toggles between **🗄️ Network Database (PostgreSQL)**, **⚡ Live DaVinci Resolve**, and **📁 DRP Archive File** without vertical clutter.
  - Prominent Active Project banner displaying current project name, backend source, and media clip counts.
  - Increased window default geometry to `1180x860` with responsive card padding and crisp typography.
  - Visual release badge (`v1.0.0`) and operating system pill (`WINDOWS` / `MACOS`).
- **Native Apple Silicon macOS Application Bundle (`ResolveSync.app`)**:
  - Compiled native Mach-O `arm64` application bundle built with Python 3.14 + Tkinter 9.0 + CustomTkinter.
  - High-DPI Retina display support with native macOS window chrome and Dock icon.
  - Sandboxed configuration stored in `~/Library/Application Support/ResolveSync/config.json`.
  - Debug logs streamed to `~/Library/Logs/ResolveSync/resolvesync_debug.log`.

### Changed
- Refactored `desktop_app.py` UI layout to eliminate vertical cramming, grouping action buttons into intuitive cards.
- Default download folder now auto-configures to `D:\DAVINCI` on Windows and `~/Movies/DaVinci Resolve/D/` on macOS.

---

## [0.9.0] - 2026-10-24 - macOS Support & Mapped Mount Engine

### Added
- **DaVinciPreferencesManager**:
  - Reads and writes DaVinci Resolve `.config.data` and `config.dat` preference files directly.
  - Supports both Windows (`%APPDATA%\Blackmagic Design\DaVinci Resolve\Preferences`) and macOS (`~/Library/Preferences/Blackmagic Design/DaVinci Resolve`).
  - Automatic trailing slash bug detection and 1-click auto-fix (resolving `D:\DAVINCI\Root\Users\ziga` vs `/Users/ziga/` path truncations).
  - Preserves system `/Volumes` mounts and MacDIO preferences.
- **Cross-Platform Mapped Mounts Assistant**:
  - Visual modal assistant recommending exact mapped mount configurations for Windows <-> Mac interoperability.
  - Real-time status badges (`OK`, `MISSING`, `SLASH_MISMATCH`, `NOT_CONFIGURED`).

### Fixed
- Fixed Tkinter import failure on macOS by bundling Tcl/Tk 9.0 runtimes.
- Fixed Unicode cp1250 console crash on Windows when logging Unicode emojis.

---

## [0.8.0] - 2026-10-24 - PostgreSQL Project Server & .resolvedbkey

### Added
- **Direct DaVinci Project Server Integration**:
  - Native PostgreSQL connector querying project hierarchies without requiring DaVinci Resolve Studio.
  - Queries `Sm2MediaPool`, `Sm2MpFolder`, `Sm2MpMedia`, and `BtVideoInfo` / `BtAudioInfo` tables.
  - High-performance binary Protobuf regex parser extracting absolute file paths from raw `Clip` blobs.
- **1-Click `.resolvedbkey` Credential Importer**:
  - Decodes base64-encoded Blackmagic project database connection tokens.
  - Auto-extracts hostname, port, database name, username, and password into `config.json`.
  - Automatic fallback between local IP (`192.168.x.x`) and public WAN/DDNS domain (`thekingziga.com`).

---

## [0.7.0] - 2026-10-23 - First-Time Onboarding & Auto-Discovery

### Added
- **First-Time Sync Guidance Dialog**:
  - Interactive onboarding prompt allowing user to choose their media download drive/folder on initial sync.
  - "Remember my choice" persistence.
- **Interactive In-App DaVinci Setup Guide**:
  - Embedded setup guide covering Mapped Mounts, remote editing setups, and step-by-step workflow tutorials.

---

## [0.6.0] - 2026-10-23 - Zero-Configuration Auto-Mapping

### Added
- **Filename Substring & Drive Auto-Mapper**:
  - Eliminates the need for manual path translation rules for projects sharing standard directory structures.
  - Automatically reconstructs drive-letter hierarchies (`D:\...` mapped to `DownloadFolder/D/...`).
  - Gracefully ignores missing rules, defaulting to intelligent mirror sync.

---

## [0.5.0] - 2026-10-22 - TrueNAS SCALE HTTP Hub Engine

### Added
- **TrueNAS SCALE Docker Container**:
  - Lightweight Python 3 Flask microservice (`web_server.py`) with chunked file uploads and streaming downloads.
  - `/api/sync/check-batch` endpoint checking existence, sizes, and timestamps of hundreds of clips in a single HTTP request (<50ms).
  - SHA-256 integrity verification.
- **Deployment Automation**:
  - Automated `deploy_truenas.sh` script packaging `docker-compose.yml` and container assets.

---

## [0.4.0] - 2026-10-22 - Live DaVinci Resolve Scripting API

### Added
- **DaVinci Resolve IPC Discovery**:
  - Scans system for running `Resolve.exe` / `DaVinci Resolve` processes.
  - Dynamic loading of Blackmagic `fusionscript.dll` / `fusionscript.so`.
  - Traverses active Media Pool bins, timelines, and clips in memory.

---

## [0.3.0] - 2026-10-22 - Standalone Windows Executable

### Added
- PyInstaller automated packaging script `build_windows_app.py`.
- Generates single-file standalone executable `ResolveSync.exe`.
- Bundled default dark-theme assets and default configuration fallback.

---

## [0.2.0] - 2026-10-21 - DRP Project Archive Parser

### Added
- **DRPParser Engine**:
  - Direct ZIP archive decompression of `.drp` DaVinci Resolve Project files.
  - XML parsing of `project.xml` supporting all known media path tags (`filePath`, `clippath`, `sourcefilepath`, etc.).
  - Filters out DaVinci temporary files, render caches (`.dvcc`, `.dtl`), and database files.

---

## [0.1.0] - 2026-10-21 - Initial SFTP Synchronizer

### Added
- Core bidirectional SFTP synchronization engine (`resolvesync.py`).
- JSON configuration schema (`config.json`) with prefix-based path translation rules.
- Command-line interface with `--analyze`, `--sync`, `--download`, and `--dry-run` modes.
- Transfer progress callbacks with transfer speed calculation.
