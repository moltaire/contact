#!/usr/bin/env python3
"""
sort_screenshots.py
───────────────────
Scans an inbox folder for images, asks a local vision model (via Ollama) to
describe each one, renames it to YYYY-MM-DD_brief-description.ext, and moves
it to an archive folder.

Starts Ollama if it isn't already running, and stops it again when done
(unless it was already running before the script started).

Usage:
    python3 sort_screenshots.py --incoming /path/to/inbox --archive /path/to/archive
    python3 sort_screenshots.py --incoming /path/to/inbox --archive /path/to/archive --model llava:7b
"""

import argparse
import base64
import json
import re
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
OLLAMA_BASE = "http://localhost:11434"


# ── Ollama helpers ────────────────────────────────────────────────────────────

def ollama_ready() -> bool:
    try:
        urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=2)
        return True
    except Exception:
        return False


def wait_for_ollama(timeout: int = 30) -> bool:
    for _ in range(timeout):
        if ollama_ready():
            return True
        time.sleep(1)
    return False


def describe_image(path: Path, model: str) -> str:
    """Ask the vision model for a short slug description of the image."""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    payload = json.dumps({
        "model": model,
        "prompt": (
            "Give a filename tag for this screenshot. "
            "Reply with 3 to 5 lowercase words joined by hyphens, nothing else. "
            "No punctuation, no spaces, no sentence. "
            "Focus on the main subject. "
            "Examples: bayesian-model-diagram  concert-listing-berlin  dictator-game-stimulus"
        ),
        "images": [b64],
        "stream": False,
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        raw = json.loads(resp.read())["response"].strip()

    # Sanitise to a clean slug
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug[:60] or "screenshot"


# ── Filename helpers ──────────────────────────────────────────────────────────

def extract_date(path: Path) -> str:
    """
    Pull YYYY-MM-DD from a macOS screenshot filename if present,
    otherwise fall back to the file's modification time.

    Handles:
      Screenshot 2026-02-26 at 10.19.30.png   (modern macOS)
      Screenshot 2013-11-04 11.24.07.png       (older macOS)
      SCR-20220213-x0u.png                     (iPhone/iPad)
    """
    name = path.name
    m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
    if m:
        return m.group(1)
    m = re.search(r"SCR-(\d{4})(\d{2})(\d{2})", name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")


def unique_dest(archive: Path, stem: str, suffix: str) -> Path:
    """Return a destination path that doesn't collide with existing files."""
    dest = archive / f"{stem}{suffix}"
    n = 1
    while dest.exists():
        dest = archive / f"{stem}_{n}{suffix}"
        n += 1
    return dest


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Rename and archive screenshots using a local vision model."
    )
    parser.add_argument(
        "--incoming", required=True, metavar="DIR",
        help="Folder where new screenshots land (inbox).",
    )
    parser.add_argument(
        "--archive", required=True, metavar="DIR",
        help="Folder where renamed screenshots are stored.",
    )
    parser.add_argument(
        "--model", default="moondream", metavar="MODEL",
        help="Ollama vision model to use (default: moondream).",
    )
    args = parser.parse_args()

    incoming = Path(args.incoming).expanduser().resolve()
    archive  = Path(args.archive).expanduser().resolve()

    archive.mkdir(parents=True, exist_ok=True)
    incoming.mkdir(parents=True, exist_ok=True)

    images = sorted(
        f for f in incoming.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS
    )

    if not images:
        print("Nothing to process.")
        return

    # Start Ollama only if it isn't already running
    already_running = ollama_ready()
    ollama_proc = None
    if not already_running:
        print("Starting Ollama…")
        ollama_proc = subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not wait_for_ollama():
            print("Error: Ollama failed to start.")
            ollama_proc.terminate()
            return

    try:
        print(f"Processing {len(images)} image(s) with {args.model}…\n")
        for img in images:
            print(f"  {img.name}")
            try:
                date = extract_date(img)
                slug = describe_image(img, args.model)
                dest = unique_dest(archive, f"{date}_{slug}", img.suffix.lower())
                img.rename(dest)
                print(f"  → {dest.name}\n")
            except Exception as e:
                print(f"  ✗ error: {e}\n")
    finally:
        if ollama_proc:
            print("Stopping Ollama…")
            ollama_proc.terminate()
            ollama_proc.wait()


if __name__ == "__main__":
    main()
