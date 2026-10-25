#!/usr/bin/env python3
"""
ResolveSync Desktop Application (Windows & macOS)
=================================================
A native, cross-platform desktop application for DaVinci Resolve media synchronization.
Connects your editing workstation (Windows, Mac, or remote) to your TrueNAS server,
auto-discovers projects from live DaVinci Resolve instances and databases,
and synchronizes media in real-time with zero-configuration path mapping.
"""

import json
import logging
import os
import platform
import posixpath
import re
import sys
import threading
import time
import webbrowser
from typing import Dict, List, Optional, Tuple

# Safeguard UTF-8 console encoding on Windows
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import tkinter as tk
from tkinter import filedialog, messagebox, ttk, font as tkfont

# Attempt to load customtkinter or auto-install on macOS/Linux/Windows
HAS_CUSTOMTKINTER = False
ctk = None

try:
    import customtkinter as _ctk
    ctk = _ctk
    HAS_CUSTOMTKINTER = True
except ImportError:
    # Try automatic pip install for stock macOS / remote workstations
    try:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "--user", "customtkinter", "requests"])
        import customtkinter as _ctk
        ctk = _ctk
        HAS_CUSTOMTKINTER = True
    except Exception:
        HAS_CUSTOMTKINTER = False

# Fallback: Robust Tkinter Compatibility Shim (Never crashes on bare-bones systems)
if not HAS_CUSTOMTKINTER:
    class _TkinterShim:
        StringVar = tk.StringVar
        BooleanVar = tk.BooleanVar
        IntVar = tk.IntVar

        @staticmethod
        def set_appearance_mode(m): pass
        @staticmethod
        def set_default_color_theme(t): pass

        class CTk(tk.Tk):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.configure(bg="#18191f")

        class CTkToplevel(tk.Toplevel):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.configure(bg="#18191f")

        class CTkFont:
            def __new__(cls, family="Helvetica" if sys.platform == "darwin" else "Segoe UI", size=11, weight="normal"):
                return (family, size, weight)

        class CTkFrame(tk.Frame):
            def __init__(self, master=None, fg_color=None, corner_radius=None, border_color=None, border_width=0, **kwargs):
                kwargs.pop("corner_radius", None)
                kwargs.pop("border_color", None)
                kwargs.pop("border_width", None)
                if fg_color and fg_color != "transparent":
                    kwargs["bg"] = fg_color
                elif not kwargs.get("bg"):
                    kwargs["bg"] = "#1c1d24"
                super().__init__(master, **kwargs)

            def configure(self, **kwargs):
                if "fg_color" in kwargs:
                    c = kwargs.pop("fg_color")
                    if c and c != "transparent":
                        kwargs["bg"] = c
                kwargs.pop("corner_radius", None)
                kwargs.pop("border_color", None)
                kwargs.pop("border_width", None)
                super().configure(**kwargs)

        class CTkScrollableFrame(tk.Frame):
            def __init__(self, master=None, width=None, height=None, fg_color=None, **kwargs):
                kwargs.pop("corner_radius", None)
                kwargs.pop("border_color", None)
                kwargs.pop("border_width", None)
                if fg_color and fg_color != "transparent":
                    kwargs["bg"] = fg_color
                elif not kwargs.get("bg"):
                    kwargs["bg"] = "#18191f"
                super().__init__(master, **kwargs)

            def configure(self, **kwargs):
                if "fg_color" in kwargs:
                    c = kwargs.pop("fg_color")
                    if c and c != "transparent":
                        kwargs["bg"] = c
                kwargs.pop("corner_radius", None)
                kwargs.pop("border_color", None)
                super().configure(**kwargs)

        class CTkLabel(tk.Label):
            def __init__(self, master=None, text="", font=None, text_color=None, fg_color=None, corner_radius=None, justify="center", wraplength=0, **kwargs):
                kwargs.pop("corner_radius", None)
                if text_color:
                    kwargs["fg"] = text_color
                else:
                    kwargs["fg"] = "#e5e7eb"
                if fg_color and fg_color != "transparent":
                    kwargs["bg"] = fg_color
                elif not kwargs.get("bg"):
                    kwargs["bg"] = master.cget("bg") if hasattr(master, "cget") else "#1c1d24"
                if font:
                    kwargs["font"] = font
                super().__init__(master, text=text, justify=justify, wraplength=wraplength, **kwargs)

            def configure(self, **kwargs):
                if "text_color" in kwargs:
                    kwargs["fg"] = kwargs.pop("text_color")
                if "fg_color" in kwargs:
                    c = kwargs.pop("fg_color")
                    if c and c != "transparent":
                        kwargs["bg"] = c
                kwargs.pop("corner_radius", None)
                super().configure(**kwargs)

        class CTkButton(tk.Button):
            def __init__(self, master=None, text="", command=None, fg_color=None, hover_color=None, text_color=None, font=None, width=None, height=None, state="normal", **kwargs):
                kwargs.pop("hover_color", None)
                kwargs.pop("corner_radius", None)
                kwargs.pop("border_width", None)
                kwargs.pop("border_color", None)
                if text_color:
                    kwargs["fg"] = text_color
                else:
                    kwargs["fg"] = "#ffffff"
                if fg_color and fg_color != "transparent":
                    kwargs["bg"] = fg_color
                else:
                    kwargs["bg"] = "#2563eb"
                if font:
                    kwargs["font"] = font
                if width:
                    kwargs["width"] = max(1, width // 10)
                kwargs["relief"] = "flat"
                kwargs["activebackground"] = "#1d4ed8"
                kwargs["activeforeground"] = "#ffffff"
                super().__init__(master, text=text, command=command, state=state, **kwargs)

            def configure(self, **kwargs):
                if "fg_color" in kwargs:
                    c = kwargs.pop("fg_color")
                    if c and c != "transparent":
                        kwargs["bg"] = c
                if "text_color" in kwargs:
                    kwargs["fg"] = kwargs.pop("text_color")
                kwargs.pop("hover_color", None)
                kwargs.pop("corner_radius", None)
                super().configure(**kwargs)

        class CTkEntry(tk.Entry):
            def __init__(self, master=None, placeholder_text="", font=None, show="", **kwargs):
                kwargs.pop("corner_radius", None)
                kwargs.pop("border_color", None)
                kwargs.pop("border_width", None)
                kwargs.pop("fg_color", None)
                if font:
                    kwargs["font"] = font
                if show:
                    kwargs["show"] = show
                kwargs["bg"] = "#22232a"
                kwargs["fg"] = "#ffffff"
                kwargs["insertbackground"] = "#ffffff"
                super().__init__(master, **kwargs)

        class CTkComboBox(ttk.Combobox):
            def __init__(self, master=None, values=None, width=None, **kwargs):
                kwargs.pop("corner_radius", None)
                kwargs.pop("fg_color", None)
                kwargs.pop("button_color", None)
                kwargs.pop("border_color", None)
                kwargs.pop("border_width", None)
                super().__init__(master, values=values or [], **kwargs)

        class CTkProgressBar(ttk.Progressbar):
            def __init__(self, master=None, height=None, **kwargs):
                kwargs.pop("corner_radius", None)
                kwargs.pop("border_color", None)
                kwargs.pop("progress_color", None)
                super().__init__(master, orient="horizontal", mode="determinate", maximum=1.0, **kwargs)

            def set(self, val):
                self["value"] = val

        class CTkTextbox(tk.Text):
            def __init__(self, master=None, font=None, fg_color=None, text_color=None, **kwargs):
                kwargs.pop("corner_radius", None)
                kwargs.pop("border_color", None)
                if font:
                    kwargs["font"] = font
                kwargs["bg"] = fg_color if fg_color and fg_color != "transparent" else "#121316"
                kwargs["fg"] = text_color if text_color else "#d1d5db"
                kwargs["insertbackground"] = "#ffffff"
                super().__init__(master, **kwargs)

        class CTkSegmentedButton(tk.Frame):
            def __init__(self, master=None, values=None, variable=None, command=None, **kwargs):
                kwargs.pop("corner_radius", None)
                kwargs.pop("selected_color", None)
                kwargs.pop("selected_hover_color", None)
                kwargs.pop("unselected_color", None)
                super().__init__(master, bg="#1c1d24", **kwargs)
                self.values = values or []
                self.variable = variable or tk.StringVar()
                self.command = command
                self.buttons = {}
                for v in self.values:
                    btn = tk.Button(
                        self,
                        text=v,
                        command=lambda val=v: self._on_btn_click(val),
                        bg="#2d3039",
                        fg="#e5e7eb",
                        relief="flat",
                        activebackground="#2563eb",
                        activeforeground="#ffffff",
                        padx=10,
                        pady=4
                    )
                    btn.pack(side="left", padx=2)
                    self.buttons[v] = btn

            def _on_btn_click(self, val):
                self.set(val)
                if self.command:
                    self.command(val)

            def set(self, val):
                self.variable.set(val)
                for v, btn in self.buttons.items():
                    if v == val:
                        btn.configure(bg="#2563eb", fg="#ffffff", relief="sunken")
                    else:
                        btn.configure(bg="#2d3039", fg="#e5e7eb", relief="flat")

            def get(self):
                return self.variable.get()

    ctk = _TkinterShim

from resolvesync import (
    DaVinciPostgresReader,
    DaVinciPreferencesManager,
    DaVinciProjectDiscoverer,
    DRPParser,
    HTTPServerSyncEngine,
    MediaItem,
    PathMapper,
    ResolveSyncApp,
    SFTPSyncEngine,
    SyncCancelledError,
    get_debug_log_path,
    launch_davinci_resolve,
    set_debug_logging,
    setup_file_logger,
    __version__,
)

# Initialize persistent file logger (Default: verbose=False for standard INFO/ERROR logs)
LOG_FILE_PATH = setup_file_logger(verbose=False)
logger = logging.getLogger("ResolveSyncDesktop")

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"
OS_NAME = "macOS" if IS_MAC else ("Windows" if IS_WIN else "Linux")


def open_log_file():
    """Opens the persistent debug log file in system default text editor."""
    log_path = get_debug_log_path()
    logger.info(f"Opening debug log file: {log_path}")
    if not os.path.exists(log_path):
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("=== ResolveSync Debug Log File ===\n")
        except Exception:
            pass
    try:
        if sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", log_path])
        elif sys.platform == "win32":
            os.startfile(log_path)
        else:
            import subprocess
            subprocess.Popen(["xdg-open", log_path])
    except Exception as ex:
        logger.error(f"Failed to open log file automatically: {ex}")
        messagebox.showinfo("Log File Path", f"Log file is located at:\n{log_path}")


def choose_drp_file(parent=None) -> Optional[str]:
    """Selects a .drp project archive with platform-native dialogs and fallback."""
    logger.info("User opened DRP file picker dialog...")
    if sys.platform == "darwin":
        # 1. Native macOS Finder file picker via osascript (guarantees .drp is selectable!)
        try:
            import subprocess
            cmd = 'osascript -e \'POSIX path of (choose file with prompt "Select DaVinci Resolve Project (.drp)" of type {"drp", "zip", "public.data"})\''
            out = subprocess.check_output(cmd, shell=True, timeout=60).decode("utf-8").strip()
            if out and os.path.exists(out):
                logger.info(f"DRP selected via macOS osascript: {out}")
                return out
        except Exception as e:
            logger.debug(f"macOS osascript file picker: {e}")

        # 2. Tkinter file picker with valid macOS filetypes
        try:
            path = filedialog.askopenfilename(
                parent=parent,
                title="Select DaVinci Resolve Project File",
                filetypes=[
                    ("DaVinci Resolve Project", ".drp"),
                    ("ZIP Archive", ".zip"),
                    ("All Files", "*"),
                ],
            )
            if path and os.path.exists(path):
                logger.info(f"DRP selected via macOS filedialog: {path}")
                return path
        except Exception as e:
            logger.debug(f"macOS filedialog picker error: {e}")

    # Windows / Linux standard file picker
    try:
        path = filedialog.askopenfilename(
            parent=parent,
            title="Select DaVinci Resolve Project File",
            filetypes=[
                ("Resolve Project Archives", "*.drp;*.zip"),
                ("DaVinci Resolve Projects", "*.drp"),
                ("ZIP Archives", "*.zip"),
                ("All Files", "*.*"),
            ],
        )
        if path and os.path.exists(path):
            logger.info(f"DRP selected via standard filedialog: {path}")
            return path
    except Exception as e:
        logger.error(f"File dialog error: {e}")

    logger.info("DRP selection was cancelled or returned empty.")
    return None


def choose_destination_folder(title="Select Destination Folder", parent=None) -> Optional[str]:
    """Opens platform-native folder picker."""
    logger.info(f"User opened folder picker: {title}")
    if sys.platform == "darwin":
        try:
            import subprocess
            cmd = f'osascript -e \'POSIX path of (choose folder with prompt "{title}")\''
            out = subprocess.check_output(cmd, shell=True, timeout=60).decode("utf-8").strip()
            if out and os.path.isdir(out):
                logger.info(f"Folder selected via macOS osascript: {out}")
                return out
        except Exception as e:
            logger.debug(f"macOS osascript folder picker: {e}")

    try:
        folder = filedialog.askdirectory(title=title, parent=parent)
        if folder and os.path.isdir(folder):
            logger.info(f"Folder selected via filedialog: {folder}")
            return folder
    except Exception as e:
        logger.error(f"Folder picker error: {e}")

    logger.info("Folder selection was cancelled or returned empty.")
    return None


def get_app_dir() -> str:
    """Returns the base directory containing the application data and config."""
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support/ResolveSync")
        os.makedirs(base, exist_ok=True)
        return base
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            base = os.path.join(appdata, "ResolveSync")
            os.makedirs(base, exist_ok=True)
            return base
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_FILE = os.path.join(get_app_dir(), "config.json")


def format_bytes(size: int) -> str:
    """Formats bytes into human-readable strings (MB, GB, TB)."""
    if not size or size <= 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def get_default_download_dir() -> str:
    """Returns sensible default download folder based on operating system."""
    if IS_WIN:
        return "D:\\DAVINCI"
    elif IS_MAC:
        # Check if an external volume is mounted in /Volumes/
        if os.path.exists("/Volumes"):
            try:
                vols = [v for v in os.listdir("/Volumes") if v not in ("Macintosh HD", ".timemachine", "Recovery")]
                if vols:
                    return f"/Volumes/{vols[0]}/ResolveSync"
            except Exception:
                pass
        return os.path.expanduser("~/Movies/ResolveSync")
    return os.path.expanduser("~/ResolveSync")


# ---------------------------------------------------------------------------
# DaVinci Setup & Mapping Tips Dialog
# ---------------------------------------------------------------------------

class DaVinciTipsDialog(ctk.CTkToplevel):
    """Interactive in-app guidance modal explaining DaVinci Resolve Mapped Mounts."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("💡 DaVinci Resolve Setup & Path Mapping Guide")
        self.geometry("780x740")
        self.minsize(720, 640)
        self.transient(parent)
        self.grab_set()

        self._build_ui()

    def _build_ui(self):
        container = ctk.CTkScrollableFrame(self, width=740, height=700)
        container.pack(fill="both", expand=True, padx=20, pady=20)

        # Title Header
        ctk.CTkLabel(
            container,
            text="DaVinci Resolve Path Mapping & Zero-Config Guide",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#60a5fa"
        ).pack(anchor="w", pady=(0, 6))

        ctk.CTkLabel(
            container,
            text="Everything you need to know about working between PC, Mac, and Remote Editors without offline clips.",
            font=ctk.CTkFont(size=12),
            text_color="#9ca3af"
        ).pack(anchor="w", pady=(0, 16))

        # Card 1: What is Mapped Mounts?
        c1 = ctk.CTkFrame(container, fg_color="#181a20", corner_radius=8, border_color="#2b2d38", border_width=1)
        c1.pack(fill="x", pady=(0, 14), padx=2)
        ctk.CTkLabel(c1, text="⚡ 1. What is DaVinci Resolve 'Mapped Mounts'?", font=ctk.CTkFont(size=14, weight="bold"), text_color="#10b981").pack(anchor="w", padx=16, pady=(12, 6))
        desc1 = (
            "DaVinci Resolve has a built-in virtual drive translator called 'Mapped Mounts'.\n\n"
            "• When a project is created on Windows, clip paths are stored as 'D:\\Users\\...\\clip.mp4'.\n"
            "• When that project is opened on macOS or another PC, DaVinci normally flags clips as 'Offline'.\n"
            "• With ONE Mapped Mount rule, DaVinci dynamically swaps 'D:\\' for your local folder in memory!\n"
            "• Result: ALL clips instantly show ONLINE, color graded, and fully playable with 0 relinking!"
        )
        ctk.CTkLabel(c1, text=desc1, font=ctk.CTkFont(size=12), text_color="#e5e7eb", justify="left").pack(anchor="w", padx=16, pady=(0, 14))

        # Card 2: macOS Setup
        c2 = ctk.CTkFrame(container, fg_color="#181a20", corner_radius=8, border_color="#2b2d38", border_width=1)
        c2.pack(fill="x", pady=(0, 14), padx=2)
        ctk.CTkLabel(c2, text="🍎 2. Exact Setup on Mac (Laptop or Mac Studio)", font=ctk.CTkFont(size=14, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=16, pady=(12, 6))
        desc2 = (
            "Step 1: Open DaVinci Resolve on your Mac.\n"
            "Step 2: Go to DaVinci Resolve menu -> Preferences... (or press Cmd + ,)\n"
            "Step 3: Click 'Media Storage' in the left sidebar.\n"
            "Step 4: Under 'Mapped Mounts' table at the bottom, click 'Add':\n"
            "        • Mapped Mount (Remote):  D:\\\n"
            "        • Local Mount (Mac):     /Volumes/YourSSD/D/  (or your chosen Download Folder)\n"
            "Step 5: Click 'Save' and reopen your project. BAM! Every single clip is online!"
        )
        ctk.CTkLabel(c2, text=desc2, font=ctk.CTkFont(size=12, family="Consolas"), text_color="#e2e8f0", justify="left").pack(anchor="w", padx=16, pady=(0, 14))

        # Card 3: Windows Setup & External Editors
        c3 = ctk.CTkFrame(container, fg_color="#181a20", corner_radius=8, border_color="#2b2d38", border_width=1)
        c3.pack(fill="x", pady=(0, 14), padx=2)
        ctk.CTkLabel(c3, text="👥 3. Setup for Windows Workstations & Remote Editors", font=ctk.CTkFont(size=14, weight="bold"), text_color="#fbbf24").pack(anchor="w", padx=16, pady=(12, 6))
        desc3 = (
            "If your remote editor is editing on Windows (or an external drive like E:\\Footage):\n\n"
            "• They open ResolveSync, set TrueNAS URL, and choose their local drive as 'Download To:'.\n"
            "• In DaVinci Resolve -> Preferences (Ctrl + ,) -> Media Storage -> Mapped Mounts:\n"
            "        • Mapped Mount (Remote):  D:\\\n"
            "        • Local Mount (Windows): E:\\Footage\\D\\\n"
            "• Both you and your editor can work simultaneously on the same PostgreSQL Network Database\n"
            "  or exchange .drp files with zero path conflicts!"
        )
        ctk.CTkLabel(c3, text=desc3, font=ctk.CTkFont(size=12), text_color="#e5e7eb", justify="left").pack(anchor="w", padx=16, pady=(0, 14))

        # Card 4: How ResolveSync Auto-Mirrors Drives
        c4 = ctk.CTkFrame(container, fg_color="#181a20", corner_radius=8, border_color="#2b2d38", border_width=1)
        c4.pack(fill="x", pady=(0, 14), padx=2)
        ctk.CTkLabel(c4, text="🔄 4. How ResolveSync Zero-Config Auto-Mapping Works", font=ctk.CTkFont(size=14, weight="bold"), text_color="#a855f7").pack(anchor="w", padx=16, pady=(12, 6))
        desc4 = (
            "You never need to set up manual folder rules for your footage:\n\n"
            "• PC File:     D:\\Users\\zigav\\Videos\\take1.mp4\n"
            "• TrueNAS:     /media/D/Users/zigav/Videos/take1.mp4  (Safe central storage)\n"
            "• Mac / SSD:   /Volumes/SSD/D/Users/zigav/Videos/take1.mp4\n\n"
            "Because the drive letter 'D' is maintained as the parent folder, mapping 'D:\\' to your\n"
            "local folder connects 100% of your clips regardless of how many folders you have!"
        )
        ctk.CTkLabel(c4, text=desc4, font=ctk.CTkFont(size=12, family="Consolas"), text_color="#e2e8f0", justify="left").pack(anchor="w", padx=16, pady=(0, 14))

        # Card 5: DaVinci Resolve Free + Network Project Server
        c5 = ctk.CTkFrame(container, fg_color="#181a20", corner_radius=8, border_color="#2b2d38", border_width=1)
        c5.pack(fill="x", pady=(0, 14), padx=2)
        ctk.CTkLabel(c5, text="🌐 5. DaVinci Resolve Free & Network Project Servers (No Studio Needed!)", font=ctk.CTkFont(size=14, weight="bold"), text_color="#ec4899").pack(anchor="w", padx=16, pady=(12, 6))
        desc5 = (
            "DaVinci Resolve Free connects natively to PostgreSQL Project Servers, but Blackmagic blocks\n"
            "external Python scripting in the Free version.\n\n"
            "ResolveSync solves this completely:\n"
            "• It connects directly to your PostgreSQL database using your .resolvedbkey credentials.\n"
            "• It auto-discovers all projects (test123, thailand, etc.) and extracts 100% of media clip paths.\n"
            "• DaVinci does not even need to be running, and no Studio license is needed!\n"
            "• Simply click 'Import .resolvedbkey' on your PC or Mac to sync and collaborate seamlessly!"
        )
        ctk.CTkLabel(c5, text=desc5, font=ctk.CTkFont(size=12), text_color="#e5e7eb", justify="left").pack(anchor="w", padx=16, pady=(0, 14))

        # Card 6: Blackmagic Proxy Workflow (Fast Sync on Laptops & Remote Editing)
        c6 = ctk.CTkFrame(container, fg_color="#181a20", corner_radius=8, border_color="#2b2d38", border_width=1)
        c6.pack(fill="x", pady=(0, 14), padx=2)
        ctk.CTkLabel(c6, text="⚡ 6. Blackmagic Proxy Workflow (Proxies Only vs Camera Originals)", font=ctk.CTkFont(size=14, weight="bold"), text_color="#38bdf8").pack(anchor="w", padx=16, pady=(12, 6))
        desc6 = (
            "Just like official Blackmagic Cloud (without subscription fees), ResolveSync supports selective proxy syncing:\n\n"
            "• '⚡ Proxies Only (Fast)': Syncs ONLY lightweight proxy files (_Proxy.mov, Proxy/ subfolder).\n"
            "   Transfers in seconds over Wi-Fi, saves 90% disk space, ideal for laptops and remote editors!\n"
            "• '🎥 Camera Originals Only': Syncs full-res 4K/8K/RAW footage for final color grading and export.\n"
            "• '🎬 All Media (Both)': Syncs both originals and proxies for a complete local mirror.\n\n"
            "In DaVinci Resolve, go to Playback -> Proxy Handling -> 'Prefer Proxies' to edit smoothly at 60fps!"
        )
        ctk.CTkLabel(c6, text=desc6, font=ctk.CTkFont(size=12), text_color="#e5e7eb", justify="left").pack(anchor="w", padx=16, pady=(0, 14))

        # Close button
        btn_close = ctk.CTkButton(container, text="Got it!", font=ctk.CTkFont(size=13, weight="bold"), command=self.destroy, fg_color="#2563eb", height=36)
        btn_close.pack(fill="x", pady=(10, 4))


# ---------------------------------------------------------------------------
# Path Helper Utilities & Mapped Mounts Calculator
# ---------------------------------------------------------------------------

def open_folder_in_explorer(folder_path: str):
    """Opens a directory in Windows File Explorer or macOS Finder."""
    norm = os.path.normpath(folder_path)
    if not os.path.exists(norm):
        try:
            os.makedirs(norm, exist_ok=True)
        except Exception:
            pass
    try:
        if sys.platform == "win32":
            os.startfile(norm)
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["open", norm])
        else:
            import subprocess
            subprocess.run(["xdg-open", norm])
    except Exception as e:
        logger.warning(f"Could not open folder in file explorer: {e}")


def copy_to_clipboard(window, text: str, feedback_label: Optional[ctk.CTkLabel] = None):
    """Safely copies a string to the system clipboard and displays confirmation."""
    try:
        window.clipboard_clear()
        window.clipboard_append(text)
        window.update()
        if feedback_label:
            feedback_label.configure(text=f"✓ Copied: {text}", text_color="#10b981")
            window.after(3000, lambda: feedback_label.configure(text=""))
    except Exception as e:
        logger.debug(f"Clipboard copy error: {e}")


def calculate_mapped_mounts(paths: List[str], sync_root: str, is_win: bool) -> List[dict]:
    """
    Analyzes project clip paths and returns a list of recommended DaVinci Resolve
    Mapped Mount rules with exact Remote and Local mount paths.
    """
    recs = []
    seen = set()
    norm_sync = os.path.normpath(sync_root) if sync_root else ("D:\\DAVINCI" if is_win else os.path.expanduser("~/Movies/ResolveSync"))

    for p in paths:
        if not p:
            continue
        clean = p.replace('\\', '/')
        if is_win:
            # 1. Foreign macOS Home Path (e.g. /Users/ziga/...)
            m_user = re.match(r'^/?Users/([^/]+)/', clean, re.IGNORECASE)
            if m_user:
                u = m_user.group(1)
                k = f"mac_user_{u.lower()}"
                if k not in seen:
                    seen.add(k)
                    remote = f"/Users/{u}/"
                    c1 = os.path.normpath(os.path.join(norm_sync, "Root", "Users", u)) + "\\"
                    c2 = os.path.normpath(os.path.join(norm_sync, "Users", u)) + "\\"
                    loc = c1 if os.path.exists(c1) else c2

                    # Check sample file on disk
                    fname = os.path.basename(clean)
                    v_file = os.path.normpath(os.path.join(loc, clean.split(f"/Users/{u}/")[1].replace('/', os.sep))) if f"/Users/{u}/" in clean else None
                    exists = os.path.exists(v_file) if v_file else os.path.exists(loc)

                    recs.append({
                        "origin": f"macOS User Home (/Users/{u}/...)",
                        "origin_badge": "🍎 macOS Path",
                        "remote": remote,
                        "local": loc,
                        "sample_clip": fname,
                        "verified": exists,
                        "verified_path": v_file or loc,
                    })

            # 2. Foreign macOS Volumes (e.g. /Volumes/ExtSSD/...)
            m_vol = re.match(r'^/?Volumes/([^/]+)/', clean, re.IGNORECASE)
            if m_vol:
                v = m_vol.group(1)
                k = f"mac_vol_{v.lower()}"
                if k not in seen:
                    seen.add(k)
                    remote = f"/Volumes/{v}/"
                    loc = os.path.normpath(os.path.join(norm_sync, "Volumes", v)) + "\\"
                    recs.append({
                        "origin": f"macOS External Drive (/Volumes/{v}/...)",
                        "origin_badge": f"🍎 Drive: {v}",
                        "remote": remote,
                        "local": loc,
                        "sample_clip": os.path.basename(clean),
                        "verified": os.path.exists(loc),
                        "verified_path": loc,
                    })

            # 3. UNC Network Share (e.g. \\server\share\...)
            m_unc = re.match(r'^[\\/]{2}([^\\/]+)[\\/]([^\\/]+)', clean)
            if m_unc:
                srv = m_unc.group(1)
                sh = m_unc.group(2)
                k = f"unc_{srv.lower()}_{sh.lower()}"
                if k not in seen:
                    seen.add(k)
                    remote = f"\\\\{srv}\\{sh}\\"
                    loc = os.path.normpath(os.path.join(norm_sync, "SMB", srv, sh)) + "\\"
                    recs.append({
                        "origin": f"Network SMB Share (\\\\{srv}\\{sh})",
                        "origin_badge": "🌐 SMB Share",
                        "remote": remote,
                        "local": loc,
                        "sample_clip": os.path.basename(clean),
                        "verified": os.path.exists(loc),
                        "verified_path": loc,
                    })

        else:
            # macOS running: Look for Windows drive letters (e.g. D:\..., E:\...)
            m_win = re.match(r'^([a-zA-Z]):[\\/]', p)
            if m_win:
                d = m_win.group(1).upper()
                k = f"win_drive_{d}"
                if k not in seen:
                    seen.add(k)
                    remote = f"{d}:\\"
                    loc = posixpath.join(norm_sync.replace('\\', '/'), d) + "/"
                    recs.append({
                        "origin": f"Windows Drive ({d}:\\...)",
                        "origin_badge": f"🖥️ Windows {d}:",
                        "remote": remote,
                        "local": loc,
                        "sample_clip": os.path.basename(clean),
                        "verified": os.path.exists(loc),
                        "verified_path": loc,
                    })

            # UNC Network Share on Mac
            m_unc = re.match(r'^[\\/]{2}([^\\/]+)[\\/]([^\\/]+)', clean)
            if m_unc:
                srv = m_unc.group(1)
                sh = m_unc.group(2)
                k = f"unc_{srv.lower()}_{sh.lower()}"
                if k not in seen:
                    seen.add(k)
                    remote = f"\\\\{srv}\\{sh}\\"
                    loc = posixpath.join(norm_sync.replace('\\', '/'), "SMB", srv, sh) + "/"
                    recs.append({
                        "origin": f"Network SMB Share (\\\\{srv}\\{sh})",
                        "origin_badge": "🌐 SMB Share",
                        "remote": remote,
                        "local": loc,
                        "sample_clip": os.path.basename(clean),
                        "verified": os.path.exists(loc),
                        "verified_path": loc,
                    })

    return recs


# ---------------------------------------------------------------------------
# First-Time Sync Destination Prompt Dialog
# ---------------------------------------------------------------------------

class FirstTimeSyncDialog(ctk.CTkToplevel):
    """Prompts the user on their first sync to confirm or customize the media download folder."""

    def __init__(self, parent, current_folder: str, on_confirm_callback):
        super().__init__(parent)
        self.current_folder = current_folder
        self.on_confirm_callback = on_confirm_callback

        self.title("📁 Choose Media Download Location")
        self.geometry("580x370")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._build_ui()

    def _build_ui(self):
        f = ctk.CTkFrame(self, fg_color="#18191f")
        f.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            f,
            text="Where should media be downloaded?",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color="#60a5fa"
        ).pack(anchor="w", pady=(0, 6))

        desc = (
            "When synchronizing, ResolveSync downloads project media into this folder,\n"
            "preserving the exact drive hierarchy so DaVinci Resolve can link files seamlessly.\n\n"
            "You can keep this default or choose any internal drive, SSD, or external storage."
        )
        ctk.CTkLabel(f, text=desc, font=ctk.CTkFont(size=12), text_color="#d1d5db", justify="left").pack(anchor="w", pady=(0, 16))

        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x", pady=(0, 16))

        self.folder_entry = ctk.CTkEntry(row, height=36, font=ctk.CTkFont(size=12))
        self.folder_entry.insert(0, self.current_folder)
        self.folder_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        btn_browse = ctk.CTkButton(row, text="Browse...", width=100, height=36, command=self._browse, fg_color="#374151")
        btn_browse.pack(side="left")

        self.remember_var = ctk.BooleanVar(value=True)
        chk = ctk.CTkCheckBox(f, text="Remember my choice (don't prompt on future syncs)", variable=self.remember_var, font=ctk.CTkFont(size=12))
        chk.pack(anchor="w", pady=(0, 20))

        btn_row = ctk.CTkFrame(f, fg_color="transparent")
        btn_row.pack(fill="x")

        btn_cancel = ctk.CTkButton(btn_row, text="Cancel", width=100, height=36, command=self.destroy, fg_color="#4b5563")
        btn_cancel.pack(side="right", padx=(8, 0))

        btn_confirm = ctk.CTkButton(
            btn_row,
            text="✅ Start Sync with this Folder",
            height=36,
            command=self._confirm,
            fg_color="#059669",
            hover_color="#047857",
            font=ctk.CTkFont(weight="bold")
        )
        btn_confirm.pack(side="right")

    def _browse(self):
        f = filedialog.askdirectory(title="Select Folder to Store Downloaded Media", initialdir=self.folder_entry.get().strip() or None)
        if f:
            norm = os.path.normpath(f)
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, norm)

    def _confirm(self):
        chosen = self.folder_entry.get().strip()
        if not chosen:
            messagebox.showwarning("Folder Required", "Please specify a folder to store media.")
            return
        self.on_confirm_callback(chosen, self.remember_var.get())
        self.destroy()


# ---------------------------------------------------------------------------
# Post-Sync DaVinci Launch Dialog
# ---------------------------------------------------------------------------

class PostSyncLaunchDialog(ctk.CTkToplevel):
    """
    Clean, modern modal dialog that asks the user if they wish to launch DaVinci Resolve
    immediately after a successful sync run.
    """

    def __init__(self, parent, project_name: str, count: int, on_launch_callback):
        super().__init__(parent)
        self.on_launch_callback = on_launch_callback

        self.title("🎬 DaVinci Resolve Ready")
        self.geometry("560x340")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._build_ui(project_name, count)

    def _build_ui(self, project_name: str, count: int):
        f = ctk.CTkFrame(self, fg_color="#18191f")
        f.pack(fill="both", expand=True, padx=20, pady=20)

        header_frame = ctk.CTkFrame(f, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            header_frame,
            text="✓ Media Synchronization Complete!",
            font=ctk.CTkFont(size=17, weight="bold"),
            text_color="#10b981",
        ).pack(side="left")

        p_name = project_name or "Your Project"
        msg = (
            f"All {count} media clips for '{p_name}' are fully synchronized\n"
            f"and ready on your local workstation.\n\n"
            f"Would you like to open DaVinci Resolve now to start editing with automatic media relinking?"
        )
        ctk.CTkLabel(f, text=msg, font=ctk.CTkFont(size=12), text_color="#d1d5db", justify="left").pack(anchor="w", pady=(0, 14))

        tip_box = ctk.CTkFrame(f, fg_color="#1e222d", corner_radius=8, border_color="#2b2d38", border_width=1)
        tip_box.pack(fill="x", pady=(0, 18), padx=2)
        ctk.CTkLabel(
            tip_box,
            text="💡 DaVinci Resolve Mapped Mounts are active. Your footage will show online with 0 relinking!",
            font=ctk.CTkFont(size=11),
            text_color="#93c5fd",
            justify="left",
            wraplength=480,
        ).pack(padx=12, pady=10)

        btn_row = ctk.CTkFrame(f, fg_color="transparent")
        btn_row.pack(fill="x", side="bottom")

        btn_later = ctk.CTkButton(
            btn_row,
            text="Done / Later",
            width=120,
            height=36,
            command=self.destroy,
            fg_color="#374151",
            hover_color="#4b5563",
        )
        btn_later.pack(side="right", padx=(10, 0))

        btn_launch = ctk.CTkButton(
            btn_row,
            text="🎬 Open DaVinci Resolve",
            width=200,
            height=36,
            command=self._launch,
            fg_color="#6366f1",
            hover_color="#4f46e5",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        btn_launch.pack(side="right")

    def _launch(self):
        self.destroy()
        if self.on_launch_callback:
            self.on_launch_callback()


# ---------------------------------------------------------------------------
# Sync Scope Confirmation & File Selection Dialogs
# ---------------------------------------------------------------------------

class SyncScopeDialog(ctk.CTkToplevel):
    """
    Asks the user whether to sync all missing media or select specific files to sync.
    """
    def __init__(self, parent, project_name: str, mode: str, count: int, total_bytes: int, on_choice_callback):
        super().__init__(parent)
        self.on_choice_callback = on_choice_callback

        self.title("🚀 Start Synchronization")
        self.geometry("560x370")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._build_ui(project_name, mode, count, total_bytes)

    def _build_ui(self, project_name: str, mode: str, count: int, total_bytes: int):
        f = ctk.CTkFrame(self, fg_color="#18191f")
        f.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            f,
            text="🚀 Ready to Synchronize",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#60a5fa",
        ).pack(anchor="w", pady=(0, 4))

        p_name = project_name or "Active Project"
        size_str = format_bytes(total_bytes) if total_bytes > 0 else ""
        size_part = f" ({size_str})" if size_str else ""
        msg = (
            f"Project: {p_name}\n"
            f"Mode: {mode.upper()}\n"
            f"Files to transfer: {count} file(s){size_part}\n\n"
            f"Would you like to sync all files, or choose specific files to transfer?"
        )
        ctk.CTkLabel(f, text=msg, font=ctk.CTkFont(size=12), text_color="#d1d5db", justify="left").pack(anchor="w", pady=(0, 16))

        # Choices frame
        choice_box = ctk.CTkFrame(f, fg_color="#14151b", corner_radius=8, border_color="#2b2d38", border_width=1)
        choice_box.pack(fill="x", pady=(0, 16), padx=2)

        # Button 1: Sync Everything
        btn_all = ctk.CTkButton(
            choice_box,
            text=f"🚀 Sync Everything (All {count} Files)",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._choose_all,
            fg_color="#059669",
            hover_color="#047857",
            height=40,
        )
        btn_all.pack(fill="x", padx=16, pady=(14, 8))

        # Button 2: Select Specific Files
        btn_select = ctk.CTkButton(
            choice_box,
            text="📋 Select Specific Files (Pick from List)...",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._choose_select,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            height=40,
        )
        btn_select.pack(fill="x", padx=16, pady=(0, 14))

        # Footer Row with Remember Checkbox & Cancel
        footer = ctk.CTkFrame(f, fg_color="transparent")
        footer.pack(fill="x", side="bottom")

        self.remember_var = ctk.BooleanVar(value=False)
        chk = ctk.CTkCheckBox(
            footer,
            text="Always sync everything (don't ask again)",
            variable=self.remember_var,
            font=ctk.CTkFont(size=11),
        )
        chk.pack(side="left")

        btn_cancel = ctk.CTkButton(
            footer,
            text="Cancel",
            width=90,
            command=self.destroy,
            fg_color="#374151",
            hover_color="#4b5563",
        )
        btn_cancel.pack(side="right")

    def _choose_all(self):
        remember = self.remember_var.get()
        self.destroy()
        if self.on_choice_callback:
            self.on_choice_callback("all", remember)

    def _choose_select(self):
        self.destroy()
        if self.on_choice_callback:
            self.on_choice_callback("select", False)


class FileSelectionModalDialog(ctk.CTkToplevel):
    """
    Interactive checklist allowing users to review all project media files,
    filter by status / type / proxy, search by filename, and selectively download or upload.
    """
    def __init__(self, parent, media_items: List[MediaItem], mode: str, on_confirmed_callback):
        super().__init__(parent)
        self.parent_app = parent
        self.media_items = media_items
        self.mode = mode
        self.on_confirmed_callback = on_confirmed_callback

        self.title("📋 Select Files to Synchronize")
        self.geometry("920x740")
        self.minsize(780, 560)
        self.transient(parent)
        self.grab_set()

        # Track checkboxes: item_id -> (BooleanVar, item)
        self.item_vars: Dict[int, Tuple[ctk.BooleanVar, MediaItem]] = {}
        for idx, item in enumerate(self.media_items):
            # Check by default if file needs action
            needs_action = item.status in ("NEEDS_DOWNLOAD", "NEEDS_UPLOAD", "SIZE_MISMATCH")
            self.item_vars[idx] = (ctk.BooleanVar(value=needs_action), item)

        self._build_ui()

    def _build_ui(self):
        container = ctk.CTkFrame(self, fg_color="#18191f")
        container.pack(fill="both", expand=True, padx=16, pady=16)

        # Header
        top_bar = ctk.CTkFrame(container, fg_color="transparent")
        top_bar.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            top_bar,
            text="📋 Select Files to Synchronize",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#60a5fa",
        ).pack(side="left")

        # Search Bar
        search_frame = ctk.CTkFrame(container, fg_color="transparent")
        search_frame.pack(fill="x", pady=(0, 8))

        self.search_entry = ctk.CTkEntry(
            search_frame,
            placeholder_text="🔍 Filter files by name...",
            height=32,
            font=ctk.CTkFont(size=12),
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.search_entry.bind("<KeyRelease>", lambda e: self._filter_display())

        btn_clear = ctk.CTkButton(
            search_frame,
            text="Clear",
            width=70,
            height=32,
            command=self._clear_search,
            fg_color="#374151",
        )
        btn_clear.pack(side="left")

        # Quick Filter Pills
        filter_row = ctk.CTkFrame(container, fg_color="transparent")
        filter_row.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(filter_row, text="Quick Select:", font=ctk.CTkFont(size=11, weight="bold"), text_color="#9ca3af").pack(side="left", padx=(0, 6))

        for lbl, fn in [
            ("Select All", lambda: self._set_all_checks(True)),
            ("Deselect All", lambda: self._set_all_checks(False)),
            ("⚡ Proxies Only", lambda: self._set_filtered_checks(lambda i: i.is_proxy)),
            ("🎥 Originals Only", lambda: self._set_filtered_checks(lambda i: not i.is_proxy)),
            ("⬇️ Needs Download", lambda: self._set_filtered_checks(lambda i: i.status == "NEEDS_DOWNLOAD")),
            ("⬆️ Needs Upload", lambda: self._set_filtered_checks(lambda i: i.status == "NEEDS_UPLOAD")),
        ]:
            b = ctk.CTkButton(
                filter_row,
                text=lbl,
                height=26,
                font=ctk.CTkFont(size=11),
                command=fn,
                fg_color="#2d3039",
                hover_color="#373a46",
            )
            b.pack(side="left", padx=3)

        # Scrollable File List Container
        self.scroll_frame = ctk.CTkScrollableFrame(container, fg_color="#121316", corner_radius=8)
        self.scroll_frame.pack(fill="both", expand=True, pady=(0, 12))

        self.row_widgets: List[Tuple[ctk.CTkFrame, int]] = []
        self._populate_rows()

        # Bottom Bar: Summary & Confirm / Cancel
        bottom_bar = ctk.CTkFrame(container, fg_color="transparent")
        bottom_bar.pack(fill="x", side="bottom")

        self.summary_lbl = ctk.CTkLabel(
            bottom_bar,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#e5e7eb",
        )
        self.summary_lbl.pack(side="left")

        self.btn_confirm = ctk.CTkButton(
            bottom_bar,
            text="🚀 Start Sync with Selected Files",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._confirm_selection,
            fg_color="#059669",
            hover_color="#047857",
            height=38,
            width=220,
        )
        self.btn_confirm.pack(side="right", padx=(10, 0))

        btn_cancel = ctk.CTkButton(
            bottom_bar,
            text="Cancel",
            width=90,
            height=38,
            command=self.destroy,
            fg_color="#374151",
            hover_color="#4b5563",
        )
        btn_cancel.pack(side="right")

        self._update_summary()

    def _populate_rows(self):
        for w, _ in self.row_widgets:
            w.destroy()
        self.row_widgets.clear()

        query = self.search_entry.get().strip().lower()

        for idx, (var, item) in self.item_vars.items():
            fname = os.path.basename(item.local_path or item.drp_path)
            fpath = item.local_path or item.drp_path

            if query and query not in fname.lower() and query not in fpath.lower():
                continue

            row = ctk.CTkFrame(self.scroll_frame, fg_color="#1c1d24", corner_radius=6)
            row.pack(fill="x", padx=4, pady=3)

            # Left: Checkbox + Filename
            cb = ctk.CTkCheckBox(
                row,
                text=fname,
                variable=var,
                command=self._update_summary,
                font=ctk.CTkFont(size=12, weight="bold"),
                width=300,
            )
            cb.pack(side="left", padx=10, pady=8)

            # Type Badge (Proxy vs Original)
            type_text = "⚡ PROXY" if item.is_proxy else "🎥 ORIGINAL"
            type_color = "#4f46e5" if item.is_proxy else "#374151"
            ctk.CTkLabel(
                row,
                text=type_text,
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color=type_color,
                corner_radius=4,
                padx=6,
                pady=1,
            ).pack(side="left", padx=6)

            # Status Badge
            st = item.status
            if st == "NEEDS_DOWNLOAD":
                st_text = "⬇️ Needs Download"
                st_color = "#2563eb"
            elif st == "NEEDS_UPLOAD":
                st_text = "⬆️ Needs Upload"
                st_color = "#7c3aed"
            elif st == "SYNCED":
                st_text = "✓ In Sync"
                st_color = "#10b981"
            elif item.local_exists:
                st_text = "✓ Local Exists"
                st_color = "#059669"
            elif st == "SIZE_MISMATCH":
                st_text = "⚠️ Size Mismatch"
                st_color = "#d97706"
            elif st == "UNMAPPED":
                st_text = "⚠️ Unmapped"
                st_color = "#dc2626"
            else:
                st_text = st
                st_color = "#4b5563"

            ctk.CTkLabel(
                row,
                text=st_text,
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color=st_color,
                corner_radius=4,
                padx=6,
                pady=1,
            ).pack(side="left", padx=6)

            # Size
            size_b = item.file_size_local or item.file_size_remote or 0
            size_str = format_bytes(size_b) if size_b > 0 else "-"
            ctk.CTkLabel(
                row,
                text=size_str,
                font=ctk.CTkFont(size=11),
                text_color="#9ca3af",
                width=80,
                anchor="e",
            ).pack(side="right", padx=12)

            # Monospace subpath
            ctk.CTkLabel(
                row,
                text=fpath,
                font=ctk.CTkFont(family="Consolas", size=10),
                text_color="#6b7280",
                anchor="w",
            ).pack(side="left", fill="x", expand=True, padx=8)

            self.row_widgets.append((row, idx))

    def _filter_display(self):
        self._populate_rows()

    def _clear_search(self):
        self.search_entry.delete(0, "end")
        self._populate_rows()

    def _set_all_checks(self, checked: bool):
        for var, _ in self.item_vars.values():
            var.set(checked)
        self._update_summary()

    def _set_filtered_checks(self, predicate):
        for var, item in self.item_vars.values():
            if predicate(item):
                var.set(True)
            else:
                var.set(False)
        self._update_summary()

    def _update_summary(self):
        selected = [item for var, item in self.item_vars.values() if var.get()]
        total_count = len(self.media_items)
        sel_count = len(selected)
        sel_bytes = sum(i.file_size_local or i.file_size_remote or 0 for i in selected)

        self.summary_lbl.configure(text=f"Selected: {sel_count} of {total_count} files ({format_bytes(sel_bytes)})")
        if sel_count > 0:
            self.btn_confirm.configure(state="normal", text=f"🚀 Sync Selected ({sel_count} Files)")
        else:
            self.btn_confirm.configure(state="disabled", text="Select at least 1 file")

    def _confirm_selection(self):
        selected_paths = [
            (item.local_path or item.drp_path)
            for var, item in self.item_vars.values()
            if var.get()
        ]
        self.destroy()
        if self.on_confirmed_callback:
            self.on_confirmed_callback(selected_paths)


# ---------------------------------------------------------------------------
# DaVinci Resolve Mapped Mounts Assistant Dialog
# ---------------------------------------------------------------------------

class MappedMountsHelperDialog(ctk.CTkToplevel):
    """
    Interactive assistant that reads DaVinci Resolve preferences (.config.data and config.dat),
    detects missing or slash-mismatched mapped mounts, and allows 1-click automatic addition/fixing.
    """

    def __init__(self, parent, current_folder: str, media_paths: Optional[List[str]] = None, active_project: str = ""):
        super().__init__(parent)
        self.current_folder = current_folder or get_default_download_dir()
        self.media_paths = media_paths or []
        self.active_project = active_project or "Current Project"
        self.pref_manager = DaVinciPreferencesManager()

        self.title("🗺️ DaVinci Resolve Mapped Mounts Assistant")
        self.geometry("880x860")
        self.minsize(800, 700)
        self.transient(parent)
        self.grab_set()

        self.container = ctk.CTkScrollableFrame(self, width=840, height=820)
        self.container.pack(fill="both", expand=True, padx=20, pady=20)

        self._render_content()

    def _render_content(self):
        for w in self.container.winfo_children():
            w.destroy()

        # Title Header
        ctk.CTkLabel(
            self.container,
            text="DaVinci Resolve Mapped Mounts Assistant",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#a855f7"
        ).pack(anchor="w", pady=(0, 4))

        subtitle = (
            "Seamlessly link media imported across different operating systems (Mac <-> Windows <-> Linux).\n"
            "This assistant reads DaVinci Resolve's preferences directly and can auto-configure mounts with 1 click."
        )
        ctk.CTkLabel(self.container, text=subtitle, font=ctk.CTkFont(size=12), text_color="#9ca3af", justify="left").pack(anchor="w", pady=(0, 14))

        # Status & System Card
        ctx_frame = ctk.CTkFrame(self.container, fg_color="#181922", corner_radius=8, border_color="#2b2d38", border_width=1)
        ctx_frame.pack(fill="x", pady=(0, 14))
        ctx_inner = ctk.CTkFrame(ctx_frame, fg_color="transparent")
        ctx_inner.pack(fill="x", padx=16, pady=12)

        ctk.CTkLabel(ctx_inner, text="System Environment & DaVinci Configuration:", font=ctk.CTkFont(size=13, weight="bold"), text_color="#60a5fa").pack(anchor="w", pady=(0, 6))

        pref_status = "✓ Found & Configurable" if self.pref_manager.exists() else "⚠️ Not Found"
        is_running = self.pref_manager.is_davinci_running()
        run_status = "⚠️ Running (Restart required after auto-applying)" if is_running else "🟢 Closed (Safe to auto-apply mounts directly)"

        info_text = (
            f"• Current Workstation OS:   {OS_NAME} ({platform.machine()})\n"
            f"• DaVinci Preferences Dir: {self.pref_manager.pref_dir} ({pref_status})\n"
            f"• DaVinci Resolve Status:  {run_status}\n"
            f"• Media Download Folder:   {self.current_folder}\n"
            f"• Active Project:          {self.active_project} ({len(self.media_paths)} clips)"
        )
        ctk.CTkLabel(ctx_inner, text=info_text, font=ctk.CTkFont(family="Consolas", size=11), text_color="#e2e8f0", justify="left").pack(anchor="w")

        # --- Section 1: Project-Specific Calculated Recommendations ---
        recs = calculate_mapped_mounts(self.media_paths, self.current_folder, IS_WIN)

        sec1_title = ctk.CTkLabel(self.container, text="⚡ Recommended Mapped Mounts for Active Project:", font=ctk.CTkFont(size=15, weight="bold"), text_color="#10b981")
        sec1_title.pack(anchor="w", pady=(8, 6))

        if recs:
            for r in recs:
                st = self.pref_manager.check_mount_status(r["remote"], r["local"])

                # Border color matches DaVinci status
                border_c = st.get("color", "#2563eb")
                card = ctk.CTkFrame(self.container, fg_color="#132438", corner_radius=8, border_color=border_c, border_width=1)
                card.pack(fill="x", pady=(0, 12))

                inner = ctk.CTkFrame(card, fg_color="transparent")
                inner.pack(fill="x", padx=16, pady=12)

                top_r = ctk.CTkFrame(inner, fg_color="transparent")
                top_r.pack(fill="x", pady=(0, 8))
                badge = ctk.CTkLabel(top_r, text=r["origin_badge"], font=ctk.CTkFont(size=11, weight="bold"), fg_color="#1e40af", corner_radius=6)
                badge.pack(side="left")
                ctk.CTkLabel(top_r, text=f"  {r['origin']}", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")

                st_badge = ctk.CTkLabel(top_r, text=f" {st['badge']} ", font=ctk.CTkFont(size=11, weight="bold"), fg_color=st.get("color", "#374151"), text_color="#ffffff", corner_radius=6)
                st_badge.pack(side="right")

                # Mapped Mount Row (Remote)
                row_m = ctk.CTkFrame(inner, fg_color="transparent")
                row_m.pack(fill="x", pady=2)
                ctk.CTkLabel(row_m, text="Mapped Mount (Remote):", width=180, anchor="w", font=ctk.CTkFont(size=12)).pack(side="left")
                ent_m = ctk.CTkEntry(row_m, font=ctk.CTkFont(family="Consolas", size=12))
                ent_m.insert(0, r["remote"])
                ent_m.pack(side="left", fill="x", expand=True, padx=(0, 8))
                ctk.CTkButton(row_m, text="📋 Copy", width=80, fg_color="#2563eb", command=lambda t=r["remote"]: copy_to_clipboard(self, t, self.status_feedback)).pack(side="left")

                # Local Mount Row (On Disk)
                row_l = ctk.CTkFrame(inner, fg_color="transparent")
                row_l.pack(fill="x", pady=2)
                ctk.CTkLabel(row_l, text="Local Mount (Media Folder):", width=180, anchor="w", font=ctk.CTkFont(size=12)).pack(side="left")
                ent_l = ctk.CTkEntry(row_l, font=ctk.CTkFont(family="Consolas", size=12))
                ent_l.insert(0, r["local"])
                ent_l.pack(side="left", fill="x", expand=True, padx=(0, 8))
                ctk.CTkButton(row_l, text="📋 Copy", width=80, fg_color="#059669", command=lambda t=r["local"]: copy_to_clipboard(self, t, self.status_feedback)).pack(side="left")

                # Disk verification note
                if r.get("verified"):
                    status_note = f"✓ Verified file on disk: {r.get('sample_clip', 'media file')}"
                    ctk.CTkLabel(inner, text=status_note, font=ctk.CTkFont(size=11, weight="bold"), text_color="#10b981").pack(anchor="w", pady=(6, 4))
                else:
                    status_note = f"• Will apply to downloaded files like: {r.get('sample_clip', 'media file')}"
                    ctk.CTkLabel(inner, text=status_note, font=ctk.CTkFont(size=11), text_color="#9ca3af").pack(anchor="w", pady=(6, 4))

                # --- DaVinci Live Status & 1-Click Action Box ---
                if st["status"] == "slash_mismatch":
                    st_box = ctk.CTkFrame(inner, fg_color="#3b2005", corner_radius=6, border_color="#f59e0b", border_width=1)
                    st_box.pack(fill="x", pady=(6, 0))
                    st_box_in = ctk.CTkFrame(st_box, fg_color="transparent")
                    st_box_in.pack(fill="x", padx=12, pady=10)
                    ctk.CTkLabel(st_box_in, text="⚠️ Trailing Slash Mismatch Bug Detected in DaVinci Preferences!", font=ctk.CTkFont(size=12, weight="bold"), text_color="#f59e0b").pack(anchor="w")
                    ctk.CTkLabel(st_box_in, text=st["details"], font=ctk.CTkFont(size=11), text_color="#fde68a", justify="left", wraplength=720).pack(anchor="w", pady=(2, 8))
                    btn_fix = ctk.CTkButton(
                        st_box_in,
                        text="⚡ 1-Click Fix in DaVinci Preferences",
                        fg_color="#d97706",
                        hover_color="#b45309",
                        font=ctk.CTkFont(weight="bold"),
                        height=32,
                        command=lambda rm=r["remote"], lm=r["local"]: self._auto_apply_mount(rm, lm)
                    )
                    btn_fix.pack(anchor="w")

                elif st["status"] == "missing":
                    st_box = ctk.CTkFrame(inner, fg_color="#2b1115", corner_radius=6, border_color="#ef4444", border_width=1)
                    st_box.pack(fill="x", pady=(6, 0))
                    st_box_in = ctk.CTkFrame(st_box, fg_color="transparent")
                    st_box_in.pack(fill="x", padx=12, pady=10)
                    ctk.CTkLabel(st_box_in, text="❌ Missing in DaVinci Resolve Preferences!", font=ctk.CTkFont(size=12, weight="bold"), text_color="#ef4444").pack(anchor="w")
                    ctk.CTkLabel(st_box_in, text=st["details"], font=ctk.CTkFont(size=11), text_color="#fca5a5", justify="left", wraplength=720).pack(anchor="w", pady=(2, 8))
                    btn_add = ctk.CTkButton(
                        st_box_in,
                        text="⚡ 1-Click Auto-Add to DaVinci Preferences",
                        fg_color="#2563eb",
                        hover_color="#1d4ed8",
                        font=ctk.CTkFont(weight="bold"),
                        height=32,
                        command=lambda rm=r["remote"], lm=r["local"]: self._auto_apply_mount(rm, lm)
                    )
                    btn_add.pack(anchor="w")

                elif st["status"] == "different_target":
                    st_box = ctk.CTkFrame(inner, fg_color="#3b2005", corner_radius=6, border_color="#f59e0b", border_width=1)
                    st_box.pack(fill="x", pady=(6, 0))
                    st_box_in = ctk.CTkFrame(st_box, fg_color="transparent")
                    st_box_in.pack(fill="x", padx=12, pady=10)
                    ctk.CTkLabel(st_box_in, text="⚠️ Mount Points to Different Folder in DaVinci", font=ctk.CTkFont(size=12, weight="bold"), text_color="#f59e0b").pack(anchor="w")
                    ctk.CTkLabel(st_box_in, text=st["details"], font=ctk.CTkFont(size=11), text_color="#fde68a", justify="left", wraplength=720).pack(anchor="w", pady=(2, 8))
                    btn_upd = ctk.CTkButton(
                        st_box_in,
                        text="⚡ Update DaVinci Mount to Match ResolveSync",
                        fg_color="#d97706",
                        hover_color="#b45309",
                        font=ctk.CTkFont(weight="bold"),
                        height=32,
                        command=lambda rm=r["remote"], lm=r["local"]: self._auto_apply_mount(rm, lm)
                    )
                    btn_upd.pack(anchor="w")

                elif st["status"] == "active":
                    st_box = ctk.CTkFrame(inner, fg_color="#062e1c", corner_radius=6, border_color="#10b981", border_width=1)
                    st_box.pack(fill="x", pady=(6, 0))
                    st_box_in = ctk.CTkFrame(st_box, fg_color="transparent")
                    st_box_in.pack(fill="x", padx=12, pady=8)
                    top_act = ctk.CTkFrame(st_box_in, fg_color="transparent")
                    top_act.pack(fill="x")
                    ctk.CTkLabel(top_act, text="🟢 100% Configured & Active in DaVinci Resolve!", font=ctk.CTkFont(size=12, weight="bold"), text_color="#10b981").pack(side="left")
                    ctk.CTkButton(
                        top_act,
                        text="🔄 Re-apply",
                        width=85,
                        height=26,
                        fg_color="#1f2937",
                        hover_color="#374151",
                        command=lambda rm=r["remote"], lm=r["local"]: self._auto_apply_mount(rm, lm)
                    ).pack(side="right")
                    ctk.CTkLabel(st_box_in, text=st["details"], font=ctk.CTkFont(size=11), text_color="#a7f3d0", justify="left").pack(anchor="w", pady=(2, 0))
        else:
            no_rec_frame = ctk.CTkFrame(self.container, fg_color="#181a20", corner_radius=8)
            no_rec_frame.pack(fill="x", pady=(0, 10))
            no_desc = (
                "✓ All media files in the active project use paths native to this operating system!\n"
                "If footage is imported from another machine (e.g. Mac /Volumes or Windows D:\\), the required\n"
                "mount rule will appear here automatically."
            )
            ctk.CTkLabel(no_rec_frame, text=no_desc, font=ctk.CTkFont(size=12), text_color="#9ca3af", justify="left").pack(anchor="w", padx=16, pady=12)

        # Global Copy Feedback Label
        self.status_feedback = ctk.CTkLabel(self.container, text="", font=ctk.CTkFont(size=12, weight="bold"))
        self.status_feedback.pack(anchor="w", pady=(2, 10))

        # --- Section 2: Interactive Offline Path Calculator ---
        sec2_card = ctk.CTkFrame(self.container, fg_color="#1c1d24", corner_radius=8, border_color="#374151", border_width=1)
        sec2_card.pack(fill="x", pady=(4, 16))

        s2_inner = ctk.CTkFrame(sec2_card, fg_color="transparent")
        s2_inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(s2_inner, text="🔍 Test Any Offline Path (From DaVinci 'Unable to find media' popup):", font=ctk.CTkFont(size=14, weight="bold"), text_color="#f59e0b").pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(s2_inner, text="Did DaVinci popup 'Unable to find media: \\Users\\ziga\\Pictures\\lidl.png'? Paste it here to test and auto-fix:", font=ctk.CTkFont(size=11), text_color="#9ca3af").pack(anchor="w", pady=(0, 10))

        input_row = ctk.CTkFrame(s2_inner, fg_color="transparent")
        input_row.pack(fill="x", pady=(0, 10))

        self.test_path_entry = ctk.CTkEntry(input_row, placeholder_text=r"Paste offline path here (e.g. \Users\ziga\Pictures\lidl.png or /Users/ziga/Pictures/lidl.png)...", height=36)
        sample_foreign = next((p for p in self.media_paths if (p.startswith("/") or p.startswith("\\")) and not ":" in p), r"\Users\ziga\Pictures\lidl.png")
        self.test_path_entry.insert(0, sample_foreign)
        self.test_path_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        btn_calc = ctk.CTkButton(input_row, text="Calculate Mapping", height=36, width=150, command=self._calculate_custom_path, fg_color="#f59e0b", hover_color="#d97706", font=ctk.CTkFont(weight="bold"))
        btn_calc.pack(side="left")

        self.calc_result_frame = ctk.CTkFrame(s2_inner, fg_color="#131418", corner_radius=6)
        self.calc_result_frame.pack(fill="x", pady=(4, 0))
        self._calculate_custom_path()

        # --- Section 3: All Currently Configured Mounts in DaVinci ---
        sec3_card = ctk.CTkFrame(self.container, fg_color="#181a20", corner_radius=8, border_color="#2b2d38", border_width=1)
        sec3_card.pack(fill="x", pady=(0, 14))

        s3_inner = ctk.CTkFrame(sec3_card, fg_color="transparent")
        s3_inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(s3_inner, text="📁 Mounts Currently in DaVinci Resolve Preferences:", font=ctk.CTkFont(size=14, weight="bold"), text_color="#60a5fa").pack(anchor="w", pady=(0, 8))

        curr_mounts = self.pref_manager.read_mounts()
        if curr_mounts:
            for m in curr_mounts:
                m_row = ctk.CTkFrame(s3_inner, fg_color="#111216", corner_radius=6)
                m_row.pack(fill="x", pady=2, padx=2)
                r_inner = ctk.CTkFrame(m_row, fg_color="transparent")
                r_inner.pack(fill="x", padx=10, pady=6)
                tag = "🗺️ Mapped Mount" if m.get("mapped") else "💾 Media Storage"
                tag_col = "#a855f7" if m.get("mapped") else "#3b82f6"
                ctk.CTkLabel(r_inner, text=f"[{tag}]", font=ctk.CTkFont(size=11, weight="bold"), text_color=tag_col, width=120, anchor="w").pack(side="left")
                m_text = f"Local: {m.get('root', '')}"
                if m.get("mapped"):
                    m_text += f"   <===   Remote: {m.get('mapped', '')}"
                ctk.CTkLabel(r_inner, text=m_text, font=ctk.CTkFont(family="Consolas", size=11), text_color="#e2e8f0").pack(side="left")
        else:
            ctk.CTkLabel(s3_inner, text="No custom mounts currently saved in DaVinci preferences.", font=ctk.CTkFont(size=11), text_color="#9ca3af").pack(anchor="w")

        # --- Section 4: Alternative 1-Click Relink in Media Pool ---
        sec4_card = ctk.CTkFrame(self.container, fg_color="#181a20", corner_radius=8, border_color="#2b2d38", border_width=1)
        sec4_card.pack(fill="x", pady=(0, 14))

        s4_inner = ctk.CTkFrame(sec4_card, fg_color="transparent")
        s4_inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(s4_inner, text="⚡ Alternative: 1-Click Relink in Media Pool", font=ctk.CTkFont(size=14, weight="bold"), text_color="#10b981").pack(anchor="w", pady=(0, 4))
        relink_desc = (
            "If you prefer not to touch Preferences, you can also relink clips in 2 clicks:\n"
            f"1. In DaVinci Resolve Media Pool, right-click the red clip (or right-click the 'Master' bin).\n"
            "2. Select 'Relink Selected Clips...' (or 'Relink Clips for Selected Bin...').\n"
            f"3. Select your ResolveSync download folder: {self.current_folder}\n"
            "4. DaVinci Resolve will scan the folder recursively and relink all clips in seconds!"
        )
        ctk.CTkLabel(s4_inner, text=relink_desc, font=ctk.CTkFont(size=11), text_color="#d1d5db", justify="left").pack(anchor="w", pady=(0, 10))

        btn_open_f = ctk.CTkButton(
            s4_inner,
            text=f"📂 Open '{os.path.basename(self.current_folder)}' in File Explorer",
            command=lambda: open_folder_in_explorer(self.current_folder),
            fg_color="#374151",
            hover_color="#4b5563"
        )
        btn_open_f.pack(anchor="w")

        # Close button
        btn_close = ctk.CTkButton(self.container, text="Close Assistant", font=ctk.CTkFont(size=13, weight="bold"), command=self.destroy, fg_color="#2563eb", height=38)
        btn_close.pack(fill="x", pady=(8, 4))

    def _auto_apply_mount(self, remote: str, local: str):
        ok, msg = self.pref_manager.add_or_update_mount(remote, local)
        if ok:
            messagebox.showinfo("DaVinci Preferences Configured", msg, parent=self)
            self._render_content()
        else:
            messagebox.showerror("Error Updating DaVinci Preferences", msg, parent=self)

    def _calculate_custom_path(self):
        for w in self.calc_result_frame.winfo_children():
            w.destroy()

        raw_input = self.test_path_entry.get().strip()
        if not raw_input:
            ctk.CTkLabel(self.calc_result_frame, text="Enter a path above and click 'Calculate Mapping'.", text_color="#9ca3af").pack(padx=12, pady=10)
            return

        recs = calculate_mapped_mounts([raw_input], self.current_folder, IS_WIN)
        if not recs:
            clean = raw_input.replace('\\', '/')
            cand1 = os.path.normpath(os.path.join(self.current_folder, "Root", clean.lstrip('/')))
            cand2 = os.path.normpath(os.path.join(self.current_folder, clean.lstrip('/')))
            local_found = cand1 if os.path.exists(cand1) else cand2
            exists = os.path.exists(local_found)
            size_str = f" ({format_bytes(os.path.getsize(local_found))})" if exists else " (Not found on disk yet)"

            p_frame = ctk.CTkFrame(self.calc_result_frame, fg_color="transparent")
            p_frame.pack(fill="x", padx=12, pady=10)
            ctk.CTkLabel(p_frame, text=f"• Disk Location: {local_found}{size_str}", font=ctk.CTkFont(family="Consolas", size=11), text_color="#10b981" if exists else "#f59e0b").pack(anchor="w")
            return

        r = recs[0]
        st = self.pref_manager.check_mount_status(r["remote"], r["local"])

        p_frame = ctk.CTkFrame(self.calc_result_frame, fg_color="transparent")
        p_frame.pack(fill="x", padx=12, pady=10)

        top_p = ctk.CTkFrame(p_frame, fg_color="transparent")
        top_p.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(top_p, text=f"Calculated Rule for '{os.path.basename(raw_input)}':", font=ctk.CTkFont(size=12, weight="bold"), text_color="#f59e0b").pack(side="left")
        ctk.CTkLabel(top_p, text=f" {st['badge']} ", font=ctk.CTkFont(size=11, weight="bold"), fg_color=st.get("color", "#374151"), text_color="#ffffff", corner_radius=6).pack(side="right")

        # Mapped Mount
        row1 = ctk.CTkFrame(p_frame, fg_color="transparent")
        row1.pack(fill="x", pady=2)
        ctk.CTkLabel(row1, text="Mapped Mount (Remote):", width=180, anchor="w", font=ctk.CTkFont(size=11)).pack(side="left")
        e1 = ctk.CTkEntry(row1, font=ctk.CTkFont(family="Consolas", size=11))
        e1.insert(0, r["remote"])
        e1.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(row1, text="📋 Copy", width=75, fg_color="#2563eb", command=lambda t=r["remote"]: copy_to_clipboard(self, t, self.status_feedback)).pack(side="left")

        # Local Mount
        row2 = ctk.CTkFrame(p_frame, fg_color="transparent")
        row2.pack(fill="x", pady=2)
        ctk.CTkLabel(row2, text="Local Mount (Windows):", width=180, anchor="w", font=ctk.CTkFont(size=11)).pack(side="left")
        e2 = ctk.CTkEntry(row2, font=ctk.CTkFont(family="Consolas", size=11))
        e2.insert(0, r["local"])
        e2.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(row2, text="📋 Copy", width=75, fg_color="#059669", command=lambda t=r["local"]: copy_to_clipboard(self, t, self.status_feedback)).pack(side="left")

        if r.get("verified_path") and os.path.exists(r["verified_path"]):
            sz = format_bytes(os.path.getsize(r["verified_path"]))
            v_msg = f"🟢 File verified on disk: {r['verified_path']} ({sz})"
            ctk.CTkLabel(p_frame, text=v_msg, font=ctk.CTkFont(family="Consolas", size=11, weight="bold"), text_color="#10b981").pack(anchor="w", pady=(6, 2))

        # Action button if needs fix
        if st.get("needs_fix"):
            btn_act_text = "⚡ Fix in DaVinci Preferences" if st["status"] == "slash_mismatch" else "⚡ Auto-Add to DaVinci Preferences"
            btn_act_col = "#d97706" if st["status"] == "slash_mismatch" else "#2563eb"
            btn_act = ctk.CTkButton(
                p_frame,
                text=btn_act_text,
                fg_color=btn_act_col,
                font=ctk.CTkFont(weight="bold"),
                height=30,
                command=lambda rm=r["remote"], lm=r["local"]: self._auto_apply_mount(rm, lm)
            )
            btn_act.pack(anchor="w", pady=(6, 2))


# ---------------------------------------------------------------------------
# Settings & Configuration Dialog
# ---------------------------------------------------------------------------

class SettingsDialog(ctk.CTkToplevel):
    """Configuration dialog for TrueNAS server connection and path mappings."""

    def __init__(self, parent, config_data: dict, on_save_callback, suggested_dirs: Optional[List[str]] = None):
        super().__init__(parent)
        self.config_data = config_data
        self.on_save_callback = on_save_callback
        self.suggested_dirs = suggested_dirs or []

        self.title("ResolveSync Settings - TrueNAS & Path Mappings")
        self.geometry("680x720")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._build_ui()

    def _build_ui(self):
        container = ctk.CTkScrollableFrame(self, width=640, height=680)
        container.pack(fill="both", expand=True, padx=20, pady=20)

        # Title
        lbl = ctk.CTkLabel(container, text="TrueNAS Hub Connection (Docker)", font=ctk.CTkFont(size=16, weight="bold"))
        lbl.pack(anchor="w", pady=(0, 10))

        srv = self.config_data.get("server", {})
        default_url = srv.get("server_url") or srv.get("url") or (srv.get("host") if str(srv.get("host", "")).startswith("http") else "http://192.168.1.3:5000")
        self.url_entry = self._create_field(container, "TrueNAS Hub URL:", default_url)

        # Test Connection Button
        btn_test = ctk.CTkButton(container, text="🔌 Test TrueNAS Hub Connection", command=self._test_connection, fg_color="#374151")
        btn_test.pack(fill="x", pady=(8, 16))

        self.test_status_lbl = ctk.CTkLabel(container, text="", font=ctk.CTkFont(size=12))
        self.test_status_lbl.pack(anchor="w", pady=(0, 16))

        # Default Download / Sync Folder
        def_download = self.config_data.get("sync_root_folder") or get_default_download_dir()
        self.download_entry = self._create_field_with_browse(container, "Default Download Folder:", def_download)

        # Native DaVinci Auto-Sync status frame
        auto_frame = ctk.CTkFrame(container, fg_color="#132438", border_color="#2563eb", border_width=1, corner_radius=8)
        auto_frame.pack(fill="x", pady=(12, 16), padx=2)
        ctk.CTkLabel(auto_frame, text="✨ Native DaVinci Auto-Sync (Active)", font=ctk.CTkFont(size=13, weight="bold"), text_color="#60a5fa").pack(anchor="w", padx=14, pady=(10, 4))
        auto_desc = (
            "• Footage anywhere on your computer (C:, D:, /Volumes, SMB) automatically syncs.\n"
            "• Zero manual folder mapping rules required for your project footage.\n"
            "• When downloading on Mac or another PC, files download to your chosen\n"
            "  Download Folder preserving the exact drive structure for 1-click DaVinci relinking."
        )
        ctk.CTkLabel(auto_frame, text=auto_desc, font=ctk.CTkFont(size=11), text_color="#93c5fd", justify="left").pack(anchor="w", padx=14, pady=(0, 10))

        # PostgreSQL Project Server Section
        ctk.CTkLabel(container, text="DaVinci Project Server (PostgreSQL / Free & Studio)", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", pady=(14, 4))
        pg_desc = (
            "Enables direct project discovery and media extraction without DaVinci Studio license!\n"
            "Click 'Import .resolvedbkey' to load connection settings automatically from your key file."
        )
        ctk.CTkLabel(container, text=pg_desc, font=ctk.CTkFont(size=11), text_color="#9ca3af", wraplength=600, justify="left").pack(anchor="w", pady=(0, 10))

        pg = self.config_data.get("postgres", {})
        self.pg_host = self._create_field(container, "PostgreSQL Host / IP:", pg.get("host", "192.168.69.29"))
        self.pg_port = self._create_field(container, "Port (Local LAN):", str(pg.get("port", 5432)))
        self.pg_alt_host = self._create_field(container, "Fallback Host (WAN / Domain):", pg.get("alt_host", "thekingziga.com"))
        self.pg_alt_port = self._create_field(container, "Port (Fallback / WAN):", str(pg.get("alt_port", 12345)))
        self.pg_db = self._create_field(container, "Database Name:", pg.get("dbname", "main"))
        self.pg_user = self._create_field(container, "Database User:", pg.get("user", "main"))
        self.pg_pass = self._create_field(container, "Database Password:", pg.get("password", "12345"), show="*")

        pg_btn_row = ctk.CTkFrame(container, fg_color="transparent")
        pg_btn_row.pack(fill="x", pady=(8, 4))

        btn_import_key = ctk.CTkButton(pg_btn_row, text="🔑 Import .resolvedbkey", command=self._import_db_key, fg_color="#4f46e5", hover_color="#4338ca")
        btn_import_key.pack(side="left", padx=(0, 10))

        btn_test_pg = ctk.CTkButton(pg_btn_row, text="🔌 Test PostgreSQL Connection", command=self._test_postgres, fg_color="#374151")
        btn_test_pg.pack(side="left")

        self.pg_status_lbl = ctk.CTkLabel(container, text="", font=ctk.CTkFont(size=12))
        self.pg_status_lbl.pack(anchor="w", pady=(4, 16))

        # Divider for optional overrides
        ctk.CTkLabel(container, text="Custom Path Overrides (Optional)", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", pady=(6, 4))
        desc = "Only configure rules here if you want to override automatic disk mapping with a custom remote directory."
        ctk.CTkLabel(container, text=desc, font=ctk.CTkFont(size=11), text_color="#9ca3af", wraplength=600, justify="left").pack(anchor="w", pady=(0, 10))

        # Current rules container
        self.rules_frame = ctk.CTkFrame(container, fg_color="#18191f")
        self.rules_frame.pack(fill="x", pady=(0, 16))
        self._render_rules()

        # Add Rule Section
        ctk.CTkLabel(container, text="Add New Mapping Rule:", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", pady=(8, 4))
        self.new_name = self._create_field(container, "Rule Name:", "Main Footage")
        self.new_drp = self._create_field(container, "DRP Source Prefix:", "D:\\Footage" if IS_WIN else "/Volumes/Footage")
        self.new_local = self._create_field_with_browse(container, "Local Prefix:", "D:\\Footage" if IS_WIN else "/Volumes/Footage")
        self.new_remote = self._create_field(container, "TrueNAS Storage Prefix:", "/media/Footage")

        btn_add = ctk.CTkButton(container, text="+ Add Rule", command=self._add_rule, fg_color="#2563eb")
        btn_add.pack(anchor="e", pady=(6, 20))

        # Save Button
        btn_save = ctk.CTkButton(container, text="💾 Save Settings", font=ctk.CTkFont(size=14, weight="bold"), command=self._save_all, fg_color="#059669")
        btn_save.pack(fill="x", pady=(10, 0))

    def _create_field_with_browse(self, parent, label_text: str, default_val: str):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", pady=4)
        ctk.CTkLabel(f, text=label_text, width=200, anchor="w", font=ctk.CTkFont(size=12)).pack(side="left")
        entry = ctk.CTkEntry(f)
        entry.insert(0, default_val)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        def browse_folder():
            folder = filedialog.askdirectory(title=f"Select {label_text}")
            if folder:
                norm = os.path.normpath(folder)
                entry.delete(0, "end")
                entry.insert(0, norm)

        btn = ctk.CTkButton(f, text="Browse...", width=75, command=browse_folder, fg_color="#374151")
        btn.pack(side="right")
        return entry

    def _create_field(self, parent, label_text: str, default_val: str, show: str = ""):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", pady=4)
        ctk.CTkLabel(f, text=label_text, width=200, anchor="w", font=ctk.CTkFont(size=12)).pack(side="left")
        entry = ctk.CTkEntry(f, show=show)
        entry.insert(0, default_val)
        entry.pack(side="right", fill="x", expand=True)
        return entry

    def _render_rules(self):
        for widget in self.rules_frame.winfo_children():
            widget.destroy()

        mappings = self.config_data.get("path_mappings", [])
        if not mappings:
            ctk.CTkLabel(self.rules_frame, text="No custom path rules (Auto-Sync handles all disks).", text_color="#9ca3af").pack(pady=10)
            return

        for idx, rule in enumerate(mappings):
            rf = ctk.CTkFrame(self.rules_frame, fg_color="#22232a")
            rf.pack(fill="x", padx=8, pady=4)
            info = f"[{rule.get('name', 'Rule')}]\nDRP: {rule.get('drp_prefix')}\nLocal: {rule.get('local_prefix')}\nTrueNAS: {rule.get('remote_prefix')}"
            ctk.CTkLabel(rf, text=info, font=ctk.CTkFont(family="Consolas", size=11), justify="left").pack(side="left", padx=10, pady=8)
            btn_del = ctk.CTkButton(rf, text="Delete", width=60, fg_color="#ef4444", hover_color="#dc2626", command=lambda i=idx: self._delete_rule(i))
            btn_del.pack(side="right", padx=10)

    def _add_rule(self):
        rule = {
            "name": self.new_name.get().strip() or "Custom Rule",
            "drp_prefix": self.new_drp.get().strip(),
            "local_prefix": self.new_local.get().strip(),
            "remote_prefix": self.new_remote.get().strip(),
        }
        if not rule["drp_prefix"] or not rule["local_prefix"] or not rule["remote_prefix"]:
            messagebox.showwarning("Incomplete Rule", "Please fill in all prefix paths.")
            return

        self.config_data.setdefault("path_mappings", []).append(rule)
        self._render_rules()

    def _delete_rule(self, index: int):
        mappings = self.config_data.get("path_mappings", [])
        if 0 <= index < len(mappings):
            del mappings[index]
            self._render_rules()

    def _test_connection(self):
        self.test_status_lbl.configure(text="Connecting to TrueNAS Hub...", text_color="#9ca3af")
        self.update_idletasks()

        server_url = self.url_entry.get().strip()
        if not server_url:
            self.test_status_lbl.configure(text="Please enter a valid TrueNAS URL (e.g. http://192.168.1.3:5000)", text_color="#ef4444")
            return

        def run_test():
            try:
                engine = HTTPServerSyncEngine(server_url)
                ok, msg = engine.check_connection()
                if ok:
                    self.test_status_lbl.configure(text=f"✓ {msg}", text_color="#10b981")
                else:
                    self.test_status_lbl.configure(text=f"✗ Connection failed: {msg}", text_color="#ef4444")
            except Exception as e:
                self.test_status_lbl.configure(text=f"✗ Error: {e}", text_color="#ef4444")

        threading.Thread(target=run_test, daemon=True).start()

    def _import_db_key(self):
        fpath = filedialog.askopenfilename(
            title="Select DaVinci Resolve Project Library Key (.resolvedbkey)",
            filetypes=[("Resolve DB Key", "*.resolvedbkey"), ("XML Files", "*.xml"), ("All Files", "*.*")]
        )
        if fpath:
            try:
                parsed = DaVinciPostgresReader.parse_resolvedbkey(fpath)
                self.pg_host.delete(0, "end"); self.pg_host.insert(0, parsed["host"])
                self.pg_port.delete(0, "end"); self.pg_port.insert(0, str(parsed["port"]))
                self.pg_db.delete(0, "end"); self.pg_db.insert(0, parsed["dbname"])
                self.pg_user.delete(0, "end"); self.pg_user.insert(0, parsed["user"])
                self.pg_pass.delete(0, "end"); self.pg_pass.insert(0, parsed["password"])
                self.pg_status_lbl.configure(text=f"✓ Loaded credentials from {os.path.basename(fpath)}", text_color="#10b981")
            except Exception as ex:
                self.pg_status_lbl.configure(text=f"✗ Error parsing key: {ex}", text_color="#ef4444")

    def _test_postgres(self):
        self.pg_status_lbl.configure(text="Connecting to PostgreSQL server...", text_color="#9ca3af")
        self.update_idletasks()

        reader = DaVinciPostgresReader(
            host=self.pg_host.get().strip(),
            port=int(self.pg_port.get().strip() or "5432"),
            user=self.pg_user.get().strip(),
            password=self.pg_pass.get().strip(),
            dbname=self.pg_db.get().strip(),
            alt_host=self.pg_alt_host.get().strip() or None,
            alt_port=int(self.pg_alt_port.get().strip() or "5432") if self.pg_alt_port.get().strip() else None,
        )

        def worker():
            ok, msg = reader.test_connection()
            if ok:
                self.after(0, lambda: self.pg_status_lbl.configure(text=f"✓ {msg}", text_color="#10b981"))
            else:
                self.after(0, lambda: self.pg_status_lbl.configure(text=f"✗ {msg}", text_color="#ef4444"))

        threading.Thread(target=worker, daemon=True).start()

    def _save_all(self):
        url_val = self.url_entry.get().strip()
        self.config_data["server"] = {
            "server_url": url_val,
            "host": url_val,
        }
        self.config_data["sync_root_folder"] = self.download_entry.get().strip()

        # Save PostgreSQL settings
        self.config_data["postgres"] = {
            "enabled": True,
            "host": self.pg_host.get().strip(),
            "port": int(self.pg_port.get().strip() or "5432"),
            "alt_host": self.pg_alt_host.get().strip(),
            "alt_port": int(self.pg_alt_port.get().strip() or "5432") if self.pg_alt_port.get().strip() else None,
            "dbname": self.pg_db.get().strip(),
            "user": self.pg_user.get().strip(),
            "password": self.pg_pass.get().strip(),
        }

        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config_data, f, indent=2)
            self.on_save_callback(self.config_data)
            self.destroy()
        except Exception as ex:
            messagebox.showerror("Error Saving", f"Failed to save {CONFIG_FILE}: {ex}")


# ---------------------------------------------------------------------------
# Main Desktop Application GUI
# ---------------------------------------------------------------------------

class ResolveSyncAppGUI(ctk.CTk):
    """Universal Desktop Application GUI for Windows and macOS."""

    def __init__(self):
        super().__init__()

        if HAS_CUSTOMTKINTER:
            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("blue")

        self.title(f"ResolveSync v{__version__} - DaVinci Resolve Media Synchronizer ({OS_NAME})")
        self.geometry("1180x880")
        self.minsize(1060, 740)

        # Window Icon
        for candidate_icon in [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_icon.ico"),
            os.path.join(getattr(sys, "_MEIPASS", ""), "app_icon.ico"),
            "app_icon.ico",
        ]:
            if candidate_icon and os.path.exists(candidate_icon):
                try:
                    self.iconbitmap(candidate_icon)
                    break
                except Exception:
                    pass

        # State Variables
        self.config_data = self._load_config()
        self.pref_manager = DaVinciPreferencesManager()
        self.current_drp_path: Optional[str] = None
        self.live_project_media: Optional[List[str]] = None
        self.active_project_name: str = ""
        self.active_project_source: str = "PostgreSQL DB"
        self.media_items: List[MediaItem] = []
        self.is_syncing: bool = False
        self.stop_requested: bool = False
        self.db_projects_cache: List[dict] = []
        self.media_filter_var = ctk.StringVar(value="🎬 All Media (Both)")
        self.debug_logs_var = ctk.BooleanVar(value=self.config_data.get("debug_logging", False))
        if self.debug_logs_var.get():
            set_debug_logging(True)

        self._build_main_ui()

        self._log(f"ResolveSync v{__version__} ({OS_NAME}) started.")
        self._log(f"📄 Full debug log file: {LOG_FILE_PATH}")

        # Populate project sources on startup
        self._populate_postgres_projects()
        self._populate_recent_projects()
        # Automatic live Resolve connection disabled per user request (use manual button)

    def _load_config(self) -> dict:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(exe_dir, "config.json"),
            os.path.join(exe_dir, "..", "Resources", "config.json"),
            "config.json",
            os.path.join(exe_dir, "config.example.json"),
            os.path.join(exe_dir, "..", "Resources", "config.example.json"),
            "config.example.json",
        ]
        for c in candidates:
            if os.path.exists(c):
                try:
                    with open(c, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    try:
                        with open(CONFIG_FILE, "w", encoding="utf-8") as fp:
                            json.dump(data, fp, indent=2)
                    except Exception:
                        pass
                    return data
                except Exception:
                    pass
        return {"server": {}, "path_mappings": [], "sync_options": {}}

    def _build_main_ui(self):
        # 1. Top Navigation Bar (Clean & Spacious)
        top_bar = ctk.CTkFrame(self, height=64, fg_color="#18191f", corner_radius=0)
        top_bar.pack(fill="x", side="top")

        # Brand, Version & Platform Badges
        brand_frame = ctk.CTkFrame(top_bar, fg_color="transparent")
        brand_frame.pack(side="left", padx=20, pady=12)

        ctk.CTkLabel(brand_frame, text="ResolveSync", font=ctk.CTkFont(size=20, weight="bold")).pack(side="left", padx=(0, 8))

        ver_badge = ctk.CTkLabel(
            brand_frame,
            text=f"v{__version__}",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#4f46e5",
            text_color="#ffffff",
            corner_radius=6,
        )
        ver_badge.pack(side="left", padx=4)

        badge_color = "#2563eb" if IS_WIN else "#0284c7"
        badge_text = f"{OS_NAME.upper()}"
        badge = ctk.CTkLabel(
            brand_frame,
            text=badge_text,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=badge_color,
            corner_radius=6,
        )
        badge.pack(side="left", padx=4)

        # Right Header Buttons
        btn_about = ctk.CTkButton(
            top_bar,
            text="👑 About Žiga",
            width=115,
            command=self._focus_about_tab,
            fg_color="#1e1f26",
            hover_color="#2b2d38",
            border_color="#3b3e4f",
            border_width=1,
            font=ctk.CTkFont(size=12, weight="bold")
        )
        btn_about.pack(side="right", padx=(0, 16), pady=14)

        btn_log = ctk.CTkButton(
            top_bar,
            text="📄 Logs",
            width=85,
            command=open_log_file,
            fg_color="#22242b",
            hover_color="#2d3039",
            font=ctk.CTkFont(size=12)
        )
        btn_log.pack(side="right", padx=(0, 8), pady=14)

        btn_settings = ctk.CTkButton(
            top_bar,
            text="⚙️ Settings",
            width=115,
            command=self._open_settings,
            fg_color="#2d3039",
            hover_color="#373a46",
            font=ctk.CTkFont(size=12)
        )
        btn_settings.pack(side="right", padx=(0, 8), pady=14)

        btn_tips = ctk.CTkButton(
            top_bar,
            text="💡 Setup Tips",
            width=120,
            command=self._open_tips_dialog,
            fg_color="#2d3039",
            hover_color="#373a46",
            font=ctk.CTkFont(size=12)
        )
        btn_tips.pack(side="right", padx=(0, 8), pady=14)

        btn_map_top = ctk.CTkButton(
            top_bar,
            text="🗺️ Mapped Mounts",
            width=145,
            command=self._open_mapped_mounts_helper,
            fg_color="#374151",
            hover_color="#4b5563",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        btn_map_top.pack(side="right", padx=(0, 8), pady=14)

        btn_open_davinci_top = ctk.CTkButton(
            top_bar,
            text="🎬 Open DaVinci",
            width=140,
            command=self._launch_davinci_app,
            fg_color="#6366f1",
            hover_color="#4f46e5",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        btn_open_davinci_top.pack(side="right", padx=(0, 10), pady=14)

        # 2. Main Content Frame
        content_frame = ctk.CTkFrame(self, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, padx=20, pady=12)

        # --- A. Project Loader Card ---
        loader_card = ctk.CTkFrame(content_frame, fg_color="#1c1d24", corner_radius=10)
        loader_card.pack(fill="x", pady=(0, 10), padx=2)

        # Source Selection Tabs
        src_header = ctk.CTkFrame(loader_card, fg_color="transparent")
        src_header.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            src_header,
            text="Project Source:",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=100,
            anchor="w"
        ).pack(side="left")

        self.source_selector = ctk.CTkSegmentedButton(
            src_header,
            values=["🗄️ Network Database", "⚡ Live DaVinci Resolve", "📁 DRP Archive File"],
            command=self._on_source_tab_changed,
        )
        self.source_selector.set("🗄️ Network Database")
        self.source_selector.pack(side="left", padx=(0, 10))

        # View 1: PostgreSQL Network Database (Active by default)
        self.db_frame = ctk.CTkFrame(loader_card, fg_color="transparent")
        self.db_frame.pack(fill="x", padx=16, pady=(4, 6))

        ctk.CTkLabel(self.db_frame, text="Select Project:", font=ctk.CTkFont(size=12, weight="bold"), width=100, anchor="w").pack(side="left")

        self.db_project_combo = ctk.CTkComboBox(self.db_frame, values=["Connecting to PostgreSQL..."], width=300)
        self.db_project_combo.pack(side="left", padx=(0, 8))

        btn_load_db = ctk.CTkButton(
            self.db_frame,
            text="📂 Load Project",
            width=120,
            command=self._load_postgres_selected,
            fg_color="#4f46e5",
            hover_color="#4338ca",
            font=ctk.CTkFont(weight="bold")
        )
        btn_load_db.pack(side="left", padx=(0, 8))

        btn_key = ctk.CTkButton(
            self.db_frame,
            text="🔑 Import .resolvedbkey",
            width=165,
            command=self._import_db_key_from_main,
            fg_color="#374151",
            hover_color="#4b5563"
        )
        btn_key.pack(side="left", padx=(0, 10))

        self.db_status_lbl = ctk.CTkLabel(
            self.db_frame,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="#9ca3af",
            anchor="w"
        )
        self.db_status_lbl.pack(side="left", fill="x", expand=True)

        # View 2: Live DaVinci Resolve Connection & Recent Projects (Hidden initially)
        self.live_frame = ctk.CTkFrame(loader_card, fg_color="transparent")

        self.btn_connect_live = ctk.CTkButton(
            self.live_frame,
            text="⚡ Connect Live Resolve",
            width=180,
            font=ctk.CTkFont(weight="bold"),
            command=self._connect_live_resolve,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
        )
        self.btn_connect_live.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(self.live_frame, text="Or Recent:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(6, 6))

        self.recent_combo = ctk.CTkComboBox(self.live_frame, values=["Loading recent projects..."], width=280)
        self.recent_combo.pack(side="left", padx=(0, 8))

        btn_load_recent = ctk.CTkButton(self.live_frame, text="Load Recent", width=100, command=self._load_recent_selected, fg_color="#374151")
        btn_load_recent.pack(side="left", padx=(0, 12))

        self.live_status_lbl = ctk.CTkLabel(
            self.live_frame,
            text="Click '⚡ Connect Live Resolve' if you have a project open in DaVinci",
            font=ctk.CTkFont(size=12),
            text_color="#9ca3af",
            anchor="w"
        )
        self.live_status_lbl.pack(side="left", fill="x", expand=True)

        # View 3: Direct DRP Project Archive Picker (Hidden initially)
        self.drp_frame = ctk.CTkFrame(loader_card, fg_color="transparent")

        ctk.CTkLabel(self.drp_frame, text="DRP File:", font=ctk.CTkFont(size=12, weight="bold"), width=100, anchor="w").pack(side="left")

        self.drp_path_entry = ctk.CTkEntry(self.drp_frame, placeholder_text="Browse or paste path to your DaVinci project archive (.drp or .zip)...")
        self.drp_path_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        btn_browse = ctk.CTkButton(self.drp_frame, text="📁 Browse .drp", width=120, command=self._browse_drp, fg_color="#3b82f6")
        btn_browse.pack(side="left", padx=(0, 8))

        btn_scan = ctk.CTkButton(self.drp_frame, text="🔍 Analyze", width=100, command=self._scan_drp_project, fg_color="#10b981", hover_color="#059669")
        btn_scan.pack(side="left")

        # Active Project Context Banner
        self.active_proj_frame = ctk.CTkFrame(loader_card, fg_color="#14151b", corner_radius=8, border_color="#2b2d38", border_width=1)
        self.active_proj_frame.pack(fill="x", padx=16, pady=(4, 6))

        proj_inner = ctk.CTkFrame(self.active_proj_frame, fg_color="transparent")
        proj_inner.pack(fill="x", padx=12, pady=6)

        ctk.CTkLabel(proj_inner, text="ACTIVE PROJECT:", font=ctk.CTkFont(size=11, weight="bold"), text_color="#9ca3af").pack(side="left", padx=(0, 6))
        self.active_proj_lbl = ctk.CTkLabel(proj_inner, text="None selected", font=ctk.CTkFont(size=12, weight="bold"), text_color="#d1d5db")
        self.active_proj_lbl.pack(side="left", padx=(0, 10))

        self.active_proj_stats_lbl = ctk.CTkLabel(proj_inner, text="Select a project above to analyze and sync", font=ctk.CTkFont(size=11), text_color="#9ca3af")
        self.active_proj_stats_lbl.pack(side="right")

        # Download / Sync Destination Folder & Mapped Mounts Action
        dest_row = ctk.CTkFrame(loader_card, fg_color="transparent")
        dest_row.pack(fill="x", padx=16, pady=(4, 12))

        ctk.CTkLabel(dest_row, text="Download To:", font=ctk.CTkFont(size=12, weight="bold"), width=100, anchor="w").pack(side="left")

        default_dest = self.config_data.get("sync_root_folder") or get_default_download_dir()
        self.dest_folder_entry = ctk.CTkEntry(dest_row, placeholder_text="Folder where media will be downloaded (e.g. D:\\DAVINCI or /Volumes/SSD)...")
        self.dest_folder_entry.insert(0, default_dest)
        self.dest_folder_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        btn_browse_dest = ctk.CTkButton(dest_row, text="Change Folder", width=115, command=self._browse_dest_folder, fg_color="#374151", hover_color="#4b5563")
        btn_browse_dest.pack(side="left", padx=(0, 8))

        btn_map_davinci = ctk.CTkButton(
            dest_row,
            text="🗺️ Map in DaVinci",
            width=135,
            command=self._open_mapped_mounts_helper,
            fg_color="#7c3aed",
            hover_color="#6d28d9",
            font=ctk.CTkFont(weight="bold")
        )
        btn_map_davinci.pack(side="left", padx=(0, 8))

        btn_auto_info = ctk.CTkLabel(dest_row, text="⚡ Auto-Sync Active", font=ctk.CTkFont(size=11, weight="bold"), text_color="#10b981", width=115)
        btn_auto_info.pack(side="left")

        # DaVinci Mapped Mount Warning Banner (auto-appears if DaVinci mount is missing or has slash mismatch)
        self.mount_alert_banner = ctk.CTkFrame(content_frame, fg_color="#381d06", corner_radius=8, border_color="#f59e0b", border_width=1)
        self.mount_alert_inner = ctk.CTkFrame(self.mount_alert_banner, fg_color="transparent")
        self.mount_alert_inner.pack(fill="x", padx=14, pady=10)
        self.mount_alert_lbl = ctk.CTkLabel(self.mount_alert_inner, text="", font=ctk.CTkFont(size=12, weight="bold"), text_color="#fde68a", justify="left")
        self.mount_alert_lbl.pack(side="left", fill="x", expand=True)
        self.mount_alert_fix_btn = ctk.CTkButton(self.mount_alert_inner, text="⚡ 1-Click Auto-Fix", width=145, fg_color="#d97706", hover_color="#b45309", font=ctk.CTkFont(weight="bold"))
        self.mount_alert_fix_btn.pack(side="left", padx=(8, 6))
        self.mount_alert_view_btn = ctk.CTkButton(self.mount_alert_inner, text="🗺️ View Details", width=110, fg_color="#374151", command=self._open_mapped_mounts_helper)
        self.mount_alert_view_btn.pack(side="left", padx=(0, 4))
        # Hidden by default until foreign media detected
        self.mount_alert_banner.pack_forget()

        # --- B. Summary Metrics Cards ---
        self.metrics_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        self.metrics_frame.pack(fill="x", pady=(0, 10), padx=2)

        self.card_total = self._create_metric_card(self.metrics_frame, "Total Clips", "0", "#f3f4f6")
        self.card_synced = self._create_metric_card(self.metrics_frame, "In Sync (Both)", "0", "#10b981")
        self.card_down = self._create_metric_card(self.metrics_frame, "Needs Download", "0", "#3b82f6")
        self.card_up = self._create_metric_card(self.metrics_frame, "Needs Upload", "0", "#8b5cf6")
        self.card_miss = self._create_metric_card(self.metrics_frame, "Missing Everywhere", "0", "#ef4444")
        self.card_unmapped = self._create_metric_card(self.metrics_frame, "Auto-Mapped", "0", "#10b981")

        # --- C. Command Center (Sync Controls & Proxy Filtering) ---
        ctrl_card = ctk.CTkFrame(content_frame, fg_color="#1c1d24", corner_radius=10)
        ctrl_card.pack(fill="x", pady=(0, 10), padx=2)

        # Row 1: Selectors for Media Content & Sync Direction
        ctrl_selectors = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        ctrl_selectors.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(ctrl_selectors, text="Media Content:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 8))

        self.media_filter_selector = ctk.CTkSegmentedButton(
            ctrl_selectors,
            values=["🎬 All Media (Both)", "⚡ Proxies Only (Fast)", "🎥 Camera Originals"],
            variable=self.media_filter_var,
            command=self._on_media_filter_changed,
        )
        self.media_filter_selector.set("🎬 All Media (Both)")
        self.media_filter_selector.pack(side="left", padx=(0, 20))

        ctk.CTkLabel(ctrl_selectors, text="Sync Mode:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 8))

        self.mode_var = ctk.StringVar(value="sync")
        self.mode_selector = ctk.CTkSegmentedButton(
            ctrl_selectors,
            values=["🔄 Two-Way Sync", "⬇️ Pull from NAS", "⬆️ Push to NAS", "🔍 Dry Run"],
            variable=self.mode_var,
        )
        self.mode_selector.set("🔄 Two-Way Sync")
        self.mode_selector.pack(side="left")

        # Row 2: Status Breakdown & Action Buttons
        ctrl_actions = ctk.CTkFrame(ctrl_card, fg_color="transparent")
        ctrl_actions.pack(fill="x", padx=16, pady=(4, 12))

        self.media_summary_lbl = ctk.CTkLabel(
            ctrl_actions,
            text="📊 Ready to sync: Select a project above to analyze media.",
            font=ctk.CTkFont(size=12),
            text_color="#9ca3af",
            anchor="w"
        )
        self.media_summary_lbl.pack(side="left", fill="x", expand=True)

        # Buttons on Right: Start Sync, Cancel, Launch DaVinci
        self.btn_open_davinci_ctrl = ctk.CTkButton(
            ctrl_actions,
            text="🎬 Open DaVinci",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._launch_davinci_app,
            fg_color="#6366f1",
            hover_color="#4f46e5",
            width=135,
        )
        self.btn_open_davinci_ctrl.pack(side="right", padx=(8, 0))

        self.btn_stop_sync = ctk.CTkButton(
            ctrl_actions,
            text="⏹️ Cancel",
            command=self._cancel_sync,
            fg_color="#dc2626",
            hover_color="#b91c1c",
            width=85,
            state="disabled",
        )
        self.btn_stop_sync.pack(side="right", padx=(8, 0))

        self.btn_select_files = ctk.CTkButton(
            ctrl_actions,
            text="📋 Select Files...",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._open_selective_sync_dialog,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            width=130,
        )
        self.btn_select_files.pack(side="right", padx=(8, 0))

        self.btn_start_sync = ctk.CTkButton(
            ctrl_actions,
            text="🚀 Start Sync",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._start_sync_thread,
            fg_color="#059669",
            hover_color="#047857",
            width=140,
        )
        self.btn_start_sync.pack(side="right")

        # --- D. Live Progress Section ---
        self.progress_frame = ctk.CTkFrame(content_frame, fg_color="#1c1d24", corner_radius=10)
        self.progress_frame.pack(fill="x", pady=(0, 10), padx=2)

        prog_inner = ctk.CTkFrame(self.progress_frame, fg_color="transparent")
        prog_inner.pack(fill="x", padx=16, pady=10)

        self.progress_lbl = ctk.CTkLabel(prog_inner, text="Ready to synchronize.", font=ctk.CTkFont(size=12))
        self.progress_lbl.pack(anchor="w", pady=(0, 4))

        self.progress_bar = ctk.CTkProgressBar(prog_inner, height=12)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", pady=(0, 6))

        self.progress_stats = ctk.CTkLabel(prog_inner, text="0 / 0 bytes (0 MB/s)", font=ctk.CTkFont(size=11), text_color="#9ca3af")
        self.progress_stats.pack(anchor="w")

        # --- E. Main Notebook: Log Console, About Creator Tab, Setup Guide ---
        self.main_tabview = ctk.CTkTabview(content_frame, fg_color="#1c1d24", corner_radius=10)
        self.main_tabview.pack(fill="both", expand=True, padx=2)

        tab_log = self.main_tabview.add("📜 Sync Activity & Console")
        tab_about = self.main_tabview.add("👑 About Žiga (@thekingziga)")
        tab_guide = self.main_tabview.add("💡 Quick Setup Guide")

        # Tab 1: Activity Log
        list_header = ctk.CTkFrame(tab_log, fg_color="transparent")
        list_header.pack(fill="x", padx=12, pady=(4, 6))
        ctk.CTkLabel(list_header, text="Real-time Synchronization & Media Log", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")

        btn_open = ctk.CTkButton(list_header, text="📄 Open File", width=85, height=26, command=open_log_file, fg_color="#2d3039", hover_color="#373a46", font=ctk.CTkFont(size=11))
        btn_open.pack(side="right", padx=(6, 0))

        btn_clear = ctk.CTkButton(list_header, text="🧹 Clear", width=65, height=26, command=self._clear_log, fg_color="#2d3039", hover_color="#373a46", font=ctk.CTkFont(size=11))
        btn_clear.pack(side="right", padx=(6, 0))

        self.sw_debug = ctk.CTkSwitch(
            list_header,
            text="Debug Logs",
            variable=self.debug_logs_var,
            command=self._toggle_debug_logs,
            font=ctk.CTkFont(size=11),
            width=90,
        )
        self.sw_debug.pack(side="right", padx=(0, 10))

        self.log_text = ctk.CTkTextbox(tab_log, font=ctk.CTkFont(family="Consolas", size=11), fg_color="#121316", text_color="#d1d5db")
        self.log_text.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        # Tab 2: About Creator
        self._build_about_tab(tab_about)

        # Tab 3: Setup Guide
        self._build_guide_tab(tab_guide)

    def _build_about_tab(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=8, pady=8)

        # Header Profile Card
        hdr = ctk.CTkFrame(scroll, fg_color="#22242c", corner_radius=10, border_color="#374151", border_width=1)
        hdr.pack(fill="x", pady=(0, 10), padx=4)

        hdr_inner = ctk.CTkFrame(hdr, fg_color="transparent")
        hdr_inner.pack(fill="x", padx=16, pady=16)

        ctk.CTkLabel(
            hdr_inner,
            text="👑 Žiga Vodnjov Frelih",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#60a5fa",
        ).pack(anchor="w")

        ctk.CTkLabel(
            hdr_inner,
            text="aka thekingziga | TheKingZiga • Domžale, Slovenia 🇸🇮",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#9ca3af",
        ).pack(anchor="w", pady=(2, 6))

        ctk.CTkLabel(
            hdr_inner,
            text="Video Editor • Software Developer • Tech Content Creator • Self-Hosting & Homelab Architect",
            font=ctk.CTkFont(size=12),
            text_color="#d1d5db",
        ).pack(anchor="w")

        # Quick Links Button Bar
        links_bar = ctk.CTkFrame(hdr_inner, fg_color="transparent")
        links_bar.pack(anchor="w", pady=(12, 0))

        for text, url, col, hov in [
            ("🌐 thekingziga.com", "https://www.thekingziga.com", "#2563eb", "#1d4ed8"),
            ("🐙 GitHub: @thekingziga", "https://github.com/thekingziga", "#374151", "#4b5563"),
            ("📺 YouTube: @zigavf", "https://www.youtube.com/@zigavf", "#dc2626", "#b91c1c"),
            ("🎮 Twitch: thekingziga", "https://www.twitch.tv/thekingziga", "#7c3aed", "#6d28d9"),
        ]:
            b = ctk.CTkButton(
                links_bar,
                text=text,
                font=ctk.CTkFont(size=11, weight="bold"),
                command=lambda u=url: webbrowser.open_new_tab(u),
                fg_color=col,
                hover_color=hov,
                height=30,
            )
            b.pack(side="left", padx=(0, 8))

        # Card 2: Story & Why ResolveSync was created
        card_story = ctk.CTkFrame(scroll, fg_color="#18191f", corner_radius=10, border_color="#2b2d38", border_width=1)
        card_story.pack(fill="x", pady=(0, 10), padx=4)

        ctk.CTkLabel(
            card_story,
            text="🚀 The Story of ResolveSync",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#f59e0b",
        ).pack(anchor="w", padx=16, pady=(12, 6))

        story_text = (
            "As a content creator and video editor running multiple production channels, gaming videos, and vlogs, "
            "I frequently collaborate between my powerful Windows editing rig, MacBook laptops on the go, and home server.\n\n"
            "Official Blackmagic Cloud charges $5/month for project libraries, and DaVinci Resolve Free normally prevents "
            "remote collaboration and scripting APIs. I refused to let paid subscriptions limit great storytelling.\n\n"
            "I built ResolveSync to give every video editor the full power of cloud proxy workflows, automatic path translation "
            "(Windows D:\\ ↔ macOS /Users), and direct PostgreSQL project library extraction — 100% free, private, and hosted "
            "on your own TrueNAS or NAS network."
        )
        ctk.CTkLabel(
            card_story,
            text=story_text,
            font=ctk.CTkFont(size=12),
            text_color="#d1d5db",
            justify="left",
            wraplength=850,
        ).pack(anchor="w", padx=16, pady=(0, 14))

        # Card 3: Homelab & Infrastructure Background
        card_lab = ctk.CTkFrame(scroll, fg_color="#18191f", corner_radius=10, border_color="#2b2d38", border_width=1)
        card_lab.pack(fill="x", pady=(0, 10), padx=4)

        ctk.CTkLabel(
            card_lab,
            text="🛠️ Homelab & Self-Hosting Stack",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#10b981",
        ).pack(anchor="w", padx=16, pady=(12, 6))

        lab_text = (
            "• Virtualization & OS: Proxmox VE, TrueNAS SCALE, Debian & Ubuntu Server, pfSense firewall routing\n"
            "• Network Infrastructure: 10GbE SFP+ local storage pool, WireGuard & Cloudflare tunnels for remote editing\n"
            "• Containerized Microservices: Docker, PostgreSQL Project Servers, automated transcode nodes\n"
            "• Content & Community: Gaming (Minecraft, Fortnite, Rust, Hytale), tech tutorials, and homelab builds on YouTube (@zigavf)"
        )
        ctk.CTkLabel(
            card_lab,
            text=lab_text,
            font=ctk.CTkFont(size=12),
            text_color="#d1d5db",
            justify="left",
            wraplength=850,
        ).pack(anchor="w", padx=16, pady=(0, 14))

    def _build_guide_tab(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=8, pady=8)

        card1 = ctk.CTkFrame(scroll, fg_color="#18191f", corner_radius=10, border_color="#2b2d38", border_width=1)
        card1.pack(fill="x", pady=(0, 10), padx=4)

        ctk.CTkLabel(card1, text="⚡ 1. Proxies vs. Camera Originals Workflow", font=ctk.CTkFont(size=14, weight="bold"), text_color="#60a5fa").pack(anchor="w", padx=16, pady=(12, 4))
        g1 = (
            "• Travel / Laptop Mode: In ResolveSync, select '⚡ Proxies Only (Fast)' to pull lightweight ProRes/H.264 offline clips in seconds.\n"
            "• DaVinci Setting: In DaVinci Resolve, verify 'Playback -> Proxy Handling -> Prefer Proxies' is checked.\n"
            "• Final Color / Finishing: When back on your studio workstation, select '🎥 Camera Originals Only', sync the RAW masters, and set 'Playback -> Proxy Handling -> Disable Proxies'."
        )
        ctk.CTkLabel(card1, text=g1, font=ctk.CTkFont(size=12), text_color="#d1d5db", justify="left", wraplength=850).pack(anchor="w", padx=16, pady=(0, 12))

        card2 = ctk.CTkFrame(scroll, fg_color="#18191f", corner_radius=10, border_color="#2b2d38", border_width=1)
        card2.pack(fill="x", pady=(0, 10), padx=4)

        ctk.CTkLabel(card2, text="🗺️ 2. Cross-Platform Mapped Mounts", font=ctk.CTkFont(size=14, weight="bold"), text_color="#10b981").pack(anchor="w", padx=16, pady=(12, 4))
        g2 = (
            "To share projects between Windows and macOS without 'Media Offline' red badges:\n"
            "• macOS: Remote Mount = D:\\  <-->  Local Mount = /Users/<name>/Movies/DaVinci Resolve/D/\n"
            "• Windows: Remote Mount = /Users/  <-->  Local Mount = D:\\DAVINCI\\Users\\\n\n"
            "💡 ResolveSync's '🗺️ Mapped Mounts' assistant can automatically inspect and fix your DaVinci .config.data preference files with 1 click!"
        )
        ctk.CTkLabel(card2, text=g2, font=ctk.CTkFont(size=12), text_color="#d1d5db", justify="left", wraplength=850).pack(anchor="w", padx=16, pady=(0, 12))

    def _focus_about_tab(self):
        self.main_tabview.set("👑 About Žiga (@thekingziga)")

    def _clear_log(self):
        self.log_text.delete("1.0", "end")

    def _toggle_debug_logs(self):
        enabled = self.debug_logs_var.get()
        set_debug_logging(enabled)
        self.config_data["debug_logging"] = enabled
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as fp:
                json.dump(self.config_data, fp, indent=2)
        except Exception:
            pass
        self._log(f"Debug logging {'ENABLED (verbose)' if enabled else 'DISABLED (standard INFO/ERROR only)'}.")

    def _create_metric_card(self, parent, label: str, value: str, color: str):
        card = ctk.CTkFrame(parent, fg_color="#1c1d24", corner_radius=8, width=145, height=75)
        card.pack(side="left", fill="x", expand=True, padx=4)
        card.pack_propagate(False)

        val_lbl = ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=20, weight="bold"), text_color=color)
        val_lbl.pack(pady=(10, 0))

        lbl = ctk.CTkLabel(card, text=label.upper(), font=ctk.CTkFont(size=10, weight="bold"), text_color="#9ca3af")
        lbl.pack(pady=(0, 10))
        return val_lbl

    def _log(self, message: str, level: str = "INFO"):
        if level == "DEBUG" and hasattr(self, "debug_logs_var") and not self.debug_logs_var.get():
            return
        ts = time.strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] {message}\n")
        self.log_text.see("end")

    def _on_source_tab_changed(self, tab_name: str):
        self.db_frame.pack_forget()
        self.live_frame.pack_forget()
        self.drp_frame.pack_forget()

        if "Network Database" in tab_name:
            self.db_frame.pack(fill="x", padx=16, pady=(4, 6), before=self.active_proj_frame)
        elif "Live DaVinci" in tab_name:
            self.live_frame.pack(fill="x", padx=16, pady=(4, 6), before=self.active_proj_frame)
        elif "DRP Archive" in tab_name:
            self.drp_frame.pack(fill="x", padx=16, pady=(4, 6), before=self.active_proj_frame)

    def _update_active_project_display(self):
        name = self.active_project_name or (os.path.basename(self.current_drp_path) if self.current_drp_path else "")
        src = self.active_project_source or ""
        count = len(self.live_project_media) if self.live_project_media is not None else len(self.media_items)

        if name:
            display_title = f"{name} ({src})" if src else name
            self.active_proj_lbl.configure(text=display_title, text_color="#34d399")
            if count > 0:
                self.active_proj_stats_lbl.configure(text=f"{count} media clips loaded • Ready to sync", text_color="#10b981")
            else:
                self.active_proj_stats_lbl.configure(text="Analyzing project...", text_color="#9ca3af")
        else:
            self.active_proj_lbl.configure(text="None selected", text_color="#9ca3af")
            self.active_proj_stats_lbl.configure(text="Select a project above to analyze and sync", text_color="#9ca3af")

    def _on_media_filter_changed(self, value=None):
        filt = self._get_media_filter()
        self._log(f"Media filter changed to: {self.media_filter_var.get()} ({filt})")
        if self.live_project_media or self.current_drp_path:
            self._trigger_analysis()

    def _get_media_filter(self) -> str:
        val = self.media_filter_var.get()
        if "Proxies Only" in val:
            return "proxies_only"
        elif "Originals" in val:
            return "originals_only"
        return "all"

    def _launch_davinci_app(self):
        self._log("Launching DaVinci Resolve application...")
        ok, msg = launch_davinci_resolve(self.current_drp_path)
        if ok:
            self._log(f"✓ {msg}")
        else:
            self._log(f"⚠️ {msg}")
            messagebox.showwarning("DaVinci Launch", msg, parent=self)

    def _open_tips_dialog(self):
        DaVinciTipsDialog(self)

    def _open_settings(self):
        SettingsDialog(self, self.config_data, self._on_settings_saved)

    def _on_settings_saved(self, updated_cfg: dict):
        self.config_data = updated_cfg
        self._log("Configuration updated successfully.")
        self._populate_postgres_projects()
        if self.live_project_media or self.current_drp_path:
            self._trigger_analysis()

    def _populate_postgres_projects(self):
        def worker():
            reader = DaVinciPostgresReader.from_config(self.config_data)
            # If not configured, check for .resolvedbkey in common user folders
            if not reader:
                search_dirs = [
                    os.getcwd(),
                    os.path.expanduser("~/Downloads"),
                    os.path.expanduser("~/Desktop"),
                    os.path.expanduser("~"),
                ]
                for sdir in search_dirs:
                    if not os.path.exists(sdir):
                        continue
                    try:
                        for fname in os.listdir(sdir):
                            if fname.endswith(".resolvedbkey"):
                                fpath = os.path.join(sdir, fname)
                                try:
                                    parsed = DaVinciPostgresReader.parse_resolvedbkey(fpath)
                                    self.config_data["postgres"] = {
                                        "enabled": True,
                                        "host": parsed["host"],
                                        "port": parsed["port"],
                                        "dbname": parsed["dbname"],
                                        "user": parsed["user"],
                                        "password": parsed["password"],
                                    }
                                    with open(CONFIG_FILE, "w", encoding="utf-8") as fp:
                                        json.dump(self.config_data, fp, indent=2)
                                    reader = DaVinciPostgresReader.from_config(self.config_data)
                                    self.after(0, lambda fn=fname: self._log(f"Auto-discovered and loaded database key: {fn}"))
                                    break
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    if reader:
                        break

            if not reader:
                self.after(0, lambda: self.db_project_combo.configure(values=["No database configured"]))
                self.after(0, lambda: self.db_status_lbl.configure(text="⚪ Click 'Import .resolvedbkey' to connect", text_color="#9ca3af"))
                return

            projects = reader.list_projects()
            self.db_projects_cache = projects

            if projects:
                names = [p["name"] for p in projects]
                self.after(0, lambda: self.db_project_combo.configure(values=names))
                self.after(0, lambda: self.db_project_combo.set(names[0]))
                status_txt = f"🟢 Connected ({len(projects)} projects)"
                self.after(0, lambda: self.db_status_lbl.configure(text=status_txt, text_color="#10b981"))
                self.after(0, lambda: self._log(f"Connected to PostgreSQL database '{reader.dbname}' ({len(projects)} projects found)."))
            else:
                ok, err = reader.test_connection()
                if ok:
                    self.after(0, lambda: self.db_project_combo.configure(values=["0 projects found in DB"]))
                    self.after(0, lambda: self.db_status_lbl.configure(text=f"🟢 Connected to {reader.dbname} (empty)", text_color="#10b981"))
                else:
                    self.after(0, lambda: self.db_project_combo.configure(values=["Connection failed"]))
                    self.after(0, lambda: self.db_status_lbl.configure(text="❌ Connection failed (check Settings)", text_color="#ef4444"))
                    self.after(0, lambda: self._log(f"PostgreSQL connection failed: {err}"))

        threading.Thread(target=worker, daemon=True).start()

    def _load_postgres_selected(self):
        val = self.db_project_combo.get().strip()
        if not val or val in ["Connecting to PostgreSQL...", "No database configured", "Connection failed", "0 projects found in DB"]:
            messagebox.showinfo("Project Selection", "Please select a valid PostgreSQL project from the dropdown or click 'Import .resolvedbkey'.")
            return

        self._log(f"Querying PostgreSQL project server for project '{val}'...")

        def worker():
            reader = DaVinciPostgresReader.from_config(self.config_data)
            if not reader:
                self.after(0, lambda: messagebox.showerror("Database Error", "PostgreSQL database is not configured. Please import a .resolvedbkey file or check Settings."))
                return

            media_paths = reader.get_project_media(val)
            count = len(media_paths)
            self.live_project_media = media_paths
            self.active_project_name = val
            self.active_project_source = "PostgreSQL DB"
            self.current_drp_path = None

            self.after(0, self._update_active_project_display)
            self.after(0, lambda: self._log(f"✓ Retrieved {count} media clips for project '{val}' directly from PostgreSQL database."))
            self.after(0, self._trigger_analysis)

        threading.Thread(target=worker, daemon=True).start()

    def _import_db_key_from_main(self):
        fpath = filedialog.askopenfilename(
            title="Select DaVinci Resolve Project Library Key (.resolvedbkey)",
            filetypes=[("Resolve DB Key", "*.resolvedbkey"), ("XML Files", "*.xml"), ("All Files", "*.*")]
        )
        if fpath:
            try:
                parsed = DaVinciPostgresReader.parse_resolvedbkey(fpath)
                curr_pg = self.config_data.get("postgres", {})
                curr_pg.update({
                    "enabled": True,
                    "host": parsed["host"],
                    "port": parsed["port"],
                    "dbname": parsed["dbname"],
                    "user": parsed["user"],
                    "password": parsed["password"],
                })
                self.config_data["postgres"] = curr_pg
                with open(CONFIG_FILE, "w", encoding="utf-8") as fp:
                    json.dump(self.config_data, fp, indent=2)

                self._log(f"✓ Successfully imported database key: {os.path.basename(fpath)}")
                self._populate_postgres_projects()
            except Exception as ex:
                self._log(f"❌ Failed to parse .resolvedbkey: {ex}")
                messagebox.showerror("Key Import Error", f"Failed to parse database key file: {ex}")

    def _on_source_changed(self, selected_mode: str):
        if not hasattr(self, "panel_live") or not hasattr(self, "panel_recent") or not hasattr(self, "panel_drp"):
            return
        self.panel_live.pack_forget()
        self.panel_recent.pack_forget()
        self.panel_drp.pack_forget()

        if "Live" in selected_mode:
            self.panel_live.pack(fill="x")
            self._connect_live_resolve()
        elif "Recent" in selected_mode:
            self.panel_recent.pack(fill="x")
            self._populate_recent_projects()
        else:
            self.panel_drp.pack(fill="x")

    def _auto_check_live_resolve(self):
        """Silently checks if DaVinci Resolve is running on startup."""
        def check():
            info = DaVinciProjectDiscoverer.get_live_project()
            status = info.get("status")
            if status == "active":
                pname = info.get("project_name", "Open Project")
                count = info.get("clip_count", 0)
                msg = f"🟢 Connected to live project '{pname}' ({count} clips in Media Pool)"
                self.after(0, lambda: self.live_status_lbl.configure(text=msg, text_color="#10b981"))
                self.live_project_media = info.get("media_paths", [])
                self.active_project_name = pname
                self.current_drp_path = None
                self.after(0, lambda: self._log(f"Auto-connected to active DaVinci Resolve project: '{pname}' ({count} clips)"))
                self.after(0, self._trigger_analysis)
            elif status == "no_project_open":
                msg = "🟡 DaVinci Resolve is running, but no project is open."
                self.after(0, lambda: self.live_status_lbl.configure(text=msg, text_color="#f59e0b"))
            else:
                msg = "⚪ DaVinci Resolve not running (Click 'Connect' once open, or pick Recent / DRP)"
                self.after(0, lambda: self.live_status_lbl.configure(text=msg, text_color="#9ca3af"))

        threading.Thread(target=check, daemon=True).start()

    def _connect_live_resolve(self):
        self.live_status_lbl.configure(text="Connecting to DaVinci Resolve...", text_color="#9ca3af")
        self._log("Connecting to DaVinci Resolve live instance...")

        def worker():
            info = DaVinciProjectDiscoverer.get_live_project()
            status = info.get("status")

            if status == "active":
                pname = info.get("project_name")
                media_paths = info.get("media_paths", [])
                count = len(media_paths)
                msg = f"🟢 Connected: '{pname}' ({count} clips found in Media Pool)"
                self.after(0, lambda: self.live_status_lbl.configure(text=msg, text_color="#10b981"))
                self.after(0, lambda: self._log(f"✓ Successfully extracted {count} clips from active project '{pname}'."))
                self.live_project_media = media_paths
                self.active_project_name = pname
                self.active_project_source = "Live DaVinci Resolve"
                self.current_drp_path = None
                self.after(0, self._update_active_project_display)
                self.after(0, self._trigger_analysis)
            elif status == "scripting_disabled":
                msg = "⚠️ Scripting disabled in DaVinci Preferences"
                self.after(0, lambda: self.live_status_lbl.configure(text=msg, text_color="#f59e0b"))
                self.after(0, lambda: self._log("⚠️ " + info.get("message", "")))
                self.after(0, lambda: messagebox.showwarning("DaVinci Scripting Disabled", info.get("message")))
            elif status == "no_project_open":
                msg = "🟡 DaVinci Resolve is open, but no project is currently loaded."
                self.after(0, lambda: self.live_status_lbl.configure(text=msg, text_color="#f59e0b"))
                self.after(0, lambda: self._log("DaVinci Resolve is open, but no project is open. Please open your project in DaVinci."))
            elif status == "not_running":
                msg = "❌ DaVinci Resolve is not running. Please launch DaVinci Resolve."
                self.after(0, lambda: self.live_status_lbl.configure(text=msg, text_color="#ef4444"))
                self.after(0, lambda: self._log("DaVinci Resolve is not running. Launch Resolve or select a Recent Project / DRP."))
            else:
                msg = f"⚠️ {info.get('message', 'Could not connect to DaVinci Resolve.')}"
                self.after(0, lambda: self.live_status_lbl.configure(text=msg, text_color="#f59e0b"))
                self.after(0, lambda: self._log(msg))

        threading.Thread(target=worker, daemon=True).start()

    def _populate_recent_projects(self):
        def worker():
            projects = DaVinciProjectDiscoverer.get_recent_projects()
            if not projects:
                self.after(0, lambda: self.recent_combo.configure(values=["No recent projects found"]))
                return

            displays = [p["display"] for p in projects]
            self.recent_projects_cache = projects
            self.after(0, lambda: self.recent_combo.configure(values=displays))
            self.after(0, lambda: self.recent_combo.set(displays[0]))

        threading.Thread(target=worker, daemon=True).start()

    def _load_recent_selected(self):
        val = self.recent_combo.get()
        if not val or val == "No recent projects found":
            return

        self._log(f"Selected recent project: {val}")

        def worker():
            pname = val.split(" (")[0].strip()
            # If network / postgres project, load directly without needing DaVinci open
            reader = DaVinciPostgresReader.from_config(self.config_data)
            is_net = "NETWORK:" in val.upper() or "POSTGRESQL:" in val.upper() or any(p.get("name") == pname for p in getattr(self, "db_projects_cache", []))
            if reader and is_net:
                self.after(0, lambda: self._log(f"Extracting clips for '{pname}' directly from PostgreSQL database..."))
                media_paths = reader.get_project_media(pname)
                if media_paths:
                    self.live_project_media = media_paths
                    self.active_project_name = pname
                    self.active_project_source = "PostgreSQL DB"
                    self.current_drp_path = None
                    self.after(0, self._update_active_project_display)
                    self.after(0, lambda: self._log(f"✓ Extracted {len(media_paths)} clips for '{pname}' directly from PostgreSQL."))
                    self.after(0, self._trigger_analysis)
                    return

            info = DaVinciProjectDiscoverer.get_live_project()
            if info.get("status") == "active":
                self._connect_live_resolve()
            else:
                self.after(0, lambda: self._log(f"To sync '{pname}' live, please open it in DaVinci Resolve then click 'Connect Live Resolve'."))
                self.after(0, lambda: messagebox.showinfo(
                    "Open in DaVinci Resolve",
                    f"Please launch DaVinci Resolve and open project '{pname}'.\n\n"
                    "Once opened, ResolveSync will auto-detect all clips live!"
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _browse_drp(self):
        path = choose_drp_file(self)
        if path:
            self.drp_path_entry.delete(0, "end")
            self.drp_path_entry.insert(0, path)
            self.current_drp_path = path
            self.live_project_media = None
            self.active_project_name = os.path.basename(path)
            self._scan_drp_project()

    def _scan_drp_project(self):
        drp_path = self.drp_path_entry.get().strip()
        if not drp_path or not os.path.exists(drp_path):
            messagebox.showerror("File Error", "Please select a valid .drp project file.")
            return

        self.current_drp_path = drp_path
        self.live_project_media = None
        self.active_project_name = os.path.basename(drp_path)
        self.active_project_source = "DRP Archive"
        self._update_active_project_display()
        self._trigger_analysis()

    def _browse_dest_folder(self):
        folder = choose_destination_folder("Select Local Folder to Store Downloaded Media", self)
        if folder:
            norm_f = os.path.normpath(folder)
            self.dest_folder_entry.delete(0, "end")
            self.dest_folder_entry.insert(0, norm_f)
            self.config_data["sync_root_folder"] = norm_f
            try:
                with open(CONFIG_FILE, "w", encoding="utf-8") as fp:
                    json.dump(self.config_data, fp, indent=2)
            except Exception:
                pass
            if self.live_project_media or self.current_drp_path:
                self._trigger_analysis()

    def _trigger_analysis(self):
        sync_root = self.dest_folder_entry.get().strip() or None
        proj_label = self.active_project_name or (os.path.basename(self.current_drp_path) if self.current_drp_path else "Project")
        self._log(f"Analyzing media availability across workstation and TrueNAS for '{proj_label}'...")

        def worker():
            try:
                sync_app = ResolveSyncApp(config_path=CONFIG_FILE)
                media_filt = self._get_media_filter()
                if self.live_project_media is not None:
                    items = sync_app.analyze_inventory(file_paths=self.live_project_media, check_remote=True, sync_root=sync_root, media_filter=media_filt)
                elif self.current_drp_path:
                    items = sync_app.analyze_inventory(drp_path=self.current_drp_path, check_remote=True, sync_root=sync_root, media_filter=media_filt)
                else:
                    return

                self.media_items = items

                total = len(items)
                synced = len([i for i in items if i.status == "SYNCED"])
                download = len([i for i in items if i.status == "NEEDS_DOWNLOAD"])
                upload = len([i for i in items if i.status == "NEEDS_UPLOAD"])
                missing = len([i for i in items if i.status == "MISSING_EVERYWHERE"])
                unmapped = [i for i in items if i.status == "UNMAPPED"]
                unmapped_count = len(unmapped)

                proxies = [i for i in items if i.is_proxy]
                originals = [i for i in items if not i.is_proxy]
                proxy_count = len(proxies)
                orig_count = len(originals)
                proxy_bytes = sum(i.file_size_local or i.file_size_remote for i in proxies)
                orig_bytes = sum(i.file_size_local or i.file_size_remote for i in originals)

                summary_txt = f"📊 {total} Clips: {orig_count} Originals ({format_bytes(orig_bytes)}) • {proxy_count} Proxies ({format_bytes(proxy_bytes)}) • {synced} In Sync"
                self.after(0, lambda: self.media_summary_lbl.configure(text=summary_txt))
                self.after(0, self._update_active_project_display)

                self.after(0, lambda: self._update_metrics(total, synced, download, upload, missing, unmapped_count))
                self.after(0, lambda: self._log(f"Analysis complete: {total} items ({synced} synced, {download} to download, {upload} to upload). Filter: {self.media_filter_var.get()}"))

                if unmapped_count == 0 and total > 0:
                    self.after(0, lambda: self._log(f"✓ All {total} clips auto-mapped across disks. Ready to sync without rules!"))
                elif unmapped_count > 0:
                    self.after(0, lambda: self._log(f"⚠️ [WARNING] {unmapped_count} media file(s) are UNMAPPED! Check Settings."))

                # Detect cross-platform media origins & check DaVinci Preferences
                folder = sync_root or self.config_data.get("sync_root_folder") or get_default_download_dir()
                recs = calculate_mapped_mounts([i.drp_path for i in items], folder, IS_WIN)
                needed_fix = None
                for r in recs:
                    st = self.pref_manager.check_mount_status(r["remote"], r["local"])
                    if st.get("needs_fix"):
                        needed_fix = (r, st)
                        break

                if needed_fix:
                    r, st = needed_fix
                    self.after(0, lambda r=r, st=st: self._show_mount_alert(r, st))
                    self.after(0, lambda: self._log(f"⚠️ DaVinci Mapped Mount needed for '{r['remote']}' ({st['badge']}). Click '1-Click Auto-Fix' above!"))
                else:
                    self.after(0, self._hide_mount_alert)
                    if recs:
                        self.after(0, lambda: self._log("✓ DaVinci Mapped Mounts verified active. Clips will link automatically in Resolve!"))

            except Exception as e:
                self.after(0, lambda: self._log(f"Analysis error: {e}"))
                self.after(0, lambda: messagebox.showerror("Analysis Error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _open_mapped_mounts_helper(self):
        folder = self.dest_folder_entry.get().strip() or self.config_data.get("sync_root_folder") or get_default_download_dir()
        paths = self.live_project_media or [item.drp_path for item in self.media_items]
        pname = self.active_project_name or (os.path.basename(self.current_drp_path) if self.current_drp_path else "")
        MappedMountsHelperDialog(self, folder, paths, pname)

    def _show_mount_alert(self, rec: dict, status: dict):
        self.mount_alert_banner.pack(fill="x", pady=(0, 10), padx=2, before=self.metrics_frame)
        if status.get("status") == "slash_mismatch":
            msg = f"⚠️ DaVinci Mapped Mount Trailing Slash Bug: Clips from '{rec['remote']}' will appear offline in DaVinci Resolve!"
            btn_txt = "⚡ 1-Click Fix Mount"
            self.mount_alert_banner.configure(fg_color="#381d06", border_color="#f59e0b")
            self.mount_alert_fix_btn.configure(text=btn_txt, fg_color="#d97706", hover_color="#b45309")
        else:
            msg = f"⚠️ DaVinci Mapped Mount Missing: Clips from '{rec['remote']}' will appear offline in DaVinci Resolve!"
            btn_txt = "⚡ 1-Click Auto-Add"
            self.mount_alert_banner.configure(fg_color="#3b1115", border_color="#ef4444")
            self.mount_alert_fix_btn.configure(text=btn_txt, fg_color="#2563eb", hover_color="#1d4ed8")

        self.mount_alert_lbl.configure(text=msg)
        self.mount_alert_fix_btn.configure(command=lambda: self._quick_fix_mount(rec["remote"], rec["local"]))

    def _hide_mount_alert(self):
        self.mount_alert_banner.pack_forget()

    def _quick_fix_mount(self, remote: str, local: str):
        ok, msg = self.pref_manager.add_or_update_mount(remote, local)
        if ok:
            messagebox.showinfo("DaVinci Preferences Configured", msg, parent=self)
            self._log(f"✓ DaVinci Preferences updated: {remote} -> {local}")
            self.mount_alert_banner.configure(fg_color="#062e1c", border_color="#10b981")
            self.mount_alert_lbl.configure(text=f"🟢 DaVinci Mapped Mount active: {remote} -> {local}")
            self.mount_alert_fix_btn.pack_forget()
        else:
            messagebox.showerror("Error Updating Preferences", msg, parent=self)

    def _check_and_prompt_missing_mounts(self):
        paths = self.live_project_media or [item.drp_path for item in self.media_items]
        folder = self.dest_folder_entry.get().strip() or get_default_download_dir()
        recs = calculate_mapped_mounts(paths, folder, IS_WIN)
        for r in recs:
            st = self.pref_manager.check_mount_status(r["remote"], r["local"])
            if st.get("needs_fix"):
                ans = messagebox.askyesno(
                    "Auto-Configure DaVinci Mapped Mount?",
                    f"ResolveSync downloaded media from '{r['remote']}'.\n\n"
                    f"DaVinci Resolve needs a Mapped Mount so clips link up automatically in your project without manual relinking.\n\n"
                    f"• Remote Mount (DaVinci): {r['remote']}\n"
                    f"• Local Mount (Your Disk): {r['local']}\n"
                    f"• Issue: {st['badge']}\n\n"
                    f"Would you like ResolveSync to auto-configure DaVinci Resolve's preferences now?",
                    parent=self
                )
                if ans:
                    ok, msg = self.pref_manager.add_or_update_mount(r["remote"], r["local"])
                    if ok:
                        messagebox.showinfo("DaVinci Preferences Configured", msg, parent=self)
                        self._log(f"✓ DaVinci Preferences auto-configured: {r['remote']} -> {r['local']}")
                        self._hide_mount_alert()
                    else:
                        messagebox.showerror("Configuration Error", msg, parent=self)
                break

    def _update_metrics(self, total, synced, download, upload, missing, unmapped=0):
        self.card_total.configure(text=str(total))
        self.card_synced.configure(text=str(synced))
        self.card_down.configure(text=str(download))
        self.card_up.configure(text=str(upload))
        self.card_miss.configure(text=str(missing))
        if unmapped == 0 and total > 0:
            self.card_unmapped.configure(text=f"{total} ✓", text_color="#10b981")
        elif unmapped > 0:
            self.card_unmapped.configure(text=str(unmapped), text_color="#f59e0b")
        else:
            self.card_unmapped.configure(text="0", text_color="#9ca3af")

    def _start_sync_thread(self):
        if self.is_syncing:
            return

        if not self.live_project_media and not self.current_drp_path:
            messagebox.showerror("No Project", "Please select a PostgreSQL project or browse a .drp file first.")
            return

        # Prompt on first-time sync to confirm or customize the media download destination
        if not self.config_data.get("sync_destination_confirmed"):
            cur_f = self.dest_folder_entry.get().strip() or self.config_data.get("sync_root_folder") or get_default_download_dir()

            def on_confirmed(chosen_folder: str, remember: bool):
                norm_f = os.path.normpath(chosen_folder)
                self.dest_folder_entry.delete(0, "end")
                self.dest_folder_entry.insert(0, norm_f)
                self.config_data["sync_root_folder"] = norm_f
                if remember:
                    self.config_data["sync_destination_confirmed"] = True
                try:
                    with open(CONFIG_FILE, "w", encoding="utf-8") as fp:
                        json.dump(self.config_data, fp, indent=2)
                except Exception:
                    pass
                self._prompt_sync_scope_then_start()

            FirstTimeSyncDialog(self, cur_f, on_confirmed)
            return

        self._prompt_sync_scope_then_start()

    def _prompt_sync_scope_then_start(self):
        prompt_scope = self.config_data.get("sync_options", {}).get("confirm_sync_scope", True)
        if not prompt_scope or not self.media_items:
            self._actually_start_sync(selected_items=None)
            return

        selected_mode = self.mode_var.get()
        mode_map = {
            "🔄 Two-Way Sync": "sync",
            "⬇️ Pull from NAS": "download",
            "⬆️ Push to NAS": "upload",
            "🔍 Dry Run": "dry_run",
        }
        mode = mode_map.get(selected_mode, "sync")

        items_to_action = [
            it for it in self.media_items
            if (mode in ("download", "sync") and it.status in ("NEEDS_DOWNLOAD", "SIZE_MISMATCH"))
            or (mode in ("upload", "sync") and it.status in ("NEEDS_UPLOAD", "SIZE_MISMATCH"))
        ]
        count = len(items_to_action) if items_to_action else len(self.media_items)
        total_bytes = sum(i.file_size_remote or i.file_size_local or 0 for i in (items_to_action or self.media_items))
        p_name = self.active_project_name or (os.path.basename(self.current_drp_path) if self.current_drp_path else "")

        def on_scope_choice(choice: str, remember: bool):
            if remember:
                if "sync_options" not in self.config_data:
                    self.config_data["sync_options"] = {}
                self.config_data["sync_options"]["confirm_sync_scope"] = False
                try:
                    with open(CONFIG_FILE, "w", encoding="utf-8") as fp:
                        json.dump(self.config_data, fp, indent=2)
                except Exception:
                    pass
            if choice == "all":
                self._actually_start_sync(selected_items=None)
            elif choice == "select":
                self._open_selective_sync_dialog()

        SyncScopeDialog(self, p_name, mode, count, total_bytes, on_scope_choice)

    def _open_selective_sync_dialog(self):
        if not self.media_items:
            messagebox.showinfo("No Files", "No project media items currently loaded. Please select a project or .drp file first.")
            return

        selected_mode = self.mode_var.get()
        mode_map = {
            "🔄 Two-Way Sync": "sync",
            "⬇️ Pull from NAS": "download",
            "⬆️ Push to NAS": "upload",
            "🔍 Dry Run": "dry_run",
        }
        mode = mode_map.get(selected_mode, "sync")

        def on_selected_confirmed(chosen_paths: List[str]):
            if not chosen_paths:
                return
            self._log(f"📋 Selective Sync: User selected {len(chosen_paths)} file(s) for {mode.upper()}.")
            self._actually_start_sync(selected_items=chosen_paths)

        FileSelectionModalDialog(self, self.media_items, mode, on_selected_confirmed)

    def _actually_start_sync(self, selected_items: Optional[List[str]] = None):
        selected_mode = self.mode_var.get()
        mode_map = {
            "🔄 Two-Way Sync": "sync",
            "⬇️ Pull from NAS": "download",
            "⬆️ Push to NAS": "upload",
            "🔍 Dry Run": "dry_run",
        }
        mode = mode_map.get(selected_mode, "sync")
        is_dry_run = (mode == "dry_run")
        if is_dry_run:
            mode = "sync"

        self.is_syncing = True
        self.stop_requested = False
        self.btn_start_sync.configure(state="disabled")
        if hasattr(self, "btn_select_files"):
            self.btn_select_files.configure(state="disabled")
        self.btn_stop_sync.configure(state="normal")
        self.progress_bar.set(0)

        threading.Thread(
            target=self._run_sync,
            args=(mode, is_dry_run, selected_items),
            daemon=True,
        ).start()

    def _apply_progress_update(self, pct: float, status_text: str, stats_text: str):
        if not self.is_syncing:
            return
        self.progress_bar.set(pct)
        self.progress_lbl.configure(text=status_text)
        self.progress_stats.configure(text=stats_text)

    def _run_sync(self, mode: str, dry_run: bool, selected_items: Optional[List[str]] = None):
        sync_root = self.dest_folder_entry.get().strip() or None
        scope_tag = f" ({len(selected_items)} selected files)" if selected_items else ""
        self._log(f"Starting {mode.upper()} synchronization{scope_tag} (Dry run: {dry_run})...")
        last_time = time.time()
        last_bytes = 0
        last_ui_time = 0

        def progress_cb(transferred: int, total: int, direction: str, filename: str):
            nonlocal last_time, last_bytes, last_ui_time
            now = time.time()

            # High-performance throttle: rate-limit UI updates to ~12.5 FPS (every 80ms)
            # This completely eliminates event loop congestion and GUI freezing during 100MB/s+ file transfers
            if transferred < total and (now - last_ui_time) < 0.08:
                return
            last_ui_time = now

            dt = now - last_time
            speed_str = ""
            if dt >= 0.5:
                speed = (transferred - last_bytes) / dt
                speed_str = f" @ {format_bytes(int(speed))}/s"
                last_time = now
                last_bytes = transferred

            pct = (transferred / total) if total > 0 else 0
            status_text = f"[{direction.upper()}] {filename} ({int(pct * 100)}%)"
            stats_text = f"{format_bytes(transferred)} / {format_bytes(total)}{speed_str}"
            self.after(0, lambda: self._apply_progress_update(pct, status_text, stats_text))

        try:
            sync_app = ResolveSyncApp(config_path=CONFIG_FILE)
            media_filt = self._get_media_filter()
            code = sync_app.run(
                drp_path=self.current_drp_path,
                file_paths=self.live_project_media,
                mode=mode,
                dry_run=dry_run,
                progress_callback=progress_cb,
                log_callback=lambda msg: self.after(0, lambda: self._log(msg)),
                sync_root=sync_root,
                media_filter=media_filt,
                selected_items=selected_items,
                is_cancelled=lambda: self.stop_requested,
            )

            if self.stop_requested or code == 130:
                self.after(0, lambda: self._log("⏹️ Synchronization cancelled by user."))
                self.after(0, lambda: self.progress_lbl.configure(text="Synchronization cancelled."))
            elif code == 0:
                self.after(0, lambda: self.progress_bar.set(1.0))
                self.after(0, lambda: self._log("Synchronization completed successfully!"))
                self.after(0, lambda: self.progress_lbl.configure(text="Sync completed successfully!"))
                if mode in ["sync", "download"] and not dry_run:
                    self.after(0, lambda: self._log("💡 Clips downloaded! Checking DaVinci Resolve Mapped Mounts..."))
                    self.after(600, self._check_and_prompt_missing_mounts)

                    # Post-Sync DaVinci Launch Prompt
                    pname = self.active_project_name or (os.path.basename(self.current_drp_path) if self.current_drp_path else "")
                    prompt_opt = self.config_data.get("sync_options", {}).get("prompt_launch_davinci", True)
                    if prompt_opt:
                        self.after(1200, lambda pname=pname: PostSyncLaunchDialog(self, pname, len(self.media_items), self._launch_davinci_app))
            else:
                self.after(0, lambda: self._log(f"Sync finished with warnings (Exit code: {code})."))
                self.after(0, lambda: self.progress_lbl.configure(text=f"Sync finished with warnings (code {code})"))

            # Refresh media analysis after sync
            self.after(0, self._trigger_analysis)

        except SyncCancelledError:
            self.after(0, lambda: self._log("⏹️ Synchronization cancelled immediately by user."))
            self.after(0, lambda: self.progress_lbl.configure(text="Sync cancelled."))
            self.after(0, self._trigger_analysis)
        except Exception as e:
            self.after(0, lambda: self._log(f"Sync error: {e}"))
            self.after(0, lambda: messagebox.showerror("Sync Failure", str(e)))
        finally:
            self.is_syncing = False
            self.after(0, lambda: self.btn_start_sync.configure(state="normal"))
            if hasattr(self, "btn_select_files"):
                self.after(0, lambda: self.btn_select_files.configure(state="normal"))
            self.after(0, lambda: self.btn_stop_sync.configure(state="disabled", text="⏹️ Cancel"))

    def _cancel_sync(self):
        if self.is_syncing:
            self.stop_requested = True
            self.btn_stop_sync.configure(state="disabled", text="Stopping...")
            self.progress_lbl.configure(text="Cancelling synchronization immediately...")
            self._log("⏹️ Cancel requested by user! Halting all transfers...")


def main():
    app = ResolveSyncAppGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
