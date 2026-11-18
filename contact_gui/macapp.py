"""
contact_gui/macapp.py
─────────────────────
`contact-ui --install-app`: a small contact.app (macOS) that starts the app without a
terminal. It is a launcher, not a bundle: it runs the `contact-ui` that is installed
(so reinstalling contact updates it too) and needs no Python of its own.

Opening it:
- starts contact in the background, which opens the browser, or
- if contact is already running, only opens the browser on it.
The launcher itself exits straight away; contact keeps running (tagging goes on with
the browser tab closed) until Quit in Settings. Its output goes to
~/Library/Logs/contact.log.
"""

import plistlib
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

PORT = 8765  # fixed, so a second launch finds the running app
BUNDLE_ID = "io.github.moltaire.contact"

# A login shell gives the app the same PATH as a terminal (Homebrew's ollama, uv's
# tools); apps opened from Finder otherwise get only the system's.
_LAUNCHER = """\
#!/bin/zsh
# contact launcher, written by `contact-ui --install-app`
PORT=${{CONTACT_PORT:-{port}}}
URL="http://127.0.0.1:$PORT/"
if /usr/bin/curl -fs --max-time 1 "$URL" | /usr/bin/grep -q '<title>contact'; then
    /usr/bin/open "$URL"   # already running: just show it
    exit 0
fi
mkdir -p "$HOME/Library/Logs"
/usr/bin/nohup /bin/zsh -lc "exec {command} --port $PORT $CONTACT_ARGS" \\
    >> "$HOME/Library/Logs/contact.log" 2>&1 &
"""


def _icon(path: Path) -> None:
    """The wordmark's orange dot on the camera's matte black, as a macOS icon."""
    from PIL import Image, ImageDraw

    from .theme import BODY, ORANGE

    size = 1024
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    inset = 100  # macOS icons leave a margin around the rounded square
    draw.rounded_rectangle((inset, inset, size - inset, size - inset), radius=185, fill=BODY)
    r = 150
    draw.ellipse((size / 2 - r, size / 2 - r, size / 2 + r, size / 2 + r), fill=ORANGE)
    image.save(path, format="ICNS")


def _contact_ui() -> str:
    """The contact-ui command that is running now, so the app starts the same one."""
    here = Path(sys.argv[0])
    if here.name in {"contact-ui", "contact-gui"} and here.exists():
        return str(here.absolute())
    found = shutil.which("contact-ui")
    if found:
        return found
    raise SystemExit("contact-ui was not found. Install contact first: uv tool install .")


def install_app(folder: Path | None = None) -> Path:
    """Write contact.app into `folder` (default ~/Applications) and return its path."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        app_version = version("contact")
    except PackageNotFoundError:
        app_version = "0"
    folder = (folder or Path.home() / "Applications").expanduser()
    app = folder / "contact.app"
    contents = app / "Contents"
    if app.exists():
        shutil.rmtree(app)
    (contents / "MacOS").mkdir(parents=True)
    (contents / "Resources").mkdir()

    launcher = contents / "MacOS" / "contact"
    launcher.write_text(_LAUNCHER.format(port=PORT, command=shlex.quote(_contact_ui())))
    launcher.chmod(0o755)
    _icon(contents / "Resources" / "contact.icns")
    with open(contents / "Info.plist", "wb") as f:
        plistlib.dump({
            "CFBundleName": "contact",
            "CFBundleDisplayName": "contact",
            "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleExecutable": "contact",
            "CFBundleIconFile": "contact",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": app_version,
            "CFBundleVersion": app_version,
            "LSMinimumSystemVersion": "11.0",
        }, f)
    # let Finder and the Dock pick up the new icon
    lsregister = Path("/System/Library/Frameworks/CoreServices.framework/Frameworks/"
                      "LaunchServices.framework/Support/lsregister")
    if lsregister.exists():
        subprocess.run([str(lsregister), "-f", str(app)], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return app
