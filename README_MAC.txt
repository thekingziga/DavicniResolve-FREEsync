=================================================================
ResolveSync for macOS & Windows - DaVinci Resolve Universal Guide
=================================================================

1. Running the Application on macOS
-----------------------------------
Option A (Recommended): Double-click "ResolveSync.app" or "ResolveSync_Mac.command".
Option B: Run in Terminal:
    python3 desktop_app.py

Features available on Mac:
  • 🔄 Two-Way Sync: Uploads new media from Mac to TrueNAS AND pulls missing clips.
  • ⬆️ Push to NAS: Uploads newly recorded or edited clips from Mac to TrueNAS.
  • ⬇️ Pull from NAS: Downloads missing clips from TrueNAS directly to Mac / SSD.
  • ⚡ Live DaVinci Resolve: Auto-detects your active open project with 1 click.
  • 📋 Recent Projects: Auto-discovers projects from PostgreSQL Network servers & disk.
  • 📁 DRP Project Archive: Works with any exported .drp or .zip project file.
  • 💡 In-App Tips: Complete step-by-step Mapped Mounts walkthrough built right in.


2. How "Mapped Mounts" Works in DaVinci Resolve (Zero-Relink Guarantee)
----------------------------------------------------------------------
When projects are created on Windows, footage paths are recorded with Windows
drive letters (e.g. "D:\Users\zigav\Videos\take1.mp4").

Instead of manually relinking clips every time you switch between Mac and PC,
DaVinci Resolve has a feature called "Mapped Mounts" that dynamically maps paths
in memory so all clips stay 100% ONLINE on every machine!


3. Exact Setup for Every Device
-------------------------------

A. On macOS (MacBook, Mac Studio, Mac Pro, External SSD)
   1. Open DaVinci Resolve on your Mac.
   2. Open Preferences: Press [Cmd + ,] (or DaVinci Resolve menu -> Preferences...).
   3. In the left sidebar, click "Media Storage".
   4. Scroll to the "Mapped Mounts" section at the bottom and click "+ Add":
      • Mapped Mount (Remote):  D:\
      • Local Mount (Mac):     /Volumes/YourSSD/D/   (or ~/Movies/ResolveSync/D/)
   5. Click "Save". Reopen your project.
   --> BAM! All clips link instantly and stay permanently online!

B. On Main Windows Workstation
   • If footage was originally placed on D:\, no mapping is needed.
   • If viewing files stored on TrueNAS via SMB directly:
     Local Mount: D:\  <--->  Remote Mount: \\192.168.1.3\media\D\

C. For Remote Editors (Windows or Mac)
   1. The editor downloads ResolveSync, enters your TrueNAS Hub URL (or VPN),
      and sets their local drive as the "Download To:" folder (e.g. E:\Footage).
   2. In DaVinci Resolve -> Preferences -> Media Storage -> Mapped Mounts:
      • Mapped Mount (Remote):  D:\
      • Local Mount (Editor):  E:\Footage\D\  (or /Volumes/EditorSSD/D/ on Mac)
   3. The editor can now collaborate over your PostgreSQL Network Database
      (thekingziga.com) or import your .drp files with ZERO offline clips!


4. UNC Network Share Mapping (e.g. \\server\share\footage\...)
--------------------------------------------------------------
If footage is stored on a Windows network share:
  • PC path:      \\truenas\share\take1.mov
  • TrueNAS Hub:  /media/SMB/truenas/share/take1.mov
  • Mac local:    /Volumes/YourSSD/SMB/truenas/share/take1.mov
  • DaVinci Mapped Mount on Mac:
      Mapped Mount (Remote): \\truenas\share\
      Local Mount (Mac):     /Volumes/YourSSD/SMB/truenas/share/


6. Network Project Server (PostgreSQL) - DaVinci Resolve Free & Studio
-----------------------------------------------------------------------
You don't need a DaVinci Resolve Studio license to work with network projects!
• Click "🔑 Import .resolvedbkey" in ResolveSync to load your database logins.
• ResolveSync connects directly to PostgreSQL (192.168.69.29 / thekingziga.com).
• Select any project (test123, thailand, etc.) from the dropdown and click "📂 Load Project".
• ResolveSync extracts 100% of media clips without needing DaVinci running or Studio API!
• Click "Start Sync" to push or pull media between TrueNAS and your workstation.


7. Manual 1-Click Relinking Fallback
------------------------------------
If you haven't set up Mapped Mounts yet:
   1. Select all clips in the DaVinci Resolve Media Pool (Cmd + A).
   2. Right-click -> "Relink Selected Clips...".
   3. Select your ResolveSync download folder (e.g. /Volumes/YourSSD).
   4. DaVinci Resolve will scan subfolders and relink everything in seconds.
