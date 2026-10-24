#!/usr/bin/env python3
"""
ResolveSync - Automated Media Sync Engine for DaVinci Resolve
============================================================
Synchronizes media referenced in DaVinci Resolve Project (.drp) files
between a self-hosted SFTP remote server (NAS) and local storage.
Supports bidirectional sync (Upload & Download), and cross-platform
path translation (Windows <-> macOS <-> Linux).

No DaVinci Resolve Studio license or Blackmagic Cloud subscription required.
"""

import argparse
import json
import logging
import os
import platform
import posixpath
import re
import shutil
import stat
import sys
import tempfile
import urllib.parse
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from typing import Callable, Dict, List, Optional, Set, Tuple

__version__ = "1.1.0"


class SyncCancelledError(Exception):
    """Raised immediately when synchronization is cancelled by user."""
    pass

# Fix Windows console UTF-8 output encoding for emojis and non-ASCII paths
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import paramiko
except ImportError:
    paramiko = None

try:
    import requests
except ImportError:
    requests = None

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Logging Setup (Console & Persistent Debug Log File)
# ---------------------------------------------------------------------------
logger = logging.getLogger("ResolveSync")


def get_debug_log_path() -> str:
    """Returns the persistent debug log file path for the current platform."""
    if sys.platform == "darwin":
        log_dir = os.path.expanduser("~/Library/Logs/ResolveSync")
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
        log_dir = os.path.join(appdata, "ResolveSync")
    else:
        log_dir = os.path.expanduser("~/.resolvesync")

    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        log_dir = os.path.expanduser("~")

    return os.path.join(log_dir, "resolvesync_debug.log")


def setup_file_logger(verbose: bool = False) -> str:
    """Configures both console and persistent file logging. Default is INFO (debug OFF)."""
    log_path = get_debug_log_path()
    log_level = logging.DEBUG if verbose else logging.INFO

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Attach file handler if not already present
    has_file = any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == log_path for h in root_logger.handlers)
    if not has_file:
        try:
            file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
            file_handler.setLevel(log_level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except Exception as ex:
            sys.stderr.write(f"Warning: Could not create file logger at {log_path}: {ex}\n")

    # Attach console handler if not present
    has_console = any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in root_logger.handlers)
    if not has_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
        root_logger.addHandler(console_handler)

    logger.info(f"=== ResolveSync Session Initialized ===")
    logger.info(f"Log file: {log_path}")
    logger.info(f"Platform: {platform.system()} {platform.release()} ({platform.machine()})")
    logger.info(f"Python: {sys.executable} ({sys.version.split()[0]})")
    logger.info(f"Debug logging: {'ENABLED' if verbose else 'DISABLED (Default: INFO/ERROR only)'}")

    return log_path


def set_debug_logging(enabled: bool):
    """Dynamically updates root logger and all handlers to DEBUG or INFO level."""
    level = logging.DEBUG if enabled else logging.INFO
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for h in root_logger.handlers:
        h.setLevel(level)
    logger.info(f"Logging level updated: {'DEBUG (verbose)' if enabled else 'INFO (standard - debug off)'}")


def setup_logging(verbose: bool = False):
    """Configure console and file logging."""
    setup_file_logger(verbose=verbose)


# ---------------------------------------------------------------------------
# Constants & Recognized Formats
# ---------------------------------------------------------------------------

# Known XML tags in DaVinci Resolve project schemas where media paths live
KNOWN_PATH_TAGS = {
    "filepath",
    "path",
    "clippath",
    "mediafilepath",
    "sourcefilepath",
    "originalpath",
    "audiofilepath",
    "videofilepath",
    "masteraudiofilepath",
    "proxyfilepath",
    "optimizedfilepath",
    "ms_path",
    "sourcepath",
}

# Known XML attributes that may store media paths
KNOWN_PATH_ATTRS = {
    "filepath",
    "path",
    "source",
    "file",
    "src",
    "clippath",
    "mediafilepath",
    "originalpath",
}

# Auto-generated Resolve cache and project-internal files to skip
EXCLUDED_EXTENSIONS = {
    ".dvcc",      # DaVinci Video Cache
    ".drx",       # DaVinci Resolve Grade Stills
    ".dtl",       # DaVinci Timeline / Cache
    ".gallery",   # Gallery stills
    ".tmp",       # Temporary files
    ".dat",       # Cache data
    ".cache",     # Generic cache
    ".xml",       # Nested XMLs or metadata
    ".db",        # Project database files
    ".idx",       # Waveform indices
    ".setting",   # Fusion node settings
    ".caf",       # Cache Audio Format
}

# Standard professional video, audio, and graphic formats
COMMON_MEDIA_EXTENSIONS = {
    # Video & RAW
    ".mov", ".mp4", ".mxf", ".mkv", ".avi", ".braw", ".r3d", ".ari",
    ".crm", ".dng", ".webm", ".mpg", ".mpeg", ".m2ts", ".mts", ".vob",
    ".wmv", ".flv", ".f4v", ".cine",
    # Audio
    ".wav", ".mp3", ".aac", ".flac", ".aiff", ".aif", ".m4a", ".ogg",
    ".wma", ".opus",
    # Images / Stills / Sequences
    ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".exr", ".psd", ".psb",
    ".dpx", ".tga", ".bmp", ".svg", ".cin", ".hdr",
}


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class PathMappingRule:
    """Represents a translation rule between DRP path, Local path, and SFTP Remote path."""
    name: str
    drp_prefix: str
    local_prefix: str
    remote_prefix: str

    def matches(self, drp_path: str) -> bool:
        """Check if drp_path begins with this rule's drp_prefix."""
        norm_rule = self._normalize_for_matching(self.drp_prefix)
        norm_path = self._normalize_for_matching(drp_path)
        return norm_path.lower().startswith(norm_rule.lower())

    def translate(self, drp_path: str) -> Tuple[str, str]:
        """
        Translates a DRP path into (local_path, remote_path).
        Preserves subdirectory structure and original file naming.
        """
        norm_rule = self._normalize_for_matching(self.drp_prefix)
        norm_path = self._normalize_for_matching(drp_path)

        # Slice the relative path after the prefix
        relative_part = norm_path[len(norm_rule):].lstrip("/")

        # 1. Build Local Path (using current host OS separator)
        local_rel = relative_part.replace("/", os.sep).replace("\\", os.sep)
        local_full = os.path.normpath(os.path.join(self.local_prefix, local_rel))

        # 2. Build Remote SFTP Path (always uses POSIX forward slashes '/')
        remote_rel = relative_part.replace("\\", "/").strip("/")
        remote_base = self.remote_prefix.replace("\\", "/").rstrip("/")
        remote_full = f"{remote_base}/{remote_rel}" if remote_base else f"/{remote_rel}"

        return local_full, remote_full

    @staticmethod
    def _normalize_for_matching(p: str) -> str:
        """Normalizes path string to forward slashes with collapsed separators and stripped trailing slashes."""
        if not p:
            return ""
        return re.sub(r'[\\/]+', '/', p.strip()).rstrip('/')


@dataclass
class MediaItem:
    """Represents a media file found in the DRP project or live library."""
    drp_path: str
    local_path: Optional[str] = None
    remote_path: Optional[str] = None
    status: str = "PENDING"  # SYNCED, NEEDS_DOWNLOAD, NEEDS_UPLOAD, MISSING_EVERYWHERE, UNMAPPED, ERROR
    local_exists: bool = False
    remote_exists: bool = False
    file_size_local: int = 0
    file_size_remote: int = 0
    matched_rule: Optional[str] = None
    error_message: Optional[str] = None
    is_proxy: bool = False
    proxy_path: Optional[str] = None

    def __post_init__(self):
        if not self.is_proxy:
            self.is_proxy = self.is_proxy_file(self.drp_path) or self.is_proxy_file(self.local_path or "")

    @staticmethod
    def is_proxy_file(path: str) -> bool:
        """Determines if a file path refers to proxy media based on DaVinci conventions."""
        if not path:
            return False
        clean = path.replace("\\", "/")
        parts = clean.lower().split("/")
        fname = parts[-1] if parts else ""
        proxy_folders = {"proxy", "proxies", "proxymedia", "proxy_half", "proxy_quarter", "lowres", "offline"}
        if any(p in proxy_folders for p in parts[:-1]):
            return True
        stem, _ = os.path.splitext(fname)
        if stem.endswith("_proxy") or stem.endswith("-proxy") or "_proxy_" in stem:
            return True
        return False

    @staticmethod
    def find_local_proxies(local_path: Optional[str]) -> List[str]:
        """
        Discovers local companion proxy media generated by DaVinci Resolve or Blackmagic Proxy Generator.
        Looks in:
          1. <Folder>/Proxy/ or <Folder>/Proxies/ or <Folder>/ProxyMedia/
          2. <Folder>/<stem>_Proxy.* or <stem>-proxy.*
        """
        if not local_path:
            return []
        folder = os.path.dirname(local_path)
        stem, orig_ext = os.path.splitext(os.path.basename(local_path))
        stem_lower = stem.lower()
        candidates = []
        seen = set()

        # 1. Search standard DaVinci Proxy / Proxies / ProxyMedia subfolders
        for sub in ("Proxy", "Proxies", "ProxyMedia"):
            sub_dir = os.path.join(folder, sub)
            if os.path.isdir(sub_dir):
                try:
                    for fname in os.listdir(sub_dir):
                        fstem, fext = os.path.splitext(fname)
                        fstem_lower = fstem.lower()
                        if fstem_lower in (stem_lower, f"{stem_lower}_proxy", f"{stem_lower}-proxy"):
                            full_p = os.path.join(sub_dir, fname)
                            if full_p not in seen and os.path.isfile(full_p):
                                seen.add(full_p)
                                candidates.append(full_p)
                except Exception:
                    pass

        # 2. Search adjacent files in the same directory with proxy suffix
        if os.path.isdir(folder):
            try:
                for fname in os.listdir(folder):
                    fstem, fext = os.path.splitext(fname)
                    fstem_lower = fstem.lower()
                    if fstem_lower in (f"{stem_lower}_proxy", f"{stem_lower}-proxy"):
                        full_p = os.path.join(folder, fname)
                        if full_p not in seen and os.path.isfile(full_p):
                            seen.add(full_p)
                            candidates.append(full_p)
            except Exception:
                pass

        return candidates

    @staticmethod
    def get_candidate_remote_proxy_paths(remote_path: Optional[str]) -> List[str]:
        """
        Generates possible remote proxy paths on TrueNAS for a given camera original.
        """
        if not remote_path:
            return []
        remote_dir = posixpath.dirname(remote_path)
        stem, _ = posixpath.splitext(posixpath.basename(remote_path))
        candidates = []
        for ext in (".mov", ".mp4", ".mxf"):
            candidates.append(f"{remote_dir}/Proxy/{stem}{ext}")
            candidates.append(f"{remote_dir}/Proxy/{stem}_Proxy{ext}")
            candidates.append(f"{remote_dir}/{stem}_Proxy{ext}")
        return candidates

    def to_dict(self) -> dict:
        filename = os.path.basename(self.local_path or self.drp_path)
        _, ext = os.path.splitext(filename)
        return {
            "filename": filename,
            "extension": ext.lower(),
            "drp_path": self.drp_path,
            "local_path": self.local_path,
            "remote_path": self.remote_path,
            "status": self.status,
            "local_exists": self.local_exists,
            "remote_exists": self.remote_exists,
            "file_size_local": self.file_size_local,
            "file_size_remote": self.file_size_remote,
            "matched_rule": self.matched_rule,
            "error_message": self.error_message,
            "is_proxy": self.is_proxy,
            "proxy_path": self.proxy_path,
        }


# ---------------------------------------------------------------------------
# DRP Parsing Engine
# ---------------------------------------------------------------------------

