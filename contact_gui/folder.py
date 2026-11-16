"""
contact_gui/folder.py
─────────────────────
The system's folder picker, used to open a roll and to choose the library folder.
"""

import platform
import subprocess
import sys


def pick_folder(prompt: str = "Select folder") -> str:
    """Open the system folder picker. Blocking; returns '' if cancelled."""
    try:
        if platform.system() == "Darwin":
            cmd = ["osascript", "-e", f'POSIX path of (choose folder with prompt "{prompt}")']
        else:
            cmd = [
                sys.executable, "-c",
                "import tkinter; from tkinter import filedialog; "
                "root = tkinter.Tk(); root.withdraw(); "
                "root.wm_attributes('-topmost', True); "
                "print(filedialog.askdirectory(), end=''); root.destroy()",
            ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""
