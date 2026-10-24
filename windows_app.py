#!/usr/bin/env python3
"""
ResolveSync Windows Desktop Application
=======================================
A native Windows desktop app for DaVinci Resolve media synchronization.
Aliases to desktop_app for universal cross-platform support.
"""

from desktop_app import (
    CONFIG_FILE,
    DaVinciProjectDiscoverer,
    DaVinciTipsDialog,
    DRPParser,
    HTTPServerSyncEngine,
    MediaItem,
    PathMapper,
    ResolveSyncApp,
    ResolveSyncAppGUI,
    SettingsDialog,
    SFTPSyncEngine,
    format_bytes,
    get_app_dir,
    main,
)

if __name__ == "__main__":
    main()
