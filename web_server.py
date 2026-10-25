#!/usr/bin/env python3
"""
ResolveSync Server & Admin Dashboard
====================================
Runs directly on TrueNAS inside Docker with native access to the /media
and /projects ZFS storage pools.

Provides:
  1. High-Performance Direct Media Sync API (Chunked streaming, Range resume,
     atomic uploads) so client PCs/Macs sync without needing SSH/SFTP.
  2. Central Web Management & Storage Pool Monitoring Dashboard.
"""

import json
import logging
import os
import posixpath
import shutil
import sys
import tempfile
import threading
import time
from typing import Dict, List, Optional

from flask import Flask, jsonify, render_template, request, send_file

from resolvesync import PathMapper, ResolveSyncApp

app = Flask(__name__, template_folder="templates")

# Configure Web Server Logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ResolveSyncServer")

# Paths (Configured for TrueNAS Docker Mounts)
CONFIG_PATH = os.getenv("RESOLVESYNC_CONFIG", "/config/config.json" if os.path.exists("/config") else "config.json")
MEDIA_ROOT = os.getenv("RESOLVESYNC_MEDIA_PATH", "/media" if os.path.exists("/media") else os.path.abspath("./media"))
PROJECTS_ROOT = os.getenv("RESOLVESYNC_PROJECTS_PATH", "/projects" if os.path.exists("/projects") else os.path.abspath("./projects"))

# Ensure base directories exist if running locally
os.makedirs(MEDIA_ROOT, exist_ok=True)
os.makedirs(PROJECTS_ROOT, exist_ok=True)

# Global Sync Activity Log Buffer
activity_lock = threading.Lock()
server_activity_logs: List[dict] = []


def log_activity(action: str, client_ip: str, file_name: str, details: str = ""):
    """Appends an event to the server activity log for display on the web dashboard."""
    event = {
        "time": time.strftime("%H:%M:%S"),
        "action": action,        # DOWNLOAD, UPLOAD, CHECK, SYNC
        "client": client_ip,
        "filename": file_name,
        "details": details,
    }
    with activity_lock:
        server_activity_logs.append(event)
        if len(server_activity_logs) > 300:
            server_activity_logs.pop(0)


def sanitize_media_path(rel_path: str) -> Optional[str]:
    """
    Prevents path traversal attacks and resolves path safely relative to MEDIA_ROOT.
    Returns absolute path if valid, None if invalid/unsafe.
    """
    clean_rel = rel_path.replace("\\", "/").strip().lstrip("/")
    # Strip any leading 'media/' if the client prefixed it
    if clean_rel.lower().startswith("media/"):
        clean_rel = clean_rel[6:]

    # Normalize Windows drive letter format "D:/..." -> "D/..."
    if len(clean_rel) >= 2 and clean_rel[1] == ':' and clean_rel[0].isalpha():
        clean_rel = clean_rel[0].upper() + "/" + clean_rel[2:].lstrip("/")

    abs_path = os.path.abspath(os.path.join(MEDIA_ROOT, clean_rel))
    real_media = os.path.abspath(MEDIA_ROOT)

    if not abs_path.startswith(real_media):
        return None
    return abs_path


