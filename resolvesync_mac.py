#!/usr/bin/env python3
"""
ResolveSync macOS Standalone Client
==================================
Zero-dependency, standalone DaVinci Resolve media synchronizer for macOS.
Downloads project media directly from TrueNAS storage.

Preserves the exact disk and directory structure so that relinking in DaVinci
Resolve on Mac takes just one click.
"""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

# Safeguard UTF-8 console output
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Auto-install requests if missing
try:
    import requests
except ImportError:
    print("[!] 'requests' library not found. Installing via pip...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
        import requests
    except Exception as e:
        print(f"Error: Could not install 'requests': {e}")
        print("Please run: python3 -m pip install requests")
        sys.exit(1)


COMMON_MEDIA_EXTENSIONS = {
    ".mov", ".mp4", ".mxf", ".braw", ".r3d", ".ari", ".arx", ".dng",
    ".wav", ".mp3", ".aac", ".flac", ".aif", ".aiff",
    ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".exr", ".dpx"
}


def format_bytes(size: int) -> str:
    """Formats bytes into human-readable strings."""
    if not size or size <= 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def mac_choose_file(title: str = "Select DaVinci Resolve Project (.drp)") -> Optional[str]:
    """Opens native macOS Finder file chooser dialog with public.data fallback."""
    if platform.system() == "Darwin":
        try:
            cmd = f'osascript -e \'POSIX path of (choose file with prompt "{title}" of type {{"drp", "zip", "public.data"}})\''
            out = subprocess.check_output(cmd, shell=True, timeout=60).decode("utf-8").strip()
            if out and os.path.exists(out):
                return out
        except Exception:
            pass

    try:
        from tkinter import filedialog, Tk
        root = Tk()
        root.withdraw()
        path = filedialog.askopenfilename(
            title=title,
            filetypes=[
                ("DaVinci Resolve Project", ".drp"),
                ("Zip Archive", ".zip"),
                ("All Files", "*"),
            ]
        )
        root.destroy()
        return path if path else None
    except Exception:
        return None


def mac_choose_folder(title: str = "Select Destination Folder for Media Sync") -> Optional[str]:
    """Opens native macOS Finder folder chooser dialog."""
    if platform.system() == "Darwin":
        try:
            cmd = f'osascript -e \'POSIX path of (choose folder with prompt "{title}")\''
            out = subprocess.check_output(cmd, shell=True).decode("utf-8").strip()
            if out and os.path.isdir(out):
                return out
        except Exception:
            pass

    try:
        from tkinter import filedialog, Tk
        root = Tk()
        root.withdraw()
        path = filedialog.askdirectory(title=title)
        root.destroy()
        return path if path else None
    except Exception:
        return None


def extract_drp_media(drp_path: str) -> List[str]:
    """Extracts all referenced media file paths from a DaVinci Resolve project archive."""
    extracted = set()
    ordered = []

    with zipfile.ZipFile(drp_path, "r") as archive:
        for name in archive.namelist():
            if not name.lower().endswith(".xml"):
                continue

            raw_bytes = archive.read(name)
            raw_text = raw_bytes.decode("utf-8", errors="replace")
            # Sanitize DaVinci Resolve 21 C++ namespace tags
            clean_text = re.sub(r'<(/?[a-zA-Z0-9_]+)::([a-zA-Z0-9_]+)', r'<\1__\2', raw_text)

            try:
                root = ET.fromstring(clean_text)
            except Exception:
                continue

            for elem in root.iter():
                tag_lower = elem.tag.split("}")[-1].lower()

                # Hex-encoded binary Clip tags in DaVinci Resolve MediaPool
                if tag_lower == "clip" and elem.text and len(elem.text.strip()) > 30:
                    try:
                        clip_hex = elem.text.strip()
                        if all(c in "0123456789abcdefABCDEF" for c in clip_hex[:20]):
                            raw_clip = bytes.fromhex(clip_hex)
                            m = re.search(
                                rb'\n[\x01-\x7f]([a-zA-Z]:[^\x00-\x1f\x7f-\xff]+|\/[^\x00-\x1f\x7f-\xff]+)\x12[\x01-\x7f]([^\x00-\x1f\x7f-\xff]+?\.[a-zA-Z0-9]{2,5})',
                                raw_clip
                            )
                            if m:
                                d = m.group(1).decode("utf-8", errors="ignore").strip()
                                f = m.group(2).decode("utf-8", errors="ignore").strip()
                                p = os.path.join(d, f)
                                if p not in extracted:
                                    extracted.add(p)
                                    ordered.append(p)
                    except Exception:
                        pass

                # Element text path checking
                if elem.text:
                    t = elem.text.strip()
                    has_slash = "/" in t or "\\" in t
                    has_drive = bool(re.match(r"^[a-zA-Z]:", t))
                    _, ext = os.path.splitext(t)
                    if (has_slash or has_drive) and ext.lower() in COMMON_MEDIA_EXTENSIONS:
                        if t not in extracted:
                            extracted.add(t)
                            ordered.append(t)

    return ordered


def auto_map_path(drp_path: str, sync_root: str) -> Tuple[str, str]:
    """
    Translates any DRP path (Windows drive, UNC share, Mac volume)
    into a TrueNAS remote storage path and a local Mac download path.
    """
    clean = drp_path.strip()

    # Windows Drive Letter: D:\Users\zigav\Videos\jp.mp4
    m_win = re.match(r'^([a-zA-Z]):[\\/](.*)$', clean)
    if m_win:
        drive = m_win.group(1).upper()
        rest = re.sub(r'[\\/]+', '/', m_win.group(2)).strip('/')
        remote_path = f"/media/{drive}/{rest}"
        local_path = os.path.normpath(os.path.join(sync_root, drive, rest.replace('/', os.sep)))
        return local_path, remote_path

    # UNC Network Share: \\server\share\path\file.mp4
    m_unc = re.match(r'^[\\/]{2}([^\\/]+)[\\/]([^\\/]+)[\\/](.*)$', clean)
    if m_unc:
        srv, share, rest = m_unc.group(1), m_unc.group(2), re.sub(r'[\\/]+', '/', m_unc.group(3)).strip('/')
        remote_path = f"/media/SMB/{srv}/{share}/{rest}"
        local_path = os.path.normpath(os.path.join(sync_root, "SMB", srv, share, rest.replace('/', os.sep)))
        return local_path, remote_path

    # macOS Volume: /Volumes/SSD/...
    m_mac = re.match(r'^/Volumes/([^/]+)/(.*)$', clean, re.IGNORECASE)
    if m_mac:
        vol, rest = m_mac.group(1), m_mac.group(2).strip('/')
        remote_path = f"/media/Volumes/{vol}/{rest}"
        local_path = os.path.normpath(os.path.join(sync_root, "Volumes", vol, rest.replace('/', os.sep)))
        return local_path, remote_path

    # Generic absolute path
    norm_slash = re.sub(r'[\\/]+', '/', clean).lstrip('/')
    remote_path = f"/media/Root/{norm_slash}"
    local_path = os.path.normpath(os.path.join(sync_root, "Root", norm_slash.replace('/', os.sep)))
    return local_path, remote_path


def download_media_file(server_url: str, remote_path: str, local_path: str, expected_size: int = 0) -> bool:
    """Streams a file from TrueNAS HTTP API with resume and real-time progress."""
    local_dir = os.path.dirname(local_path)
    if local_dir:
        os.makedirs(local_dir, exist_ok=True)

    part_file = local_path + ".part"
    downloaded_bytes = 0
    headers = {}

    if os.path.exists(part_file):
        downloaded_bytes = os.path.getsize(part_file)
        headers["Range"] = f"bytes={downloaded_bytes}-"

    url = f"{server_url}/api/media/download"
    params = {"path": remote_path}
    filename = os.path.basename(local_path)

    start_time = time.time()
    last_print = 0

    with requests.get(url, params=params, headers=headers, stream=True, timeout=60) as r:
        if r.status_code not in (200, 206):
            raise IOError(f"HTTP {r.status_code} from TrueNAS: {r.text}")

        total_size = int(r.headers.get("Content-Length", 0)) + (downloaded_bytes if r.status_code == 206 else 0)
        if expected_size and total_size == 0:
            total_size = expected_size

        mode = "ab" if r.status_code == 206 else "wb"
        with open(part_file, mode) as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):  # 1MB buffer
                if chunk:
                    f.write(chunk)
                    downloaded_bytes += len(chunk)

                    now = time.time()
                    if now - last_print >= 0.3:
                        pct = (downloaded_bytes / total_size * 100) if total_size > 0 else 0
                        speed = downloaded_bytes / max(0.1, (now - start_time))
                        sys.stdout.write(f"\r  [{pct:5.1f}%] {filename[:30]:30} {format_bytes(downloaded_bytes)} / {format_bytes(total_size)} ({format_bytes(int(speed))}/s)")
                        sys.stdout.flush()
                        last_print = now

    sys.stdout.write(f"\r  [100.0%] {filename[:30]:30} {format_bytes(downloaded_bytes)} (Done!)\n")
    sys.stdout.flush()

    os.replace(part_file, local_path)
    return True