class DRPParser:
    """
    Extracts media file references from DaVinci Resolve Project (.drp) archives.
    .drp files are standard ZIP archives containing XML project files (project.xml).
    """

    def __init__(self, allowed_exts: Optional[Set[str]] = None, excluded_exts: Optional[Set[str]] = None):
        self.allowed_exts = {e.lower() for e in allowed_exts} if allowed_exts else None
        self.excluded_exts = {e.lower() for e in (excluded_exts or EXCLUDED_EXTENSIONS)}

    def extract_media_paths(self, drp_path: str) -> List[str]:
        """
        Opens the .drp ZIP archive in memory, finds and parses all XML files,
        and returns a deduplicated list of original media file paths.
        """
        if not os.path.exists(drp_path):
            raise FileNotFoundError(f"DRP file not found: {drp_path}")

        if not zipfile.is_zipfile(drp_path):
            raise ValueError(f"The specified file is not a valid ZIP/DRP archive: {drp_path}")

        extracted_paths: Set[str] = set()
        ordered_paths: List[str] = []

        logger.info(f"Opening DRP archive: {os.path.basename(drp_path)}")
        with zipfile.ZipFile(drp_path, "r") as archive:
            namelist = archive.namelist()
            xml_files = [name for name in namelist if name.lower().endswith(".xml")]

            if not xml_files:
                logger.warning("No XML files found inside the .drp archive!")
                return []

            logger.debug(f"Found {len(xml_files)} XML files in DRP: {xml_files}")

            for xml_name in xml_files:
                logger.debug(f"Parsing XML: {xml_name}")
                try:
                    raw_bytes = archive.read(xml_name)
                    raw_text = raw_bytes.decode("utf-8", errors="replace")
                    # Sanitize DaVinci Resolve 21 C++ namespace tags (e.g. ListMgt::Lm... -> ListMgt__Lm...)
                    clean_text = re.sub(r'<(/?[a-zA-Z0-9_]+)::([a-zA-Z0-9_]+)', r'<\1__\2', raw_text)
                    root = ET.fromstring(clean_text)

                    # Scan elements and attributes
                    for elem in root.iter():
                        tag_lower = elem.tag.split("}")[-1].lower()

                        # 0. Check hex-encoded binary Clip elements in DaVinci Resolve MediaPool
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
                                        d_part = m.group(1).decode("utf-8", errors="ignore").strip()
                                        f_part = m.group(2).decode("utf-8", errors="ignore").strip()
                                        full_path = os.path.join(d_part, f_part)
                                        cleaned = self._clean_path(full_path)
                                        if cleaned and self._is_valid_media(cleaned):
                                            if cleaned not in extracted_paths:
                                                extracted_paths.add(cleaned)
                                                ordered_paths.append(cleaned)
                            except Exception:
                                pass

                        # 1. Check element text
                        if elem.text:
                            text_val = elem.text.strip()
                            if tag_lower in KNOWN_PATH_TAGS or self._looks_like_media_path(text_val):
                                cleaned = self._clean_path(text_val)
                                if cleaned and self._is_valid_media(cleaned):
                                    if cleaned not in extracted_paths:
                                        extracted_paths.add(cleaned)
                                        ordered_paths.append(cleaned)

                        # 2. Check element attributes (e.g. <Clip filePath="..."/>)
                        for attr_name, attr_val in elem.attrib.items():
                            attr_lower = attr_name.lower()
                            if attr_lower in KNOWN_PATH_ATTRS or self._looks_like_media_path(attr_val):
                                cleaned = self._clean_path(attr_val)
                                if cleaned and self._is_valid_media(cleaned):
                                    if cleaned not in extracted_paths:
                                        extracted_paths.add(cleaned)
                                        ordered_paths.append(cleaned)

                except ET.ParseError as pe:
                    logger.warning(f"XML parse error in {xml_name}: {pe}")
                except Exception as ex:
                    logger.warning(f"Error reading {xml_name}: {ex}")

        logger.info(f"Extracted {len(ordered_paths)} unique media file references from DRP.")
        return ordered_paths

    def inspect_drp(self, drp_path: str):
        """Diagnostic inspection mode for user discovery of internal schema."""
        print("\n" + "=" * 60)
        print(f"  DRP ARCHIVE INSPECTOR: {os.path.basename(drp_path)}")
        print("=" * 60)

        if not os.path.exists(drp_path):
            print(f"Error: File does not exist: {drp_path}")
            return

        with zipfile.ZipFile(drp_path, "r") as archive:
            files = archive.namelist()
            print(f"\n[+] Total files inside ZIP: {len(files)}")
            for f in files:
                info = archive.getinfo(f)
                print(f"    - {f} ({info.file_size:,} bytes)")

            xml_files = [f for f in files if f.lower().endswith(".xml")]
            print(f"\n[+] XML Files Found: {len(xml_files)}")

            all_tags: Set[str] = set()
            all_attrs: Set[str] = set()
            found_paths: List[Tuple[str, str, str]] = []

            for xml_name in xml_files:
                try:
                    raw_bytes = archive.read(xml_name)
                    raw_text = raw_bytes.decode("utf-8", errors="replace")
                    clean_text = re.sub(r'<(/?[a-zA-Z0-9_]+)::([a-zA-Z0-9_]+)', r'<\1__\2', raw_text)
                    root = ET.fromstring(clean_text)
                    for elem in root.iter():
                            tag_clean = elem.tag.split("}")[-1]
                            all_tags.add(tag_clean)

                            if elem.text:
                                text_val = elem.text.strip()
                                if self._looks_like_media_path(text_val):
                                    found_paths.append((xml_name, f"<{tag_clean}>", text_val))

                            for attr_name, attr_val in elem.attrib.items():
                                all_attrs.add(attr_name)
                                if self._looks_like_media_path(attr_val):
                                    found_paths.append((xml_name, f"@{attr_name}", attr_val))

                except Exception as ex:
                    print(f"    [!] Error parsing {xml_name}: {ex}")

            print(f"\n[+] Total XML Tags Present: {len(all_tags)}")
            candidate_tags = [t for t in all_tags if any(k in t.lower() for k in ("path", "file", "clip", "media", "source"))]
            print(f"    Tags with media/path keywords ({len(candidate_tags)}):")
            for t in sorted(candidate_tags):
                print(f"      <{t}>")

            print(f"\n[+] Total XML Attributes Present: {len(all_attrs)}")
            candidate_attrs = [a for a in all_attrs if any(k in a.lower() for k in ("path", "file", "clip", "media", "source", "src"))]
            print(f"    Attributes with media/path keywords ({len(candidate_attrs)}):")
            for a in sorted(candidate_attrs):
                print(f"      @{a}")

            print(f"\n[+] Extracted Candidate Media Paths ({len(found_paths)}):")
            for src, loc, path_str in found_paths[:20]:
                print(f"    [{src}] {loc} -> {path_str}")
            if len(found_paths) > 20:
                print(f"    ... and {len(found_paths) - 20} more paths.")

        print("=" * 60 + "\n")

    @staticmethod
    def _clean_path(raw_path: str) -> str:
        """Cleans URL encoding, prefixes (file://), and whitespace."""
        p = raw_path.strip()
        p = urllib.parse.unquote(p)

        if p.lower().startswith("file://localhost/"):
            p = p[16:]
        elif p.lower().startswith("file:///"):
            p = p[8:]
            if len(p) >= 2 and p[1] == ":":
                pass
            else:
                p = "/" + p
        elif p.lower().startswith("file://"):
            p = p[7:]

        return p

    def _looks_like_media_path(self, text: str) -> bool:
        if not text or len(text) < 4:
            return False

        has_slash = "/" in text or "\\" in text
        has_drive = bool(re.match(r"^[a-zA-Z]:", text))
        _, ext = os.path.splitext(text)
        ext_lower = ext.lower()

        if ext_lower in self.excluded_exts:
            return False

        # Only consider it a media path if it has directory separators or drive letter
        if (has_slash or has_drive) and ext_lower in COMMON_MEDIA_EXTENSIONS:
            return True

        if (has_slash or has_drive) and ext_lower and len(ext_lower) <= 5:
            if re.match(r"^[a-zA-Z]:[/\\]", text) or text.startswith("/") or text.startswith("\\\\"):
                return True

        return False

    def _is_valid_media(self, path_str: str) -> bool:
        _, ext = os.path.splitext(path_str)
        ext_lower = ext.lower()

        if not ext_lower:
            return False

        if ext_lower in self.excluded_exts:
            return False

        if self.allowed_exts:
            return ext_lower in self.allowed_exts

        return True


# ---------------------------------------------------------------------------
# Path Mapping & OS Conversion Engine
# ---------------------------------------------------------------------------

class PathMapper:
    """
    Translates file paths across operating systems and remote environments.
    Converts: DRP Path -> Local Machine Path & Remote TrueNAS/SFTP Path.
    Supports both custom prefix rules and zero-config Native DaVinci Auto-Mapping.
    """

    def __init__(
        self,
        rules: Optional[List[PathMappingRule]] = None,
        auto_fallback: bool = False,
        sync_root: Optional[str] = None,
    ):
        self.rules = rules or []
        self.auto_fallback = auto_fallback
        self.sync_root = sync_root

    @classmethod
    def from_config(cls, config_data: dict) -> "PathMapper":
        rules = []
        for item in config_data.get("path_mappings", []):
            rule = PathMappingRule(
                name=item.get("name", "Unnamed Rule"),
                drp_prefix=item.get("drp_prefix", ""),
                local_prefix=item.get("local_prefix", ""),
                remote_prefix=item.get("remote_prefix", ""),
            )
            rules.append(rule)

        sync_opts = config_data.get("sync_options", {})
        auto_fallback = sync_opts.get("auto_map_unmatched", True)
        sync_root = config_data.get("sync_root_folder") or sync_opts.get("download_folder")
        return cls(rules, auto_fallback=auto_fallback, sync_root=sync_root)

    def map_path(
        self,
        drp_path: str,
        sync_root: Optional[str] = None,
        force_auto: Optional[bool] = None,
    ) -> Tuple[Optional[str], Optional[str], Optional[PathMappingRule]]:
        """
        Finds the matching rule and computes (local_path, remote_path, matching_rule).
        If no explicit rule matches and auto_fallback is enabled (default), automatically
        computes the canonical TrueNAS storage path and local path preserving drive/folder hierarchy.
        """
        # 1. Check custom user rules
        for rule in self.rules:
            if rule.matches(drp_path):
                local_path, remote_path = rule.translate(drp_path)
                return local_path, remote_path, rule

        # 2. Native DaVinci Auto-Mapping (Zero Config!)
        should_auto = self.auto_fallback if force_auto is None else force_auto
        if should_auto:
            active_root = sync_root or self.sync_root
            return self.auto_map(drp_path, active_root)

        return None, None, None

    @classmethod
    def auto_map(cls, drp_path: str, sync_root: Optional[str] = None) -> Tuple[str, str, PathMappingRule]:
        """
        Zero-config Native DaVinci Sync path translator.
        Converts any local path into a clean, canonical TrueNAS path and maps
        download destinations while preserving drive and folder hierarchies.
        """
        clean = drp_path.strip()

        # A. Windows Drive Letter (e.g. D:\Users\zigav\Videos\jp.mp4 or D:/...)
        m_win = re.match(r'^([a-zA-Z]):[\\/](.*)$', clean)
        if m_win:
            drive = m_win.group(1).upper()
            rest = re.sub(r'[\\/]+', '/', m_win.group(2)).strip('/')
            remote_path = f"/media/{drive}/{rest}"

            norm_clean = os.path.normpath(clean)
            if os.name == 'nt' and os.path.exists(norm_clean):
                local_path = norm_clean
            elif sync_root:
                local_path = os.path.normpath(os.path.join(sync_root, drive, rest.replace('/', os.sep)))
            elif os.name == 'nt':
                local_path = norm_clean
            else:
                def_root = os.path.expanduser("~/Movies/ResolveSync")
                local_path = os.path.normpath(os.path.join(def_root, drive, rest.replace('/', os.sep)))

            rule = PathMappingRule(
                name=f"Auto (Drive {drive}:)",
                drp_prefix=f"{drive}:",
                local_prefix=f"{drive}:" if os.name == 'nt' else (sync_root or "~/Movies/ResolveSync"),
                remote_prefix=f"/media/{drive}",
            )
            return local_path, remote_path, rule

        # B. UNC Network Share (e.g. \\server\share\folder\file.ext)
        m_unc = re.match(r'^[\\/]{2}([^\\/]+)[\\/]([^\\/]+)[\\/](.*)$', clean)
        if m_unc:
            srv = m_unc.group(1)
            share = m_unc.group(2)
            rest = re.sub(r'[\\/]+', '/', m_unc.group(3)).strip('/')
            remote_path = f"/media/SMB/{srv}/{share}/{rest}"
            norm_clean = os.path.normpath(clean)
            if os.path.exists(norm_clean):
                local_path = norm_clean
            elif sync_root:
                local_path = os.path.normpath(os.path.join(sync_root, "SMB", srv, share, rest.replace('/', os.sep)))
            else:
                local_path = norm_clean

            rule = PathMappingRule(
                name=f"Auto (SMB {srv}/{share})",
                drp_prefix=f"\\\\{srv}\\{share}",
                local_prefix=f"\\\\{srv}\\{share}" if os.name == 'nt' else (sync_root or "~/Movies/ResolveSync"),
                remote_prefix=f"/media/SMB/{srv}/{share}",
            )
            return local_path, remote_path, rule

        # C. macOS Volume (e.g. /Volumes/ExtSSD/path/file.ext)
        m_mac = re.match(r'^/Volumes/([^/]+)/(.*)$', clean, re.IGNORECASE)
        if m_mac:
            vol = m_mac.group(1)
            rest = m_mac.group(2).strip('/')
            remote_path = f"/media/Volumes/{vol}/{rest}"
            if os.path.exists(clean):
                local_path = clean
            elif sync_root:
                local_path = os.path.normpath(os.path.join(sync_root, "Volumes", vol, rest.replace('/', os.sep)))
            else:
                local_path = clean

            rule = PathMappingRule(
                name=f"Auto (Volume {vol})",
                drp_prefix=f"/Volumes/{vol}",
                local_prefix=f"/Volumes/{vol}" if sys.platform == "darwin" else (sync_root or "D:\\DAVINCI"),
                remote_prefix=f"/media/Volumes/{vol}",
            )
            return local_path, remote_path, rule

        # D. Generic Absolute Path (/Users/..., /home/..., etc.)
        norm_slash = re.sub(r'[\\/]+', '/', clean).lstrip('/')
        remote_path = f"/media/Root/{norm_slash}"
        if os.path.exists(clean):
            local_path = clean
        elif sync_root:
            local_path = os.path.normpath(os.path.join(sync_root, "Root", norm_slash.replace('/', os.sep)))
        else:
            local_path = clean

        rule = PathMappingRule(
            name="Auto (System Path)",
            drp_prefix="/",
            local_prefix="/" if os.name != 'nt' else (sync_root or "D:\\DAVINCI"),
            remote_prefix="/media/Root",
        )
        return local_path, remote_path, rule