def load_config_data() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    if os.path.exists("config.example.json"):
        with open("config.example.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {"server": {}, "path_mappings": [], "sync_options": {}}


# ---------------------------------------------------------------------------
# Core Server & Health APIs
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status", methods=["GET"])
@app.route("/api/truenas/status", methods=["GET"])
def get_server_status():
    """Returns TrueNAS storage pool capacity, server health, and active activity."""
    def get_disk_info(path):
        try:
            total, used, free = shutil.disk_usage(path)
            return {
                "path": path,
                "total": total,
                "used": used,
                "free": free,
                "pct_used": round((used / total) * 100, 1) if total else 0,
            }
        except Exception:
            return None

    hostname = os.uname().nodename if hasattr(os, "uname") else os.getenv("COMPUTERNAME", "TrueNAS")

    with activity_lock:
        recent_logs = list(server_activity_logs[-50:])

    return jsonify({
        "status": "online",
        "service": "ResolveSync Hub",
        "version": "2.0.0",
        "hostname": hostname,
        "media_pool": get_disk_info(MEDIA_ROOT),
        "projects_pool": get_disk_info(PROJECTS_ROOT),
        "recent_activity": recent_logs,
        "docker_mode": os.path.exists("/.dockerenv") or os.path.exists("/config"),
    })


@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(load_config_data())


@app.route("/api/config", methods=["POST"])
def save_config():
    new_cfg = request.get_json()
    if not new_cfg:
        return jsonify({"error": "Invalid JSON"}), 400

    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(new_cfg, f, indent=2)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/test-mapping", methods=["POST"])
def test_mapping():
    data = request.get_json() or {}
    drp_path = data.get("drp_path", "").strip()
    if not drp_path:
        return jsonify({"matched": False, "message": "No path provided"})

    cfg = load_config_data()
    mapper = PathMapper.from_config(cfg)
    local_p, remote_p, matched_rule = mapper.map_path(drp_path)

    if matched_rule:
        return jsonify({
            "matched": True,
            "rule": matched_rule.name,
            "local_path": local_p,
            "remote_path": remote_p,
        })
    return jsonify({"matched": False})


# ---------------------------------------------------------------------------
# Direct Media Sync APIs (No SFTP required!)
# ---------------------------------------------------------------------------

@app.route("/api/media/check", methods=["POST"])
def check_media_batch():
    """
    Checks if a list of media file paths exist directly on the TrueNAS /media storage.
    Called by the Windows/Mac desktop app during project analysis.
    """
    data = request.get_json() or {}
    files = data.get("files", [])
    client_ip = request.remote_addr or "client"

    results = {}
    for f in files:
        abs_target = sanitize_media_path(f)
        if not abs_target:
            results[f] = {"exists": False, "size": 0, "error": "Invalid path"}
            continue

        if os.path.exists(abs_target) and os.path.isfile(abs_target):
            results[f] = {
                "exists": True,
                "size": os.path.getsize(abs_target),
                "mtime": int(os.path.getmtime(abs_target)),
            }
        else:
            results[f] = {"exists": False, "size": 0}

    log_activity("CHECK", client_ip, f"Batch check ({len(files)} files)", f"{sum(1 for r in results.values() if r['exists'])} found on NAS")
    return jsonify({"results": results})


@app.route("/api/media/download", methods=["GET"])
def download_media_file():
    """
    Streams a media file from TrueNAS /media to the client app.
    Supports HTTP Range requests for resuming 50GB+ video files.
    """
    rel_path = request.args.get("path", "")
    client_ip = request.remote_addr or "client"

    if not rel_path:
        return jsonify({"error": "Missing 'path' parameter"}), 400

    abs_target = sanitize_media_path(rel_path)
    if not abs_target or not os.path.exists(abs_target) or not os.path.isfile(abs_target):
        return jsonify({"error": f"File not found on storage: {rel_path}"}), 404

    filename = os.path.basename(abs_target)
    filesize = os.path.getsize(abs_target)
    log_activity("DOWNLOAD", client_ip, filename, f"{filesize / (1024 * 1024):.1f} MB")

    # conditional=True enables standard HTTP 206 Partial Content (resume)
    return send_file(abs_target, as_attachment=True, download_name=filename, conditional=True)


@app.route("/api/media/upload", methods=["POST"])
def upload_media_file():
    """
    Streams a media file from client PC into TrueNAS /media.
    Uses atomic .part staging and verifies file size.
    """
    rel_path = request.args.get("path") or request.headers.get("X-Media-Path")
    client_ip = request.remote_addr or "client"

    if not rel_path:
        return jsonify({"error": "Missing 'path' parameter or 'X-Media-Path' header"}), 400

    abs_target = sanitize_media_path(rel_path)
    if not abs_target:
        return jsonify({"error": "Forbidden destination path"}), 403

    target_dir = os.path.dirname(abs_target)
    os.makedirs(target_dir, exist_ok=True)

    part_file = abs_target + ".part"
    filename = os.path.basename(abs_target)

    # Clean stale partial file
    if os.path.exists(part_file):
        try:
            os.remove(part_file)
        except OSError:
            pass

    expected_size = request.headers.get("X-File-Size")
    if expected_size:
        try:
            expected_size = int(expected_size)
        except ValueError:
            expected_size = None

    try:
        # Check if multipart form upload or direct stream
        if "file" in request.files:
            uploaded = request.files["file"]
            uploaded.save(part_file)
        else:
            # Stream raw binary chunks directly to disk
            with open(part_file, "wb") as f_out:
                while True:
                    chunk = request.stream.read(1024 * 1024)  # 1MB buffer
                    if not chunk:
                        break
                    f_out.write(chunk)

        actual_size = os.path.getsize(part_file)

        # Verify size if header provided
        if expected_size is not None and actual_size != expected_size:
            if os.path.exists(part_file):
                os.remove(part_file)
            return jsonify({
                "error": f"Size mismatch! Expected {expected_size} bytes, received {actual_size} bytes."
            }), 400

        # Atomically rename .part to final file
        if os.path.exists(abs_target):
            try:
                os.remove(abs_target)
            except OSError:
                pass
        os.replace(part_file, abs_target)

        log_activity("UPLOAD", client_ip, filename, f"{actual_size / (1024 * 1024):.1f} MB written to NAS")
        return jsonify({
            "success": True,
            "filename": filename,
            "path": rel_path,
            "size": actual_size,
        })

    except Exception as e:
        if os.path.exists(part_file):
            try:
                os.remove(part_file)
            except OSError:
                pass
        logger.error(f"Upload failed for {filename}: {e}")
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Project Analysis & Inspection APIs
# ---------------------------------------------------------------------------

@app.route("/api/upload-drp", methods=["POST"])
def upload_drp():
    """Allows uploading a .drp project directly into the Web UI for analysis."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    temp_dir = tempfile.gettempdir()
    save_path = os.path.join(temp_dir, f"resolvesync_{int(time.time())}_{file.filename}")
    file.save(save_path)

    try:
        sync_app = ResolveSyncApp(config_path=CONFIG_PATH)
        items = sync_app.analyze_inventory(save_path, check_remote=False)

        # Check against local /media directly
        for item in items:
            if item.remote_path:
                abs_m = sanitize_media_path(item.remote_path)
                if abs_m and os.path.exists(abs_m):
                    item.remote_exists = True
                    item.file_size_remote = os.path.getsize(abs_m)
                    item.status = "SYNCED" if item.local_exists else "NEEDS_DOWNLOAD"
                else:
                    item.remote_exists = False
                    item.status = "NEEDS_UPLOAD" if item.local_exists else "MISSING_EVERYWHERE"

        return jsonify({
            "filename": file.filename,
            "drp_path": save_path,
            "items": [item.to_dict() for item in items],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def start_server(config_path: str = "config.json", port: int = 5000):
    global CONFIG_PATH
    CONFIG_PATH = config_path

    print("\n" + "=" * 65)
    print("   ResolveSync Hub & Storage Server")
    print(f"   Listening on: http://0.0.0.0:{port}")
    print(f"   Media Pool:   {MEDIA_ROOT}")
    print(f"   Projects:     {PROJECTS_ROOT}")
    print("=" * 65 + "\n")

    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    port_env = int(os.getenv("PORT", 5000))
    start_server(port=port_env)