def main():
    print("\n" + "=" * 65)
    print("        ResolveSync - macOS DaVinci Resolve Client")
    print("=" * 65 + "\n")

    # Read server URL from local config.json if present
    server_url = "http://192.168.1.3:5000"
    for cand in ["config.json", os.path.expanduser("~/Movies/ResolveSync/config.json")]:
        if os.path.exists(cand):
            try:
                with open(cand, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                    s = data.get("server", {})
                    server_url = s.get("server_url") or s.get("host") or server_url
                    break
            except Exception:
                pass

    print(f"[+] Connecting to TrueNAS at: {server_url} ...")
    try:
        r = requests.get(f"{server_url}/api/status", timeout=4)
        if r.status_code == 200:
            info = r.json()
            media = info.get("media_pool") or {}
            free_gb = media.get("free", 0) / (1024 ** 3)
            print(f"[✓] Connected to TrueNAS! (Free storage: {free_gb:.1f} GB)\n")
        else:
            print(f"[!] Warning: TrueNAS responded with HTTP {r.status_code}\n")
    except Exception as e:
        print(f"[!] Warning: Could not reach TrueNAS at {server_url}: {e}\n")

    # 1. Project selection
    drp_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not drp_path or not os.path.exists(drp_path):
        print("[*] Opening Finder to select your DaVinci Resolve project (.drp)...")
        drp_path = mac_choose_file("Select DaVinci Resolve Project (.drp)")

    if not drp_path:
        drp_path = input("Enter path to .drp file: ").strip().strip("'\"")

    if not os.path.exists(drp_path):
        print(f"Error: Project file not found: {drp_path}")
        sys.exit(1)

    print(f"[+] Selected Project: {os.path.basename(drp_path)}")

    # 2. Destination folder selection (e.g. external SSD)
    dest_dir = sys.argv[2] if len(sys.argv) > 2 else None
    if not dest_dir:
        default_dir = os.path.expanduser("~/Movies/ResolveSync")
        print(f"\n[*] Where should downloaded media be saved on this Mac?")
        print(f"    (e.g. an external SSD like /Volumes/T7 or your internal drive)")
        print(f"[*] Opening folder picker (or cancel for default: {default_dir})...")

        picked = mac_choose_folder("Select Sync Destination Folder (e.g. External SSD):")
        dest_dir = picked if picked else default_dir

    dest_dir = os.path.abspath(os.path.expanduser(dest_dir))
    os.makedirs(dest_dir, exist_ok=True)
    print(f"[+] Sync Destination Folder: {dest_dir}\n")

    # 3. Analyze DRP
    print("[*] Parsing project and extracting media items...")
    raw_paths = extract_drp_media(drp_path)
    print(f"[+] Extracted {len(raw_paths)} media file references from DRP.")

    mapped_items = []
    remote_query_list = []
    for p in raw_paths:
        loc, rem = auto_map_path(p, dest_dir)
        mapped_items.append({
            "drp_path": p,
            "local_path": loc,
            "remote_path": rem,
            "local_exists": os.path.exists(loc),
            "size_local": os.path.getsize(loc) if os.path.exists(loc) else 0,
        })
        remote_query_list.append(rem)

    # 4. Check status on TrueNAS
    print("[*] Querying TrueNAS storage...")
    remote_status_map = {}
    try:
        r = requests.post(f"{server_url}/api/media/check", json={"files": remote_query_list}, timeout=15)
        if r.status_code == 200:
            remote_status_map = r.json().get("results", {})
    except Exception as ex:
        print(f"[!] Warning querying TrueNAS: {ex}")

    to_download = []
    already_synced = []

    for item in mapped_items:
        r_info = remote_status_map.get(item["remote_path"], {})
        r_exists = r_info.get("exists", False)
        r_size = r_info.get("size", 0)
        item["remote_exists"] = r_exists
        item["size_remote"] = r_size

        if item["local_exists"] and r_exists:
            already_synced.append(item)
        elif not item["local_exists"] and r_exists:
            to_download.append(item)

    print("-" * 65)
    print(f"Total Referenced Media:     {len(mapped_items)}")
    print(f"Already Synced (Local):     {len(already_synced)}")
    print(f"Available to Download:      {len(to_download)} (on TrueNAS)")
    print("-" * 65)

    if not to_download:
        print("\n[✓] All files for this project are already downloaded and in sync!")
    else:
        total_dl_bytes = sum(i["size_remote"] for i in to_download)
        print(f"\n[+] Ready to download {len(to_download)} files ({format_bytes(total_dl_bytes)}) into:")
        print(f"    {dest_dir}")
        print("\nPress [Enter] to start downloading (or Ctrl+C to cancel)...")
        try:
            input()
        except KeyboardInterrupt:
            print("\nAborted.")
            sys.exit(0)

        success = 0
        failed = 0
        for idx, it in enumerate(to_download, 1):
            fname = os.path.basename(it["local_path"])
            print(f"\n[{idx}/{len(to_download)}] Downloading: {fname}")
            try:
                download_media_file(
                    server_url=server_url,
                    remote_path=it["remote_path"],
                    local_path=it["local_path"],
                    expected_size=it["size_remote"],
                )
                success += 1
            except Exception as err:
                print(f"  ❌ Error downloading {fname}: {err}")
                failed += 1

        print("\n" + "=" * 65)
        print(f"  Download Complete! ({success} downloaded, {failed} failed)")
        print("=" * 65)

    # 5. Relink instructions
    print("\n" + "=" * 65)
    print("       HOW TO RELINK IN DAVINCI RESOLVE ON MAC (1-CLICK)")
    print("=" * 65)
    print("1. Open DaVinci Resolve on this Mac and open your project.")
    print("2. In the Media Pool, select all clips (Cmd + A).")
    print("3. Right-click -> 'Relink Selected Clips...'")
    print(f"4. Select this folder: {dest_dir}")
    print("Resolve will scan subfolders and relink all footage instantly!")
    print("\nTip: To make it 100% automatic in future:")
    print("Go to DaVinci Preferences -> Media Storage -> Mapped Mounts:")
    print(f"Map 'D:\\' <---> '{dest_dir}/D/'")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