# ---------------------------------------------------------------------------
# SFTP Sync Engine (Bidirectional: Download & Upload)
# ---------------------------------------------------------------------------

class SFTPSyncEngine:
    """
    Manages SFTP connection, checks remote file metadata, and performs
    safe atomic file downloads and uploads with progress reporting.
    """

    def __init__(self, server_config: dict):
        if paramiko is None:
            raise ImportError(
                "The 'paramiko' library is required for SFTP sync. "
                "Install it with: pip install paramiko"
            )

        self.host = server_config.get("host")
        self.port = int(server_config.get("port", 22))
        self.username = server_config.get("username")
        self.password = server_config.get("password") or None
        self.key_file = server_config.get("key_file") or None
        self.key_passphrase = server_config.get("key_passphrase") or None
        self.timeout = int(server_config.get("timeout_seconds", 30))

        self.ssh_client: Optional[paramiko.SSHClient] = None
        self.sftp_client: Optional[paramiko.SFTPClient] = None

    def connect(self):
        """Establishes SSH and SFTP connections with key or password authentication."""
        logger.info(f"Connecting to SFTP server: {self.username}@{self.host}:{self.port} ...")
        self.ssh_client = paramiko.SSHClient()
        self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "timeout": self.timeout,
        }

        if self.key_file:
            expanded_key = os.path.expanduser(self.key_file)
            if os.path.exists(expanded_key):
                connect_kwargs["key_filename"] = expanded_key
                if self.key_passphrase:
                    connect_kwargs["passphrase"] = self.key_passphrase
                logger.debug(f"Using SSH private key: {expanded_key}")
            else:
                logger.warning(f"Configured key_file does not exist: {expanded_key}. Falling back to password/agent.")

        if self.password:
            connect_kwargs["password"] = self.password

        try:
            self.ssh_client.connect(**connect_kwargs)
            self.sftp_client = self.ssh_client.open_sftp()
            logger.info("SFTP connection successfully established.")
        except Exception as e:
            logger.error(f"Failed to connect to SFTP server {self.host}:{self.port} - {e}")
            self.close()
            raise

    def close(self):
        """Closes SFTP channel and SSH connection."""
        if self.sftp_client:
            try:
                self.sftp_client.close()
            except Exception:
                pass
            self.sftp_client = None

        if self.ssh_client:
            try:
                self.ssh_client.close()
            except Exception:
                pass
            self.ssh_client = None
        logger.debug("SFTP connection closed.")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def get_remote_file_size(self, remote_path: str) -> Optional[int]:
        """
        Retrieves remote file size in bytes via sftp.stat().
        Returns None if file does not exist.
        """
        if not self.sftp_client:
            raise RuntimeError("SFTP client is not connected.")

        try:
            stat_result = self.sftp_client.stat(remote_path)
            if stat.S_ISREG(stat_result.st_mode):
                return stat_result.st_size
            return None
        except IOError:
            return None

    def remote_makedirs(self, remote_dir: str):
        """Recursively creates directories on the remote SFTP server (similar to mkdir -p)."""
        if not self.sftp_client:
            raise RuntimeError("SFTP client is not connected.")

        norm_dir = posixpath.normpath(remote_dir.replace("\\", "/"))
        if norm_dir in ("", ".", "/"):
            return

        parts = [p for p in norm_dir.split("/") if p]
        current = "/" if norm_dir.startswith("/") else ""
        for part in parts:
            current = posixpath.join(current, part)
            try:
                self.sftp_client.stat(current)
            except IOError:
                try:
                    self.sftp_client.mkdir(current)
                    logger.debug(f"Created remote directory: {current}")
                except IOError:
                    pass

    def download_file(
        self,
        remote_path: str,
        local_path: str,
        expected_size: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """
        Downloads a file from remote SFTP to local workstation:
          1. Creates local parent folders.
          2. Safe atomic download using a temporary '.part' file.
          3. Real-time progress bar (tqdm) or custom callback.
          4. Immediate cancellation support.
          5. Size verification.
        """
        if is_cancelled and is_cancelled():
            raise SyncCancelledError("SFTP download cancelled before start")

        if not self.sftp_client:
            raise RuntimeError("SFTP client is not connected.")

        local_dir = os.path.dirname(local_path)
        if local_dir and not os.path.exists(local_dir):
            os.makedirs(local_dir, exist_ok=True)

        if expected_size is None:
            expected_size = self.get_remote_file_size(remote_path)
            if expected_size is None:
                raise FileNotFoundError(f"Remote file does not exist: {remote_path}")

        part_path = local_path + ".part"
        filename = os.path.basename(local_path)

        if os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                pass

        logger.info(f"Downloading: {filename} ({expected_size / (1024 * 1024):.2f} MB)")

        pbar = None
        if tqdm is not None and not progress_callback:
            pbar = tqdm(
                total=expected_size,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                desc=f"Down: {filename[:20]}".ljust(25),
                leave=True,
            )

        last_transferred = 0

        def sftp_get_callback(transferred: int, total: int):
            nonlocal last_transferred
            if is_cancelled and is_cancelled():
                raise SyncCancelledError("SFTP download cancelled by user")
            if pbar is not None:
                pbar.update(transferred - last_transferred)
            last_transferred = transferred
            if progress_callback:
                progress_callback(transferred, total, "download", filename)

        try:
            self.sftp_client.get(
                remotepath=remote_path,
                localpath=part_path,
                callback=sftp_get_callback,
            )
        except SyncCancelledError:
            if pbar is not None:
                pbar.close()
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except OSError:
                    pass
            raise
        except Exception as e:
            if pbar is not None:
                pbar.close()
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except OSError:
                    pass
            raise IOError(f"SFTP download interrupted for {filename}: {e}") from e
        finally:
            if pbar is not None:
                pbar.close()

        actual_size = os.path.getsize(part_path)
        if actual_size != expected_size:
            if os.path.exists(part_path):
                os.remove(part_path)
            raise IOError(
                f"File size mismatch on {filename}! Expected {expected_size} bytes, "
                f"downloaded {actual_size} bytes. Partial file removed."
            )

        os.replace(part_path, local_path)
        return True

    def upload_file(
        self,
        local_path: str,
        remote_path: str,
        expected_size: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """
        Uploads a file from local workstation to remote SFTP (NAS):
          1. Creates remote parent directory tree.
          2. Safe atomic upload using a temporary '.part' file on the remote server.
          3. Real-time progress bar (tqdm) or custom callback.
          4. Verifies remote file size and performs atomic rename.
        """
        if is_cancelled and is_cancelled():
            raise SyncCancelledError("SFTP upload cancelled before start")

        if not self.sftp_client:
            raise RuntimeError("SFTP client is not connected.")

        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Local file does not exist: {local_path}")

        local_size = os.path.getsize(local_path)
        if expected_size is None:
            expected_size = local_size

        remote_dir = posixpath.dirname(remote_path)
        if remote_dir:
            self.remote_makedirs(remote_dir)

        part_remote_path = remote_path + ".part"
        filename = os.path.basename(local_path)

        # Remove stale partial file on remote
        try:
            self.sftp_client.remove(part_remote_path)
        except IOError:
            pass

        logger.info(f"Uploading: {filename} ({expected_size / (1024 * 1024):.2f} MB)")

        pbar = None
        if tqdm is not None and not progress_callback:
            pbar = tqdm(
                total=expected_size,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                desc=f"Up: {filename[:20]}".ljust(25),
                leave=True,
            )

        last_transferred = 0

        def sftp_put_callback(transferred: int, total: int):
            nonlocal last_transferred
            if is_cancelled and is_cancelled():
                raise SyncCancelledError("SFTP upload cancelled by user")
            if pbar is not None:
                pbar.update(transferred - last_transferred)
            last_transferred = transferred
            if progress_callback:
                progress_callback(transferred, total, "upload", filename)

        try:
            self.sftp_client.put(
                localpath=local_path,
                remotepath=part_remote_path,
                callback=sftp_put_callback,
            )
        except SyncCancelledError:
            if pbar is not None:
                pbar.close()
            try:
                self.sftp_client.remove(part_remote_path)
            except IOError:
                pass
            raise
        except Exception as e:
            if pbar is not None:
                pbar.close()
            try:
                self.sftp_client.remove(part_remote_path)
            except IOError:
                pass
            raise IOError(f"SFTP upload interrupted for {filename}: {e}") from e
        finally:
            if pbar is not None:
                pbar.close()

        # Verify remote uploaded file size
        try:
            uploaded_size = self.sftp_client.stat(part_remote_path).st_size
        except IOError as e:
            raise IOError(f"Failed to stat uploaded remote file {part_remote_path}: {e}")

        if uploaded_size != expected_size:
            try:
                self.sftp_client.remove(part_remote_path)
            except IOError:
                pass
            raise IOError(
                f"Upload size mismatch for {filename}! Expected {expected_size} bytes, "
                f"uploaded {uploaded_size} bytes. Stale remote file removed."
            )

        # Atomic rename on remote server
        try:
            self.sftp_client.posix_rename(part_remote_path, remote_path)
        except (IOError, AttributeError):
            try:
                self.sftp_client.remove(remote_path)
            except IOError:
                pass
            self.sftp_client.rename(part_remote_path, remote_path)

        return True


# ---------------------------------------------------------------------------
# HTTP REST Sync Engine (Direct to TrueNAS Docker Container - No SFTP)
# ---------------------------------------------------------------------------

class HTTPServerSyncEngine:
    """
    Connects directly to the ResolveSync Docker container running on TrueNAS.
    Transfers media via high-speed chunked HTTP streaming with resume support.
    Eliminates the need for TrueNAS SSH/SFTP or local shell access.
    """

    def __init__(self, server_url: str):
        if requests is None:
            raise ImportError(
                "The 'requests' library is required for HTTP Hub sync. "
                "Install it with: pip install requests"
            )
        self.server_url = server_url.rstrip("/")

    def check_connection(self) -> Tuple[bool, str]:
        """Tests connectivity and checks TrueNAS storage pool capacity."""
        try:
            resp = requests.get(f"{self.server_url}/api/status", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                media = data.get("media_pool") or {}
                free_gb = media.get("free", 0) / (1024 ** 3)
                total_gb = media.get("total", 0) / (1024 ** 3)
                return True, f"Connected to TrueNAS Hub! Free: {free_gb:.1f} GB of {total_gb:.1f} GB"
            return False, f"Server returned HTTP {resp.status_code}"
        except Exception as e:
            return False, str(e)

    def check_remote_batch(self, relative_paths: List[str]) -> Dict[str, dict]:
        """Queries the TrueNAS container for existence and sizes of all project clips in one batch."""
        try:
            url = f"{self.server_url}/api/media/check"
            resp = requests.post(url, json={"files": relative_paths}, timeout=15)
            if resp.status_code == 200:
                return resp.json().get("results", {})
        except Exception as e:
            logger.warning(f"Error querying TrueNAS server for media files: {e}")
        return {}

    def download_file(
        self,
        remote_path: str,
        local_path: str,
        expected_size: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """Downloads a media file from TrueNAS via HTTP chunked streaming with resume and immediate cancellation."""
        if is_cancelled and is_cancelled():
            raise SyncCancelledError("Download cancelled before start")

        local_dir = os.path.dirname(local_path)
        if local_dir and not os.path.exists(local_dir):
            os.makedirs(local_dir, exist_ok=True)

        part_path = local_path + ".part"
        filename = os.path.basename(local_path)

        downloaded_bytes = 0
        headers = {}
        if os.path.exists(part_path):
            downloaded_bytes = os.path.getsize(part_path)
            headers["Range"] = f"bytes={downloaded_bytes}-"

        url = f"{self.server_url}/api/media/download"
        params = {"path": remote_path}

        pbar = None
        last_transferred = downloaded_bytes
        last_cb_time = 0

        try:
            with requests.get(url, params=params, headers=headers, stream=True, timeout=60) as r:
                if r.status_code not in (200, 206):
                    raise IOError(f"TrueNAS server returned HTTP {r.status_code} for {remote_path}")

                total_size = int(r.headers.get("Content-Length", 0)) + (downloaded_bytes if r.status_code == 206 else 0)
                if expected_size:
                    total_size = expected_size

                if tqdm is not None and not progress_callback:
                    pbar = tqdm(
                        total=total_size,
                        initial=downloaded_bytes,
                        unit="B",
                        unit_scale=True,
                        unit_divisor=1024,
                        desc=f"Down: {filename[:20]}".ljust(25),
                        leave=True,
                    )

                mode = "ab" if r.status_code == 206 else "wb"
                with open(part_path, mode) as f:
                    # 2MB buffer for high-throughput disk I/O without CPU thrashing
                    for chunk in r.iter_content(chunk_size=1024 * 1024 * 2):
                        if is_cancelled and is_cancelled():
                            if pbar is not None:
                                pbar.close()
                            raise SyncCancelledError("Download cancelled by user")
                        if chunk:
                            f.write(chunk)
                            downloaded_bytes += len(chunk)
                            if pbar is not None:
                                pbar.update(downloaded_bytes - last_transferred)
                            last_transferred = downloaded_bytes

                            now = time.time()
                            if progress_callback and (downloaded_bytes >= total_size or (now - last_cb_time) >= 0.08):
                                last_cb_time = now
                                progress_callback(downloaded_bytes, total_size, "download", filename)

        except SyncCancelledError:
            if os.path.exists(part_path):
                try:
                    os.remove(part_path)
                except OSError:
                    pass
            raise
        finally:
            if pbar is not None:
                pbar.close()

        # Atomic rename
        os.replace(part_path, local_path)
        return True

    def upload_file(
        self,
        local_path: str,
        remote_path: str,
        expected_size: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """Streams a local file directly into the TrueNAS /media storage dataset with immediate cancellation."""
        if is_cancelled and is_cancelled():
            raise SyncCancelledError("Upload cancelled before start")

        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Local file does not exist: {local_path}")

        filename = os.path.basename(local_path)
        file_size = os.path.getsize(local_path)
        if expected_size is None:
            expected_size = file_size

        url = f"{self.server_url}/api/media/upload"
        params = {"path": remote_path}
        headers = {"X-File-Size": str(file_size)}

        pbar = None
        if tqdm is not None and not progress_callback:
            pbar = tqdm(
                total=file_size,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                desc=f"Up: {filename[:20]}".ljust(25),
                leave=True,
            )

        class ChunkReader:
            def __init__(self, path, callback, pbar_ref, cancel_fn):
                self.f = open(path, "rb")
                self.callback = callback
                self.pbar = pbar_ref
                self.cancel_fn = cancel_fn
                self.transferred = 0
                self.total = file_size
                self.last_t = 0
                self.last_cb_time = 0

            def read(self, size=-1):
                if self.cancel_fn and self.cancel_fn():
                    self.f.close()
                    raise SyncCancelledError("Upload cancelled by user")

                chunk = self.f.read(size)
                if chunk:
                    self.transferred += len(chunk)
                    if self.pbar is not None:
                        self.pbar.update(self.transferred - self.last_t)
                    self.last_t = self.transferred

                    now = time.time()
                    if self.callback and (self.transferred >= self.total or (now - self.last_cb_time) >= 0.08):
                        self.last_cb_time = now
                        self.callback(self.transferred, self.total, "upload", filename)
                return chunk

            def close(self):
                try:
                    self.f.close()
                except Exception:
                    pass

        reader = ChunkReader(local_path, progress_callback, pbar, is_cancelled)
        try:
            resp = requests.post(url, params=params, headers=headers, data=reader, stream=True, timeout=300)
            if resp.status_code != 200:
                raise IOError(f"Upload to TrueNAS server failed (HTTP {resp.status_code}): {resp.text}")
        except SyncCancelledError:
            raise
        finally:
            reader.close()
        try:
            resp = requests.post(url, params=params, headers=headers, data=reader, stream=True, timeout=300)
            if resp.status_code != 200:
                raise IOError(f"Upload to TrueNAS server failed (HTTP {resp.status_code}): {resp.text}")
        finally:
            reader.close()
            if pbar is not None:
                pbar.close()

        return True


# ---------------------------------------------------------------------------
# DaVinci Resolve Project & Media Discovery Engine
# ---------------------------------------------------------------------------

class DaVinciProjectDiscoverer:
    """
    Auto-discovers projects and media clips directly from DaVinci Resolve:
      1. Live Running Resolve via Blackmagic Design Scripting API:
         Queries the active open project and extracts media pool clip paths live.
      2. Recent Projects Parser:
         Parses recentprojects.conf (Local Disk, PostgreSQL Network Server, Blackmagic Cloud).
      3. Project Libraries:
         Discovers configured databases (dblist.conf / activedb.conf).
    """

    @staticmethod
    def check_resolve_process_running() -> bool:
        """Checks if DaVinci Resolve process is currently running in the OS."""
        try:
            import subprocess
            if sys.platform == "win32":
                out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Resolve*"], capture_output=True, text=True, timeout=5)
                is_run = "resolve.exe" in out.stdout.lower()
                logger.debug(f"[DaVinciDiscovery] Windows process check for Resolve.exe: {is_run}")
                return is_run
            else:
                out = subprocess.run(["pgrep", "-f", "Resolve"], capture_output=True, text=True, timeout=5)
                is_run = bool(out.stdout.strip())
                logger.debug(f"[DaVinciDiscovery] macOS/Linux process check for Resolve: {is_run}")
                return is_run
        except Exception as e:
            logger.debug(f"[DaVinciDiscovery] Process check error: {e}")
            return False

    @staticmethod
    def get_resolve_script_api():
        """Attempts to load the DaVinciResolveScript module or fusionscript library."""
        logger.info(f"[DaVinciDiscovery] Scanning for DaVinci Resolve Scripting API on {sys.platform}...")

        found_lib = None
        candidate_libs = []
        candidate_module_paths = []

        if sys.platform == "win32":
            candidate_libs = [
                r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
                os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), "Blackmagic Design", "DaVinci Resolve", "fusionscript.dll"),
            ]
            candidate_module_paths = [
                r"C:\Program Files\Blackmagic Design\DaVinci Resolve\ResolvePython\lib\modules",
                r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Developer\Scripting\Modules",
                os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Scripting", "Modules"),
            ]
        elif sys.platform == "darwin":
            candidate_libs = [
                "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
                "/Applications/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so",
                "/Applications/DaVinci Resolve Studio/DaVinci Resolve Studio.app/Contents/Libraries/Fusion/fusionscript.so",
                "/Applications/DaVinci Resolve Studio.app/Contents/Libraries/Fusion/fusionscript.so",
                os.path.expanduser("~/Applications/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"),
                os.path.expanduser("~/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"),
            ]
            candidate_module_paths = [
                "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
                "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Resources/Developer/Scripting/Modules",
                "/Applications/DaVinci Resolve.app/Contents/Resources/Developer/Scripting/Modules",
                "/Applications/DaVinci Resolve Studio/DaVinci Resolve Studio.app/Contents/Resources/Developer/Scripting/Modules",
                "/Applications/DaVinci Resolve Studio.app/Contents/Resources/Developer/Scripting/Modules",
                os.path.expanduser("~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"),
            ]
        else:
            candidate_libs = [
                "/opt/resolve/libs/Fusion/fusionscript.so",
            ]
            candidate_module_paths = [
                "/opt/resolve/Developer/Scripting/Modules",
            ]

        for lib_path in candidate_libs:
            if os.path.exists(lib_path):
                found_lib = lib_path
                logger.info(f"[DaVinciDiscovery] ✓ Located fusionscript library: {found_lib}")
                os.environ["RESOLVE_SCRIPT_LIB"] = found_lib
                break
            else:
                logger.debug(f"[DaVinciDiscovery] Candidate lib path not found: {lib_path}")

        for mod_dir in candidate_module_paths:
            if os.path.exists(mod_dir):
                logger.info(f"[DaVinciDiscovery] ✓ Located scripting module dir: {mod_dir}")
                if mod_dir not in sys.path:
                    sys.path.append(mod_dir)
                curr_pypath = os.environ.get("PYTHONPATH", "")
                if mod_dir not in curr_pypath:
                    os.environ["PYTHONPATH"] = (curr_pypath + os.pathsep + mod_dir) if curr_pypath else mod_dir
            else:
                logger.debug(f"[DaVinciDiscovery] Candidate module dir not found: {mod_dir}")

        # 1. Try importing DaVinciResolveScript standard wrapper
        try:
            import DaVinciResolveScript as bmd
            logger.info("[DaVinciDiscovery] Successfully imported 'DaVinciResolveScript'")
            return bmd
        except Exception as ex:
            logger.debug(f"[DaVinciDiscovery] 'import DaVinciResolveScript' raised: {ex}")

        # 2. Direct fallback: Load fusionscript dynamic library directly
        if found_lib and os.path.exists(found_lib):
            try:
                import importlib.machinery
                import importlib.util
                if sys.platform == "win32":
                    os.environ["PYTHON3HOME"] = sys.base_prefix
                loader = importlib.machinery.ExtensionFileLoader("fusionscript", found_lib)
                spec = importlib.util.spec_from_loader("fusionscript", loader)
                if spec:
                    fusion_mod = importlib.util.module_from_spec(spec)
                    loader.exec_module(fusion_mod)
                    logger.info(f"[DaVinciDiscovery] Successfully directly loaded fusionscript from {found_lib}")
                    return fusion_mod
            except Exception as dyn_ex:
                logger.error(f"[DaVinciDiscovery] Direct dynamic load of {found_lib} failed: {dyn_ex}")

        logger.warning("[DaVinciDiscovery] Could not load DaVinci Resolve scripting API.")
        return None

    @classmethod
    def get_live_project(cls) -> dict:
        """
        Connects to a running DaVinci Resolve instance.
        Returns:
          - {'status': 'active', 'project_name': str, 'media_paths': List[str], 'clip_count': int}
          - {'status': 'no_project_open', 'message': str, 'projects_in_folder': List[str]}
          - {'status': 'scripting_disabled', 'message': str, 'process_running': True}
          - {'status': 'not_running', 'message': str, 'process_running': False}
        """
        proc_running = cls.check_resolve_process_running()
        logger.info(f"[DaVinciDiscovery] Process check: DaVinci Resolve running in OS = {proc_running}")

        bmd = cls.get_resolve_script_api()
        if not bmd:
            return {
                "status": "no_api",
                "message": "DaVinci Resolve scripting library was not found in standard system locations.",
                "process_running": proc_running,
            }

        try:
            resolve = bmd.scriptapp("Resolve")
            logger.info(f"[DaVinciDiscovery] bmd.scriptapp('Resolve') returned: {resolve}")

            if not resolve:
                if proc_running:
                    msg = (
                        "DaVinci Resolve is running, but external scripting is disabled in DaVinci Preferences!\n"
                        "To enable: Open DaVinci Resolve -> Preferences (Cmd/Ctrl + ,) -> System -> General.\n"
                        "Change 'External scripting using' from 'None' to 'Local'. Click Save, then click Connect again."
                    )
                    logger.warning("[DaVinciDiscovery] " + msg)
                    return {
                        "status": "scripting_disabled",
                        "message": msg,
                        "process_running": True,
                    }
                else:
                    msg = "DaVinci Resolve is not running. Please launch DaVinci Resolve and open your project."
                    logger.info("[DaVinciDiscovery] " + msg)
                    return {
                        "status": "not_running",
                        "message": msg,
                        "process_running": False,
                    }

            pm = resolve.GetProjectManager()
            if not pm:
                logger.error("[DaVinciDiscovery] Failed to obtain Project Manager from resolve object.")
                return {"status": "error", "message": "Failed to access DaVinci Resolve Project Manager."}

            proj = pm.GetCurrentProject()
            if not proj:
                logger.info("[DaVinciDiscovery] DaVinci Resolve is running, but no project is open in the editor.")
                return {
                    "status": "no_project_open",
                    "message": "DaVinci Resolve is running, but no project is open. Please open your project in DaVinci.",
                    "projects_in_folder": pm.GetProjectListInCurrentFolder() or [],
                }

            proj_name = proj.GetName()
            logger.info(f"[DaVinciDiscovery] Connected to active project: '{proj_name}'")

            mp = proj.GetMediaPool()
            rf = mp.GetRootFolder() if mp else None

            paths = []
            seen = set()

            def recurse_folder(folder):
                if not folder:
                    return
                for clip in folder.GetClipList() or []:
                    p = clip.GetClipProperty("File Path")
                    if p and p not in seen:
                        seen.add(p)
                        paths.append(p)
                for sub in folder.GetSubFolderList() or []:
                    recurse_folder(sub)

            recurse_folder(rf)
            logger.info(f"[DaVinciDiscovery] Found {len(paths)} media file references in active project '{proj_name}'")

            return {
                "status": "active",
                "project_name": proj_name,
                "media_paths": paths,
                "clip_count": len(paths),
            }
        except Exception as e:
            logger.error(f"[DaVinciDiscovery] Error querying DaVinci Resolve: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

            return {
                "status": "active",
                "project_name": proj_name,
                "media_paths": paths,
                "clip_count": len(paths),
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @classmethod
    def get_recent_projects(cls) -> List[dict]:
        """
        Parses DaVinci Resolve's recentprojects.conf to find recent projects
        across Local Disk databases, Network PostgreSQL project servers, and Blackmagic Cloud.
        """
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA", "")
            conf = os.path.join(appdata, "Blackmagic Design", "DaVinci Resolve", "Preferences", "recentprojects.conf")
        elif sys.platform == "darwin":
            conf = os.path.expanduser("~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Preferences/recentprojects.conf")
        else:
            conf = os.path.expanduser("~/.local/share/DaVinciResolve/Preferences/recentprojects.conf")

        if not os.path.exists(conf):
            return []

        results = []
        try:
            with open(conf, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(":")
                    db_type = parts[0]
                    db_name = parts[1] if len(parts) > 1 else db_type
                    name = None
                    proj_id = None
                    for p in parts[3:]:
                        p_clean = p.strip("\\/")
                        if p_clean:
                            if "-" in p_clean and len(p_clean) == 36:
                                if not proj_id:
                                    proj_id = p_clean
                            else:
                                name = p_clean
                                break
                    if name:
                        results.append({
                            "name": name,
                            "id": proj_id,
                            "db_type": db_type,
                            "db_name": db_name,
                            "display": f"{name} ({db_type.upper()}: {db_name})",
                        })
        except Exception as ex:
            logger.debug(f"Error parsing recentprojects.conf: {ex}")

        return results


# ---------------------------------------------------------------------------
# DaVinci Resolve PostgreSQL Project Library Reader
# ---------------------------------------------------------------------------

class DaVinciPostgresReader:
    """
    Directly queries DaVinci Resolve's PostgreSQL Project Server (Project Library).
    Enables zero-config live project discovery and media extraction on DaVinci Resolve Free
    without requiring DaVinci Resolve Studio or Blackmagic Cloud.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5432,
        user: str = "main",
        password: str = "12345",
        dbname: str = "main",
        alt_host: Optional[str] = None,
        alt_port: Optional[int] = None,
        timeout: int = 5,
    ):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.dbname = dbname
        self.alt_host = alt_host
        self.alt_port = int(alt_port) if alt_port else (12345 if alt_host and "thekingziga" in alt_host else 5432)
        self.timeout = timeout

    @classmethod
    def from_config(cls, config: dict) -> Optional["DaVinciPostgresReader"]:
        """Creates reader from config dict if 'postgres' section exists."""
        pg_cfg = config.get("postgres", {})
        if not pg_cfg:
            return None
        if pg_cfg.get("enabled") is False:
            return None
        host = pg_cfg.get("host")
        if not host:
            return None
        return cls(
            host=host,
            port=pg_cfg.get("port", 5432),
            user=pg_cfg.get("user", "main"),
            password=pg_cfg.get("password", "12345"),
            dbname=pg_cfg.get("dbname", "main"),
            alt_host=pg_cfg.get("alt_host"),
            alt_port=pg_cfg.get("alt_port"),
            timeout=pg_cfg.get("timeout", 5),
        )

    @staticmethod
    def parse_resolvedbkey(file_or_content: str) -> dict:
        """
        Parses a DaVinci Resolve database key file (.resolvedbkey) or XML string.
        Extracts hostIPAddress, dbName, dbUsername, dbPassword, and optional port.
        """
        content = file_or_content.strip()
        if os.path.exists(file_or_content):
            with open(file_or_content, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

        root = ET.fromstring(content)
        host = (root.findtext("hostIPAddress") or "").strip()
        port = (root.findtext("port") or "5432").strip()
        user = (root.findtext("dbUsername") or "main").strip()
        password = (root.findtext("dbPassword") or "").strip()
        dbname = (root.findtext("dbName") or "main").strip()

        # Handle host with port like "thekingziga.com:12345"
        if ":" in host and not host.startswith("["):
            parts = host.split(":")
            host = parts[0]
            port = parts[1]

        return {
            "host": host,
            "port": int(port) if port.isdigit() else 5432,
            "user": user,
            "password": password,
            "dbname": dbname,
        }

    def _connect_to(self, host: str, port: int):
        import pg8000.native
        conn = pg8000.native.Connection(
            user=self.user,
            password=self.password,
            host=host,
            port=port,
            database=self.dbname,
            timeout=self.timeout,
        )
        conn.run("SET client_encoding TO 'UTF8'")
        return conn

    def _get_connection(self):
        try:
            import pg8000.native
        except ImportError:
            raise ImportError(
                "The 'pg8000' library is required to query PostgreSQL Project Libraries.\n"
                "Please run: pip install pg8000"
            )

        # Try primary host first
        errors = []
        try:
            return self._connect_to(self.host, self.port)
        except Exception as e:
            errors.append(f"{self.host}:{self.port} -> {e}")

        # Try alternative host if configured (e.g. WAN fallback or LAN fallback)
        if self.alt_host and (self.alt_host != self.host or self.alt_port != self.port):
            try:
                logger.info(f"[PostgresReader] Primary host {self.host}:{self.port} failed, trying fallback {self.alt_host}:{self.alt_port}...")
                return self._connect_to(self.alt_host, self.alt_port or 5432)
            except Exception as e2:
                errors.append(f"{self.alt_host}:{self.alt_port} -> {e2}")

        raise ConnectionError(f"Could not connect to PostgreSQL server: {'; '.join(errors)}")

    def test_connection(self) -> Tuple[bool, str]:
        """Tests connectivity and returns (success: bool, status_message: str)."""
        try:
            conn = self._get_connection()
            rows = conn.run('SELECT count(*) FROM "SM_Project"')
            count = rows[0][0] if rows else 0
            conn.close()
            return True, f"Connected to '{self.dbname}' ({count} project{'s' if count != 1 else ''} found)"
        except Exception as e:
            logger.error(f"[PostgresReader] Connection test failed: {e}")
            return False, str(e)

    def list_projects(self) -> List[dict]:
        """
        Returns all projects available in the PostgreSQL database.
        Each entry: {'id': str, 'name': str, 'display': str, 'db_type': 'network', 'db_name': str}
        """
        try:
            conn = self._get_connection()
            rows = conn.run('SELECT "SM_Project_id", "ProjectName" FROM "SM_Project" ORDER BY "ProjectName" ASC')
            conn.close()
            return [
                {
                    "id": str(r[0]),
                    "name": str(r[1]),
                    "display": f"{r[1]} (PostgreSQL: {self.dbname})",
                    "db_type": "network",
                    "db_name": self.dbname,
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"[PostgresReader] Failed to list projects: {e}")
            return []

    def get_project_media(self, project_name: str) -> List[str]:
        """
        Extracts all media file paths for a given project directly from the PostgreSQL library.
        Follows project -> Sm2MediaPool -> Sm2MpFolder hierarchy -> Sm2MpMedia -> BtVideoInfo / BtAudioInfo.
        """
        try:
            conn = self._get_connection()

            # 1. Look up Project ID
            proj_rows = conn.run(f'SELECT "SM_Project_id" FROM "SM_Project" WHERE "ProjectName" = \'{project_name}\'')
            if not proj_rows:
                logger.warning(f"[PostgresReader] Project '{project_name}' not found in database.")
                conn.close()
                return []
            proj_id = str(proj_rows[0][0])

            # 2. Look up Media Pool ID
            mp_rows = conn.run(f'SELECT "Sm2MediaPool_id" FROM "Sm2MediaPool" WHERE "SM_Project_id" = \'{proj_id}\'')
            if not mp_rows:
                logger.warning(f"[PostgresReader] No media pool found for project '{project_name}'.")
                conn.close()
                return []
            mp_id = str(mp_rows[0][0])

            # 3. Find root master folders
            root_folders = conn.run(f'SELECT "Sm2MpFolder_id" FROM "Sm2MpFolder" WHERE "Sm2MediaPool_id" = \'{mp_id}\'')
            all_folder_ids = {str(r[0]) for r in root_folders}
            queue = list(all_folder_ids)

            # 4. Recursively collect all sub-folder IDs
            while queue:
                curr = queue.pop(0)
                children = conn.run(f'SELECT "Sm2MpFolder_id" FROM "Sm2MpFolder" WHERE "Sm2MpFolder_Owner_id" = \'{curr}\'')
                for c in children:
                    cid = str(c[0])
                    if cid not in all_folder_ids:
                        all_folder_ids.add(cid)
                        queue.append(cid)

            if not all_folder_ids:
                conn.close()
                return []

            folder_in = ", ".join(f"'{fid}'" for fid in all_folder_ids)

            # 5. Query media entries and clip blobs
            media_rows = conn.run(f'''
                SELECT m."Sm2MpMedia_id", m."Name", v."Clip", a."Clip"
                FROM "Sm2MpMedia" m
                LEFT JOIN "BtVideoInfo" v ON v."Sm2MpMedia_id" = m."Sm2MpMedia_id"
                LEFT JOIN "BtAudioInfo" a ON a."Sm2MpMedia_id" = m."Sm2MpMedia_id"
                WHERE m."Sm2MpFolder_id" IN ({folder_in})
            ''')
            conn.close()

            # 6. Extract clip paths using protobuf binary pattern
            paths = []
            seen = set()
            regex = re.compile(rb'\n[\x01-\x7f]([a-zA-Z]:[^\x00-\x1f\x7f]+|\/[^\x00-\x1f\x7f]+)\x12[\x01-\x7f]([^\x00-\x1f\x7f]+?\.[a-zA-Z0-9]{2,5})')

            for r in media_rows:
                clip_bytes = r[2] or r[3]
                if clip_bytes:
                    m = regex.search(clip_bytes)
                    if m:
                        d = m.group(1).decode("utf-8", errors="ignore").strip()
                        f = m.group(2).decode("utf-8", errors="ignore").strip()
                        full_p = f"{d}\\{f}" if "\\" in d else f"{d}/{f}"
                        if full_p not in seen:
                            seen.add(full_p)
                            paths.append(full_p)

            logger.info(f"[PostgresReader] Project '{project_name}': extracted {len(paths)} media file paths from PostgreSQL.")
            return paths

        except Exception as e:
            logger.error(f"[PostgresReader] Failed to query media for '{project_name}': {e}", exc_info=True)
            return []



# ---------------------------------------------------------------------------
# DaVinci Resolve Preferences Manager (Mapped Mounts Automation)
# ---------------------------------------------------------------------------

class DaVinciPreferencesManager:
    """
    Directly manages DaVinci Resolve preferences (.config.data and config.dat)
    for media storage mounts and cross-platform mapped mounts.
    Supports reading existing mounts, detecting slash mismatches / corrupt paths,
    safe backup creation, and direct 1-click addition of mapped mount entries
    without requiring DaVinci Resolve Studio or manual preference editing.
    """

    def __init__(self, pref_dir: Optional[str] = None):
        if pref_dir:
            self.pref_dir = pref_dir
        else:
            self.pref_dir = self.get_default_pref_dir()
        self.config_data_file = os.path.join(self.pref_dir, ".config.data") if self.pref_dir else ""
        self.config_dat_file = os.path.join(self.pref_dir, "config.dat") if self.pref_dir else ""

    @staticmethod
    def get_default_pref_dir() -> str:
        """Returns the default DaVinci Resolve Preferences folder for the current OS."""
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                return os.path.join(appdata, "Blackmagic Design", "DaVinci Resolve", "Preferences")
            return os.path.expandvars(r"%APPDATA%\Blackmagic Design\DaVinci Resolve\Preferences")
        elif sys.platform == "darwin":
            candidates = [
                os.path.expanduser("~/Library/Preferences/Blackmagic Design/DaVinci Resolve"),
                os.path.expanduser("~/Library/Containers/com.blackmagic-design.DaVinciResolveLite/Data/Library/Preferences"),
                os.path.expanduser("~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Preferences"),
            ]
            for c in candidates:
                if os.path.exists(c) and (os.path.exists(os.path.join(c, ".config.data")) or os.path.exists(os.path.join(c, "config.dat"))):
                    return c
            return candidates[0]
        else:
            p1 = os.path.expanduser("~/.local/share/DaVinciResolve/Preferences")
            if os.path.exists(p1):
                return p1
            return os.path.expanduser("~/.DaVinciResolve/Preferences")

    def exists(self) -> bool:
        """Returns True if the DaVinci Preferences folder exists on this computer."""
        if not self.pref_dir or not os.path.isdir(self.pref_dir):
            return False
        return os.path.exists(self.config_data_file) or os.path.exists(self.config_dat_file)

    @staticmethod
    def is_davinci_running() -> bool:
        """Checks if DaVinci Resolve process is currently active."""
        try:
            import subprocess
            if sys.platform == "win32":
                r = subprocess.run(["tasklist", "/fi", "imagename eq Resolve.exe"], capture_output=True, text=True, timeout=3)
                return "resolve.exe" in r.stdout.lower()
            else:
                r = subprocess.run(["pgrep", "-x", "Resolve"], capture_output=True, text=True, timeout=3)
                return r.returncode == 0
        except Exception:
            return False

    def read_mounts(self) -> List[dict]:
        """
        Parses all media storage mounts and mapped mounts from .config.data and config.dat.
        Returns a list of dicts: [{'index': int, 'root': str, 'mapped': str, 'dio': int}]
        """
        mounts = []
        if os.path.exists(self.config_data_file):
            try:
                with open(self.config_data_file, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                data = {}
                for l in lines:
                    if "=" in l:
                        k, v = l.split("=", 1)
                        data[k.strip()] = v.strip()
                num = int(data.get("IoFsNum", 0))
                for i in range(1, num + 1):
                    root = data.get(f"IoFsMount_{i}", "")
                    mapped = data.get(f"IoFsMappedMount_{i}", "")
                    dio = int(data.get(f"IoFsDirectIO_{i}", 1))
                    mounts.append({"index": i, "root": root, "mapped": mapped, "dio": dio})
            except Exception as e:
                logger.warning(f"[PrefManager] Error reading .config.data: {e}")

        if not mounts and os.path.exists(self.config_dat_file):
            try:
                with open(self.config_dat_file, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                data = {}
                for l in lines:
                    if "=" in l:
                        k, v = l.split("=", 1)
                        data[k.strip()] = v.strip()
                count = int(data.get("Site.1.FS.Count", 0))
                idx = 1
                for i in range(1, count + 1):
                    root = data.get(f"Site.1.FS.{i}.Root", "")
                    mapped = data.get(f"Site.1.FS.{i}.MappedRoot", "")
                    if root and root != "ResolveVirtual":
                        mounts.append({"index": idx, "root": root, "mapped": mapped, "dio": 1})
                        idx += 1
            except Exception as e:
                logger.warning(f"[PrefManager] Error reading config.dat: {e}")

        return mounts

    def check_mount_status(self, remote_mount: str, local_mount: str) -> dict:
        """
        Analyzes whether a remote-to-local mapped mount rule is currently active,
        missing, or suffering from the common trailing-slash mismatch bug.
        """
        if not self.exists():
            return {
                "status": "not_installed",
                "badge": "❓ Preferences Not Found",
                "color": "#9ca3af",
                "details": f"DaVinci Resolve preferences directory not found at: {self.pref_dir}",
                "existing": None,
                "needs_fix": False,
            }

        mounts = self.read_mounts()
        clean_remote = remote_mount.strip().replace("\\", "/").rstrip("/").lower()

        for m in mounts:
            m_mapped = m.get("mapped", "").strip()
            if not m_mapped:
                continue
            clean_m_mapped = m_mapped.replace("\\", "/").rstrip("/").lower()

            if clean_m_mapped == clean_remote:
                m_root = m.get("root", "").strip()
                clean_m_root = m_root.replace("\\", "/").rstrip("/").lower()
                clean_target_local = local_mount.strip().replace("\\", "/").rstrip("/").lower()

                mapped_has_slash = m_mapped.endswith("/") or m_mapped.endswith("\\")
                root_has_slash = m_root.endswith("/") or m_root.endswith("\\")

                if mapped_has_slash and not root_has_slash:
                    return {
                        "status": "slash_mismatch",
                        "badge": "⚠️ Trailing Slash Bug",
                        "color": "#f59e0b",
                        "details": (
                            f"DaVinci maps '{m_mapped}' to '{m_root}', but '{m_root}' is missing a trailing slash! "
                            f"DaVinci replaces '{m_mapped}' directly, searching for corrupted paths like '{m_root}Pictures' "
                            f"instead of '{m_root}\\\\Pictures'. Files appear OFFLINE."
                        ),
                        "existing": m,
                        "needs_fix": True,
                    }

                if clean_m_root == clean_target_local:
                    return {
                        "status": "active",
                        "badge": "🟢 Active in DaVinci",
                        "color": "#10b981",
                        "details": f"Correctly configured and active in DaVinci Resolve ({m_mapped} -> {m_root}).",
                        "existing": m,
                        "needs_fix": False,
                    }
                else:
                    return {
                        "status": "different_target",
                        "badge": "⚠️ Points to Other Folder",
                        "color": "#f59e0b",
                        "details": f"Mount exists for '{m_mapped}', but points to '{m_root}' instead of '{local_mount}'.",
                        "existing": m,
                        "needs_fix": True,
                    }

        return {
            "status": "missing",
            "badge": "❌ Missing in DaVinci",
            "color": "#ef4444",
            "details": f"No mapped mount in DaVinci Resolve for '{remote_mount}'. Footage will appear offline until mapped.",
            "existing": None,
            "needs_fix": True,
        }

    def add_or_update_mount(self, remote_mount: str, local_mount: str) -> Tuple[bool, str]:
        """
        Safely adds or updates the mapped mount entry in both .config.data and config.dat.
        Guarantees trailing slash normalization to prevent corrupt path concatenation.
        Automatically creates .resolvesync.bak backups before modifying any files.
        """
        if not self.pref_dir or not os.path.isdir(self.pref_dir):
            return False, f"DaVinci preferences folder does not exist: {self.pref_dir}"

        norm_remote = remote_mount.strip()
        norm_local = local_mount.strip()

        is_windows_local = bool(re.match(r"^[A-Za-z]:[\\/]", norm_local) or norm_local.startswith("\\\\"))

        if not norm_remote.endswith("/") and not norm_remote.endswith("\\"):
            norm_remote += "/" if ("/" in norm_remote or not "\\" in norm_remote) else "\\"

        if is_windows_local:
            norm_local = norm_local.replace("/", "\\")
            if not norm_local.endswith("\\"):
                norm_local += "\\"
        else:
            norm_local = norm_local.replace("\\", "/")
            if not norm_local.endswith("/"):
                norm_local += "/"

        mounts = self.read_mounts()

        clean_remote = norm_remote.replace("\\", "/").rstrip("/").lower()
        existing_idx = None
        for i, m in enumerate(mounts):
            if m.get("mapped", "").strip().replace("\\", "/").rstrip("/").lower() == clean_remote:
                existing_idx = i
                break

        if existing_idx is not None:
            mounts[existing_idx]["root"] = norm_local
            mounts[existing_idx]["mapped"] = norm_remote
        else:
            mounts.append({
                "index": len(mounts) + 1,
                "root": norm_local,
                "mapped": norm_remote,
                "dio": 1,
            })

        # Dual-slash compatibility
        if is_windows_local and "/" in norm_remote:
            alt_remote = norm_remote.replace("/", "\\")
            if not any(m.get("mapped", "").strip() == alt_remote for m in mounts):
                mounts.append({
                    "index": len(mounts) + 1,
                    "root": norm_local,
                    "mapped": alt_remote,
                    "dio": 1,
                })
        elif not is_windows_local and "\\" in norm_remote:
            alt_remote = norm_remote.replace("\\", "/")
            if not any(m.get("mapped", "").strip() == alt_remote for m in mounts):
                mounts.append({
                    "index": len(mounts) + 1,
                    "root": norm_local,
                    "mapped": alt_remote,
                    "dio": 1,
                })

        # Backups
        try:
            if os.path.exists(self.config_data_file):
                shutil.copy2(self.config_data_file, self.config_data_file + ".resolvesync.bak")
            if os.path.exists(self.config_dat_file):
                shutil.copy2(self.config_dat_file, self.config_dat_file + ".resolvesync.bak")
        except Exception as e:
            return False, f"Could not create safety backup of DaVinci config files: {e}"

        try:
            self._write_config_data(mounts)
        except Exception as e:
            return False, f"Error updating .config.data: {e}"

        try:
            self._write_config_dat(mounts)
        except Exception as e:
            return False, f"Error updating config.dat: {e}"

        running = self.is_davinci_running()
        msg = f"DaVinci Resolve Preferences updated successfully!\n\n• Remote (Mapped Mount): {norm_remote}\n• Local  (Media Mount):  {norm_local}"
        if running:
            msg += "\n\n⚠️ DaVinci Resolve is currently OPEN.\nPlease RESTART DaVinci Resolve for the new mount to take effect!"
        else:
            msg += "\n\n✓ Mount is saved. When you open DaVinci Resolve, all clips will link automatically!"

        return True, msg

    def _write_config_data(self, mounts: List[dict]):
        """Rewrites the IoFs section in .config.data while preserving all other settings."""
        lines = []
        if os.path.exists(self.config_data_file):
            with open(self.config_data_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

        non_iofs_lines = [l for l in lines if not l.strip().startswith("IoFs")]

        new_block = [f"IoFsNum = {len(mounts)}\n"]
        for i, m in enumerate(mounts, 1):
            new_block.append(f"IoFsMount_{i} = {m.get('root', '')}\n")
            new_block.append(f"IoFsMappedMount_{i} = {m.get('mapped', '')}\n")
            new_block.append(f"IoFsDirectIO_{i} = {m.get('dio', 1)}\n")

        with open(self.config_data_file, "w", encoding="utf-8") as f:
            f.writelines(new_block + non_iofs_lines)

    def _write_config_dat(self, mounts: List[dict]):
        """Rewrites the Site.1.FS section in config.dat while preserving all other sections."""
        lines = []
        if os.path.exists(self.config_dat_file):
            with open(self.config_dat_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

        if not lines:
            return

        fs_start = None
        fs_end = None

        for i, l in enumerate(lines):
            s = l.strip()
            if s.startswith("Site.1.FS.Count"):
                fs_start = i
            if fs_start is not None and i > fs_start:
                if s and not s.startswith("Site.1.FS."):
                    fs_end = i
                    break

        if fs_start is None:
            return

        if fs_end is None:
            fs_end = len(lines)

        # Detect whether to use MacDIO (macOS) or DIO (Windows/Linux)
        is_mac = sys.platform == "darwin" or any(".MacDIO" in l for l in lines)
        dio_key = "MacDIO" if is_mac else "DIO"

        # Check for system/virtual mount entries (e.g. ResolveVirtual on Windows or /Volumes on macOS)
        system_roots = []
        for l in lines[fs_start:fs_end]:
            if ".Root = " in l:
                val = l.split(".Root = ", 1)[1].strip()
                if val in ["ResolveVirtual", "/Volumes"] and val not in system_roots:
                    system_roots.append(val)

        total_fs = len(mounts) + len(system_roots)

        new_fs_lines = [f"Site.1.FS.Count = {total_fs}\n\n"]
        for i, m in enumerate(mounts, 1):
            new_fs_lines.append(f"Site.1.FS.{i}.Type = IOFileSys\n")
            new_fs_lines.append(f"Site.1.FS.{i}.Root = {m.get('root', '')}\n")
            new_fs_lines.append(f"Site.1.FS.{i}.MappedRoot = {m.get('mapped', '')}\n")
            new_fs_lines.append(f"Site.1.FS.{i}.{dio_key} = {m.get('dio', 1)}\n")
            new_fs_lines.append(f"Site.1.FS.{i}.BrightClip = 0\n\n")

        for idx_offset, s_root in enumerate(system_roots, 1):
            v_idx = len(mounts) + idx_offset
            new_fs_lines.append(f"Site.1.FS.{v_idx}.Type = IOFileSys\n")
            new_fs_lines.append(f"Site.1.FS.{v_idx}.Root = {s_root}\n")
            new_fs_lines.append(f"Site.1.FS.{v_idx}.MappedRoot = \n")
            new_fs_lines.append(f"Site.1.FS.{v_idx}.{dio_key} = 1\n")
            new_fs_lines.append(f"Site.1.FS.{v_idx}.BrightClip = 0\n\n")

        final_lines = lines[:fs_start] + new_fs_lines + lines[fs_end:]
        with open(self.config_dat_file, "w", encoding="utf-8") as f:
            f.writelines(final_lines)


def launch_davinci_resolve(drp_path: Optional[str] = None) -> Tuple[bool, str]:
    """
    Launches the DaVinci Resolve application. If drp_path is provided, opens that project archive.
    Cross-platform support for Windows, macOS, and Linux.
    """
    import subprocess
    try:
        if sys.platform == "darwin":
            cmd = ["open", "-a", "DaVinci Resolve"]
            if drp_path and os.path.exists(drp_path):
                cmd.append(drp_path)
            subprocess.Popen(cmd)
            return True, "Launching DaVinci Resolve on macOS..."
        elif sys.platform == "win32":
            win_candidates = [
                r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe",
                r"C:\Program Files\Blackmagic Design\DaVinci Resolve Studio\Resolve.exe",
            ]
            exe_path = next((p for p in win_candidates if os.path.exists(p)), None)
            if not exe_path:
                prog = os.environ.get("PROGRAMFILES", r"C:\Program Files")
                cand = os.path.join(prog, "Blackmagic Design", "DaVinci Resolve", "Resolve.exe")
                if os.path.exists(cand):
                    exe_path = cand

            if not exe_path:
                return False, "Could not locate DaVinci Resolve installation path."

            cmd = [exe_path]
            if drp_path and os.path.exists(drp_path):
                cmd.append(drp_path)
            subprocess.Popen(cmd)
            return True, "Launching DaVinci Resolve on Windows..."
        else:
            cmd = ["/opt/resolve/bin/resolve"]
            if drp_path and os.path.exists(drp_path):
                cmd.append(drp_path)
            subprocess.Popen(cmd)
            return True, "Launching DaVinci Resolve on Linux..."
    except Exception as e:
        return False, f"Failed to launch DaVinci Resolve: {e}"


# ---------------------------------------------------------------------------
# ResolveSync Application Controller
# ---------------------------------------------------------------------------

class ResolveSyncApp:
    """Coordinates parsing, path mapping, local/remote inventory, and bidirectional sync."""

    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.config = self._load_config(config_path)

        sync_opts = self.config.get("sync_options", {})
        allowed = set(sync_opts.get("allowed_extensions", []))
        excluded = set(sync_opts.get("excluded_extensions", []))

        self.parser = DRPParser(allowed_exts=allowed, excluded_exts=excluded)
        self.mapper = PathMapper.from_config(self.config)
        self.verify_sizes = sync_opts.get("verify_file_sizes", True)
        self.sync_root = self.config.get("sync_root_folder") or sync_opts.get("download_folder")

    @staticmethod
    def _load_config(path: str) -> dict:
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Configuration file not found: {path}\n"
                "Tip: Copy 'config.example.json' to 'config.json' or use --generate-config."
            )
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as jde:
            raise ValueError(f"Malformed JSON in configuration file '{path}': {jde}")

    def analyze_inventory(
        self,
        drp_path: Optional[str] = None,
        file_paths: Optional[List[str]] = None,
        check_remote: bool = True,
        sync_root: Optional[str] = None,
        media_filter: str = "all",  # "all", "proxies_only", "originals_only"
    ) -> List[MediaItem]:
        """
        Parses DRP or processes a live list of media file paths, maps paths (with zero-config
        auto-mapping), checks local file status, and optionally queries the remote server
        to establish full media availability. Supports proxy-only or originals-only filtering.
        """
        if file_paths is not None:
            media_paths = file_paths
        elif drp_path:
            media_paths = self.parser.extract_media_paths(drp_path)
        else:
            raise ValueError("Either 'drp_path' or 'file_paths' must be provided to analyze inventory.")

        items: List[MediaItem] = []
        active_sync_root = sync_root or self.sync_root

        for original_path in media_paths:
            item = MediaItem(drp_path=original_path)
            local_p, remote_p, matched_rule = self.mapper.map_path(original_path, sync_root=active_sync_root)

            if not matched_rule:
                item.status = "UNMAPPED"
                item.error_message = "No matching path_mapping rule in config.json"
            else:
                item.local_path = local_p
                item.remote_path = remote_p
                item.matched_rule = matched_rule.name

                # Check local status
                if os.path.exists(local_p):
                    item.local_exists = True
                    item.file_size_local = os.path.getsize(local_p)
                else:
                    item.local_exists = False

            items.append(item)

        # 2. Automatically discover local companion proxies (Proxy/ subfolders, _Proxy suffixes)
        seen_local = set(i.local_path for i in items if i.local_path)
        proxy_items = []
        for orig_item in list(items):
            if not orig_item.local_path:
                continue
            found_proxies = MediaItem.find_local_proxies(orig_item.local_path)
            for p_loc in found_proxies:
                if p_loc in seen_local:
                    continue
                seen_local.add(p_loc)
                _, p_rem, p_rule = self.mapper.map_path(p_loc, sync_root=active_sync_root)
                p_item = MediaItem(
                    drp_path=p_loc,
                    local_path=p_loc,
                    remote_path=p_rem,
                    is_proxy=True,
                    local_exists=True,
                    file_size_local=os.path.getsize(p_loc) if os.path.exists(p_loc) else 0,
                    matched_rule=p_rule.name if p_rule else orig_item.matched_rule,
                    proxy_path=p_loc,
                )
                orig_item.proxy_path = p_loc
                proxy_items.append(p_item)

        items.extend(proxy_items)

        # 3. Check remote status via HTTP Hub or SFTP (including remote proxy discovery)
        if check_remote:
            server_cfg = self.config.get("server", {})
            server_url = server_cfg.get("server_url") or server_cfg.get("url")
            host = server_cfg.get("host", "")
            if not server_url and (host.startswith("http://") or host.startswith("https://")):
                server_url = host

            if server_url:
                # High-performance batch check via TrueNAS Docker container
                try:
                    http_engine = HTTPServerSyncEngine(server_url)
                    remote_paths = [i.remote_path for i in items if i.status != "UNMAPPED" and i.remote_path]

                    # Also collect potential remote proxy paths for originals that do not have a local proxy
                    remote_cand_map: Dict[str, MediaItem] = {}
                    for item in items:
                        if not item.is_proxy and not item.proxy_path and item.remote_path:
                            cands = MediaItem.get_candidate_remote_proxy_paths(item.remote_path)
                            for c in cands:
                                remote_cand_map[c] = item
                                remote_paths.append(c)

                    results = http_engine.check_remote_batch(remote_paths)

                    for item in items:
                        if item.status == "UNMAPPED" or not item.remote_path:
                            continue
                        info = results.get(item.remote_path, {})
                        if info.get("exists"):
                            item.remote_exists = True
                            item.file_size_remote = info.get("size", 0)
                        else:
                            item.remote_exists = False

                        if item.local_exists and item.remote_exists:
                            if self.verify_sizes and item.file_size_local != item.file_size_remote:
                                item.status = "SIZE_MISMATCH"
                            else:
                                item.status = "SYNCED"
                        elif not item.local_exists and item.remote_exists:
                            item.status = "NEEDS_DOWNLOAD"
                        elif item.local_exists and not item.remote_exists:
                            item.status = "NEEDS_UPLOAD"
                        else:
                            item.status = "MISSING_EVERYWHERE"

                    # Discover any candidate remote proxies that exist on TrueNAS
                    seen_remotes = set(i.remote_path for i in items if i.remote_path)
                    for cand_p, parent_item in remote_cand_map.items():
                        if cand_p in seen_remotes:
                            continue
                        info = results.get(cand_p, {})
                        if info.get("exists"):
                            seen_remotes.add(cand_p)
                            cand_local, _, cand_rule = self.mapper.map_path(cand_p, sync_root=active_sync_root)
                            loc_exists = os.path.exists(cand_local) if cand_local else False
                            p_item = MediaItem(
                                drp_path=cand_p,
                                local_path=cand_local,
                                remote_path=cand_p,
                                is_proxy=True,
                                local_exists=loc_exists,
                                remote_exists=True,
                                file_size_remote=info.get("size", 0),
                                file_size_local=os.path.getsize(cand_local) if loc_exists else 0,
                                status="SYNCED" if loc_exists else "NEEDS_DOWNLOAD",
                                matched_rule=cand_rule.name if cand_rule else parent_item.matched_rule,
                                proxy_path=cand_local if loc_exists else cand_p,
                            )
                            parent_item.proxy_path = p_item.proxy_path
                            items.append(p_item)

                except Exception as e:
                    logger.warning(f"Could not connect to TrueNAS Hub API: {e}")
                    for item in items:
                        if item.status != "UNMAPPED":
                            item.status = "EXISTS_LOCAL" if item.local_exists else "PENDING_CHECK"

            elif server_cfg.get("host") and server_cfg.get("username"):
                try:
                    with SFTPSyncEngine(server_cfg) as sftp:
                        for item in items:
                            if item.status == "UNMAPPED" or not item.remote_path:
                                continue

                            remote_size = sftp.get_remote_file_size(item.remote_path)
                            if remote_size is not None:
                                item.remote_exists = True
                                item.file_size_remote = remote_size
                            else:
                                item.remote_exists = False

                            # Establish status
                            if item.local_exists and item.remote_exists:
                                if self.verify_sizes and item.file_size_local != item.file_size_remote:
                                    item.status = "SIZE_MISMATCH"
                                else:
                                    item.status = "SYNCED"
                            elif not item.local_exists and item.remote_exists:
                                item.status = "NEEDS_DOWNLOAD"
                            elif item.local_exists and not item.remote_exists:
                                item.status = "NEEDS_UPLOAD"
                            else:
                                item.status = "MISSING_EVERYWHERE"
                except Exception as e:
                    logger.warning(f"Could not connect to SFTP to verify remote files: {e}")
                    for item in items:
                        if item.status != "UNMAPPED":
                            item.status = "EXISTS_LOCAL" if item.local_exists else "PENDING_CHECK"

        # 4. Apply Proxy / Camera Originals filter
        if media_filter == "proxies_only":
            items = [i for i in items if i.is_proxy]
        elif media_filter == "originals_only":
            items = [i for i in items if not i.is_proxy]

        return items

    def run(
        self,
        drp_path: Optional[str] = None,
        file_paths: Optional[List[str]] = None,
        mode: str = "sync",
        dry_run: bool = False,
        force: bool = False,
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        sync_root: Optional[str] = None,
        media_filter: str = "all",
        selected_items: Optional[List[str]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> int:
        """
        Executes synchronization based on mode:
          - 'sync' (default / bidirectional): Downloads missing local files AND uploads missing remote files.
          - 'download' / 'pull': Downloads missing local files from NAS.
          - 'upload' / 'push': Uploads missing remote files to NAS.
        """
        def emit(msg: str):
            print(msg)
            if log_callback:
                try:
                    log_callback(msg)
                except Exception:
                    pass

        mode = mode.lower()
        if mode in ("pull", "get"):
            mode = "download"
        elif mode in ("push", "put"):
            mode = "upload"
        elif mode in ("two-way", "bidirectional"):
            mode = "sync"

        print("\n" + "=" * 65)
        print(f"     ResolveSync - Media Sync Engine [MODE: {mode.upper()}] [FILTER: {media_filter.upper()}]")
        print("=" * 65 + "\n")

        # 1. Analyze Inventory with remote checking
        logger.info("Analyzing project inventory across local drive and remote NAS...")
        items = self.analyze_inventory(
            drp_path=drp_path,
            file_paths=file_paths,
            check_remote=True,
            sync_root=sync_root,
            media_filter=media_filter,
        )

        if selected_items is not None:
            sel_norm = set(os.path.normpath(p).lower() if ("\\" in p or "/" in p) else p.lower() for p in selected_items)
            items = [
                i for i in items
                if (i.local_path and os.path.normpath(i.local_path).lower() in sel_norm)
                or (i.drp_path and os.path.normpath(i.drp_path).lower() in sel_norm)
                or (i.remote_path and i.remote_path.lower() in sel_norm)
                or (os.path.basename(i.local_path or i.drp_path).lower() in sel_norm)
            ]
            emit(f"✓ Selective Sync: Filtered to {len(items)} selected file(s).")

        unmapped = [i for i in items if i.status == "UNMAPPED"]
        synced = [i for i in items if i.status == "SYNCED"]
        to_download = [i for i in items if i.status == "NEEDS_DOWNLOAD" or (force and i.remote_exists)]
        to_upload = [i for i in items if i.status == "NEEDS_UPLOAD" or (force and i.local_exists)]
        missing_both = [i for i in items if i.status == "MISSING_EVERYWHERE"]

        if unmapped:
            logger.warning(f"{len(unmapped)} media file(s) could not be mapped to storage paths!")
            emit(f"⚠️ {len(unmapped)} media file(s) could not be mapped to storage paths!")
            for item in unmapped:
                logger.warning(f"  Unmapped DRP path: {item.drp_path}")
                emit(f"  • Unmapped: {item.drp_path}")

        print("-" * 65)
        print(f"Total Media Items:        {len(items)}")
        print(f"Already Synced (Both):    {len(synced)}")
        print(f"Available to Download:    {len(to_download)} (Missing Locally)")
        print(f"Available to Upload:      {len(to_upload)} (Missing on NAS)")
        if missing_both:
            print(f"Missing Everywhere:       {len(missing_both)} [!]")
        if unmapped:
            print(f"Unmapped Rules:           {len(unmapped)}")
        print("-" * 65)

        # Filter actions according to active mode
        actions_download = to_download if mode in ("sync", "download") else []
        actions_upload = to_upload if mode in ("sync", "upload") else []

        if not actions_download and not actions_upload:
            if unmapped:
                logger.warning("No files queued, but unmapped rules exist in config.json.")
                emit("⚠️ No files queued to transfer because all items are unmapped. Check Settings!")
                return 2
            logger.info("All media files are fully synchronized! Nothing to transfer.")
            emit("✓ All media files are fully synchronized! Nothing to transfer.")
            return 0

        # 2. Dry Run
        if dry_run:
            print(f"\n[DRY RUN MODE: {mode.upper()}] The following operations would take place:\n")
            if actions_download:
                print(f"--- ⬇️ DOWNLOADS ({len(actions_download)} files from NAS -> Local) ---")
                for idx, item in enumerate(actions_download, 1):
                    print(f" [{idx}] {os.path.basename(item.drp_path)}")
                    print(f"     Remote: {item.remote_path}")
                    print(f"     Local:  {item.local_path}\n")

            if actions_upload:
                print(f"--- ⬆️ UPLOADS ({len(actions_upload)} files from Local -> NAS) ---")
                for idx, item in enumerate(actions_upload, 1):
                    print(f" [{idx}] {os.path.basename(item.drp_path)}")
                    print(f"     Local:  {item.local_path}")
                    print(f"     Remote: {item.remote_path}\n")

            print(f"Dry run complete. No files were transferred.")
            return 0

        # 3. Perform Transfers via HTTP Hub or SFTP
        server_cfg = self.config.get("server", {})
        server_url = server_cfg.get("server_url") or server_cfg.get("url")
        host = server_cfg.get("host", "")
        if not server_url and (host.startswith("http://") or host.startswith("https://")):
            server_url = host

        successful_downloads = 0
        failed_downloads = 0
        successful_uploads = 0
        failed_uploads = 0

        if server_url:
            # --- HTTP REST Mode (Direct to TrueNAS Docker Container) ---
            http_engine = HTTPServerSyncEngine(server_url)
            print(f"\n[+] Connected to TrueNAS Hub at {server_url}")

            # --- Execute Downloads ---
            if actions_download:
                print(f"\n--- ⬇️ DOWNLOADING {len(actions_download)} MISSING LOCAL MEDIA FROM TRUENAS ---")
                for idx, item in enumerate(actions_download, 1):
                    if is_cancelled and is_cancelled():
                        emit("⏹️ Synchronization cancelled by user.")
                        return 130
                    filename = os.path.basename(item.local_path)
                    try:
                        http_engine.download_file(
                            remote_path=item.remote_path,
                            local_path=item.local_path,
                            expected_size=item.file_size_remote or None,
                            progress_callback=progress_callback,
                            is_cancelled=is_cancelled,
                        )
                        item.status = "DOWNLOAD_SUCCESS"
                        item.local_exists = True
                        successful_downloads += 1
                    except SyncCancelledError:
                        emit(f"⏹️ Transfer cancelled while downloading {filename}.")
                        return 130
                    except Exception as err:
                        logger.error(f"Failed to download {filename}: {err}")
                        item.status = "ERROR"
                        item.error_message = str(err)
                        failed_downloads += 1

            # --- Execute Uploads ---
            if actions_upload:
                print(f"\n--- ⬆️ UPLOADING {len(actions_upload)} MISSING LOCAL MEDIA TO TRUENAS ---")
                for idx, item in enumerate(actions_upload, 1):
                    if is_cancelled and is_cancelled():
                        emit("⏹️ Synchronization cancelled by user.")
                        return 130
                    filename = os.path.basename(item.local_path)
                    try:
                        http_engine.upload_file(
                            local_path=item.local_path,
                            remote_path=item.remote_path,
                            expected_size=item.file_size_local or None,
                            progress_callback=progress_callback,
                            is_cancelled=is_cancelled,
                        )
                        item.status = "UPLOAD_SUCCESS"
                        item.remote_exists = True
                        successful_uploads += 1
                    except SyncCancelledError:
                        emit(f"⏹️ Transfer cancelled while uploading {filename}.")
                        return 130
                    except Exception as err:
                        logger.error(f"Failed to upload {filename}: {err}")
                        item.status = "ERROR"
                        item.error_message = str(err)
                        failed_uploads += 1

        elif server_cfg.get("host") and server_cfg.get("username"):
            # --- SFTP Fallback Mode ---
            try:
                with SFTPSyncEngine(server_cfg) as sftp:
                    if actions_download:
                        print(f"\n--- ⬇️ DOWNLOADING {len(actions_download)} MISSING LOCAL MEDIA (SFTP) ---")
                        for idx, item in enumerate(actions_download, 1):
                            if is_cancelled and is_cancelled():
                                emit("⏹️ Synchronization cancelled by user.")
                                return 130
                            filename = os.path.basename(item.local_path)
                            try:
                                sftp.download_file(
                                    remote_path=item.remote_path,
                                    local_path=item.local_path,
                                    expected_size=item.file_size_remote or None,
                                    progress_callback=progress_callback,
                                    is_cancelled=is_cancelled,
                                )
                                item.status = "DOWNLOAD_SUCCESS"
                                item.local_exists = True
                                successful_downloads += 1
                            except SyncCancelledError:
                                emit(f"⏹️ Transfer cancelled while downloading {filename}.")
                                return 130
                            except Exception as err:
                                logger.error(f"Failed to download {filename}: {err}")
                                item.status = "ERROR"
                                item.error_message = str(err)
                                failed_downloads += 1

                    if actions_upload:
                        print(f"\n--- ⬆️ UPLOADING {len(actions_upload)} MISSING NAS MEDIA (SFTP) ---")
                        for idx, item in enumerate(actions_upload, 1):
                            if is_cancelled and is_cancelled():
                                emit("⏹️ Synchronization cancelled by user.")
                                return 130
                            filename = os.path.basename(item.local_path)
                            try:
                                sftp.upload_file(
                                    local_path=item.local_path,
                                    remote_path=item.remote_path,
                                    expected_size=item.file_size_local or None,
                                    progress_callback=progress_callback,
                                    is_cancelled=is_cancelled,
                                )
                                item.status = "UPLOAD_SUCCESS"
                                item.remote_exists = True
                                successful_uploads += 1
                            except SyncCancelledError:
                                emit(f"⏹️ Transfer cancelled while uploading {filename}.")
                                return 130
                            except Exception as err:
                                logger.error(f"Failed to upload {filename}: {err}")
                                item.status = "ERROR"
                                item.error_message = str(err)
                                failed_uploads += 1

            except (KeyboardInterrupt, SyncCancelledError):
                print("\n[!] Transfer aborted by user. Cleaned up active files.")
                emit("⏹️ Synchronization cancelled by user.")
                return 130
            except Exception as e:
                logger.error(f"Fatal SFTP sync failure: {e}")
                return 1
        else:
            logger.error("No valid server configuration in config.json (server_url or host missing).")
            return 1

        # 4. Summary Report
        print("\n" + "=" * 65)
        print("                      SYNC SUMMARY REPORT")
        print("=" * 65)
        print(f"Total Referenced Media:     {len(items)}")
        print(f"Already Synced:             {len(synced)}")
        if mode in ("sync", "download"):
            print(f"Downloaded Successfully:    {successful_downloads} / {len(actions_download)}")
            if failed_downloads > 0:
                print(f"Download Failures:          {failed_downloads}")
        if mode in ("sync", "upload"):
            print(f"Uploaded Successfully:      {successful_uploads} / {len(actions_upload)}")
            if failed_uploads > 0:
                print(f"Upload Failures:            {failed_uploads}")
        if missing_both:
            print(f"Missing on Both Sides:      {len(missing_both)} [!]")
        if unmapped:
            print(f"Unmapped Rules:             {len(unmapped)}")
        print("=" * 65)

        if failed_downloads > 0 or failed_uploads > 0 or unmapped:
            return 2

        print("\nAll operations completed successfully!\n")
        return 0


# ---------------------------------------------------------------------------
# CLI & Entry Point
# ---------------------------------------------------------------------------

def generate_default_config(target_path: str = "config.json"):
    """Creates a pre-configured template config.json in the current working directory."""
    if os.path.exists(target_path):
        print(f"Error: {target_path} already exists. Refusing to overwrite.")
        return

    example_content = {
        "server": {
            "host": "192.168.1.100",
            "port": 22,
            "username": "editor",
            "password": "YOUR_REMOTE_PASSWORD_OR_LEAVE_EMPTY",
            "key_file": "~/.ssh/id_ed25519",
            "key_passphrase": "",
            "timeout_seconds": 30,
        },
        "path_mappings": [
            {
                "name": "Windows Studio to Mac/Linux Local & Remote",
                "drp_prefix": "D:\\Projects\\Video1",
                "local_prefix": "/Users/Me/Projects/Video1",
                "remote_prefix": "/srv/media/projects/Video1",
            },
            {
                "name": "Audio Library",
                "drp_prefix": "E:\\Audio",
                "local_prefix": "/Users/Me/Audio",
                "remote_prefix": "/srv/media/audio",
            },
        ],
        "sync_options": {
            "verify_file_sizes": True,
            "skip_render_cache": True,
            "allowed_extensions": [
                ".mov", ".mp4", ".mxf", ".braw", ".r3d", ".ari", ".wav",
                ".mp3", ".aac", ".flac", ".png", ".jpg", ".jpeg", ".tiff",
                ".exr", ".dng",
            ],
            "excluded_extensions": [
                ".dvcc", ".drx", ".dtl", ".gallery", ".tmp", ".dat",
                ".cache", ".xml", ".db", ".idx",
            ],
        },
    }

    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(example_content, f, indent=2)

    print(f"Successfully generated template configuration: {target_path}")


def main():
    parser = argparse.ArgumentParser(
        description="ResolveSync: Automate DaVinci Resolve media synchronization via self-hosted SFTP.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Bidirectional sync (Downloads missing local, uploads missing remote NAS media):
  python resolvesync.py my_project.drp --mode sync

  # Pull only (download missing files from NAS):
  python resolvesync.py my_project.drp --mode download

  # Push only (upload newly added local media to NAS):
  python resolvesync.py my_project.drp --mode upload

  # Dry-run: preview files to be transferred without transferring
  python resolvesync.py my_project.drp --dry-run

  # Launch Web Dashboard:
  python resolvesync.py --web

  # Diagnostic inspect: view all XML files, tags, and media paths inside the .drp
  python resolvesync.py my_project.drp --inspect
        """,
    )

    parser.add_argument("drp_path", nargs="?", help="Path to the DaVinci Resolve project (.drp) file.")
    parser.add_argument("-c", "--config", default="config.json", help="Path to the JSON configuration file (default: config.json).")
    parser.add_argument(
        "-m", "--mode",
        choices=["sync", "download", "upload", "pull", "push"],
        default="sync",
        help="Sync direction: 'sync' (bidirectional), 'download' (NAS -> local), or 'upload' (local -> NAS). Default: sync.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Simulate the sync process and print missing files without downloading/uploading.")
    parser.add_argument("--inspect", action="store_true", help="Inspect .drp ZIP contents and XML tags to discover internal media paths.")
    parser.add_argument("--force", action="store_true", help="Force re-transfer of files even if they already exist.")
    parser.add_argument("--web", action="store_true", help="Launch the Web UI management dashboard.")
    parser.add_argument("--port", type=int, default=5000, help="Port for the Web UI (default: 5000).")
    parser.add_argument("--generate-config", action="store_true", help="Generate a starter config.json template.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable detailed debug logging.")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.generate_config:
        generate_default_config()
        sys.exit(0)

    if args.web:
        import web_server
        web_server.start_server(config_path=args.config, port=args.port)
        sys.exit(0)

    if not args.drp_path:
        parser.print_help()
        print("\nError: Please provide a .drp project file, use --web for the dashboard, or use --generate-config.")
        sys.exit(1)

    if args.inspect:
        drp_parser = DRPParser()
        drp_parser.inspect_drp(args.drp_path)
        sys.exit(0)

    try:
        app = ResolveSyncApp(config_path=args.config)
        exit_code = app.run(
            drp_path=args.drp_path,
            mode=args.mode,
            dry_run=args.dry_run,
            force=args.force,
        )
        sys.exit(exit_code)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
