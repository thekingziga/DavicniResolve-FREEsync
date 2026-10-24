#!/usr/bin/env python3
"""
ResolveSync Windows Executable Builder
======================================
Packages windows_app.py into a standalone portable ResolveSync.exe
using PyInstaller.
"""

import os
import subprocess
import sys


def build_exe():
    print("=" * 60)
    print("  Building ResolveSync Standalone Windows Executable (.exe)")
    print("=" * 60)

    # 1. Check / Install PyInstaller
    try:
        import PyInstaller
        print(f"[+] PyInstaller {PyInstaller.__version__} is installed.")
    except ImportError:
        print("[!] PyInstaller not found. Installing via pip...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 2. Run PyInstaller
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",            # Standalone single-file executable
        "--windowed",           # GUI mode without black console window
        "--name", "ResolveSync",
        "--add-data", "config.example.json;.",
        "--collect-all", "customtkinter",
        "windows_app.py",
    ]

    print("\n[+] Running build command:")
    print("    " + " ".join(cmd))
    print("\nThis may take 1-2 minutes...")

    ret = subprocess.call(cmd)
    if ret == 0:
        exe_path = os.path.abspath("dist/ResolveSync.exe")
        print("\n" + "=" * 60)
        print("  BUILD SUCCESSFUL!")
        print(f"  Standalone Executable: {exe_path}")
        print("=" * 60)
    else:
        print(f"\n[!] Build failed with exit code: {ret}")


if __name__ == "__main__":
    build_exe()
