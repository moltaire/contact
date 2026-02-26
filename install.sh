#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# screenshot-sorter installer
#
# Run once from the repo directory:
#   bash install.sh
#
# What it does:
#   1. Checks for Ollama and the vision model; offers to install them.
#   2. Asks where your screenshot inbox and archive folders are.
#   3. Asks for a schedule (daily or weekly).
#   4. Generates and installs a macOS LaunchAgent that runs the sorter
#      automatically on that schedule.
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_PATH="$REPO_DIR/sort_screenshots.py"
PLIST_LABEL="com.screenshot-sorter"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
DEFAULT_MODEL="moondream"

# ── helpers ───────────────────────────────────────────────────────────────────

ask() {
    # ask PROMPT DEFAULT
    local prompt="$1" default="$2" answer
    read -r -p "$prompt [$default]: " answer
    echo "${answer:-$default}"
}

confirm() {
    # confirm PROMPT  → returns 0 for yes, 1 for no
    local answer
    read -r -p "$1 [Y/n]: " answer
    [[ "${answer:-Y}" =~ ^[Yy] ]]
}

separator() { echo; echo "────────────────────────────────────────"; echo; }

# ── header ────────────────────────────────────────────────────────────────────

echo
echo "  screenshot-sorter installer"
echo "  ────────────────────────────"
echo

# ── 1. Python ─────────────────────────────────────────────────────────────────

PYTHON=$(command -v python3 || true)
if [[ -z "$PYTHON" ]]; then
    echo "✗ python3 not found. Please install Python 3 and re-run."
    exit 1
fi
echo "✓ Python: $PYTHON ($($PYTHON --version 2>&1))"

# ── 2. Ollama ─────────────────────────────────────────────────────────────────

if command -v ollama &>/dev/null; then
    echo "✓ Ollama: $(ollama --version 2>/dev/null | head -1)"
else
    echo "✗ Ollama not found."
    if confirm "  Install Ollama via Homebrew?"; then
        if ! command -v brew &>/dev/null; then
            echo "  Homebrew not found. Install it from https://brew.sh, then re-run."
            exit 1
        fi
        brew install ollama
        echo "✓ Ollama installed."
    else
        echo "  Skipping. You can install Ollama manually from https://ollama.com"
        echo "  Then re-run this installer."
        exit 0
    fi
fi

# ── 3. Vision model ───────────────────────────────────────────────────────────

MODEL=$(ask "  Vision model to use" "$DEFAULT_MODEL")

# Check if the model is already pulled (requires ollama to not be serving yet;
# `ollama list` works without the server running on newer versions)
if ollama list 2>/dev/null | grep -q "^${MODEL}"; then
    echo "✓ Model '$MODEL' already available."
else
    echo "  Model '$MODEL' not found locally."
    if confirm "  Pull '$MODEL' now? (may take a few minutes)"; then
        ollama pull "$MODEL"
        echo "✓ Model '$MODEL' ready."
    else
        echo "  Skipping pull. Run 'ollama pull $MODEL' before using the sorter."
    fi
fi

separator

# ── 4. Folders ────────────────────────────────────────────────────────────────

echo "Where should screenshots land before sorting (the inbox)?"
INCOMING=$(ask "  Inbox folder" "$HOME/Pictures/Screenshots/incoming")
INCOMING="${INCOMING/#\~/$HOME}"   # expand ~ manually for reliability

echo
echo "Where should sorted screenshots be archived?"
ARCHIVE=$(ask "  Archive folder" "$HOME/Pictures/Screenshots")
ARCHIVE="${ARCHIVE/#\~/$HOME}"

mkdir -p "$INCOMING" "$ARCHIVE"
echo
echo "✓ Inbox:   $INCOMING"
echo "✓ Archive: $ARCHIVE"

separator

# ── 5. Schedule ───────────────────────────────────────────────────────────────

echo "How often should the sorter run?"
echo "  1) Daily"
echo "  2) Weekly (every Monday)"
read -r -p "  Choice [1]: " SCHED_CHOICE
SCHED_CHOICE="${SCHED_CHOICE:-1}"

HOUR=$(ask "  Run at hour (0–23, 24h)" "9")

if [[ "$SCHED_CHOICE" == "2" ]]; then
    SCHEDULE_XML="    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>1</integer>
        <key>Hour</key>
        <integer>$HOUR</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>"
    SCHEDULE_DESC="every Monday at ${HOUR}:00"
else
    SCHEDULE_XML="    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>$HOUR</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>"
    SCHEDULE_DESC="daily at ${HOUR}:00"
fi

separator

# ── 6. Generate and install the LaunchAgent plist ─────────────────────────────

LOG_FILE="$ARCHIVE/sorter.log"

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_DST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>

    <key>Label</key>
    <string>$PLIST_LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>$SCRIPT_PATH</string>
        <string>--incoming</string>
        <string>$INCOMING</string>
        <string>--archive</string>
        <string>$ARCHIVE</string>
        <string>--model</string>
        <string>$MODEL</string>
    </array>

$SCHEDULE_XML

    <key>StandardOutPath</key>
    <string>$LOG_FILE</string>
    <key>StandardErrorPath</key>
    <string>$LOG_FILE</string>

    <key>RunAtLoad</key>
    <false/>

</dict>
</plist>
EOF

# Reload (unload first in case it was already installed)
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"

echo "✓ LaunchAgent installed  →  $PLIST_DST"
echo "  Schedule: $SCHEDULE_DESC"
echo "  Log:      $LOG_FILE"

separator

# ── 7. macOS screenshot save location reminder ────────────────────────────────

echo "One manual step: point macOS screenshots to your inbox."
echo
echo "  macOS 14+:  Settings → Keyboard → Keyboard Shortcuts → Screenshots"
echo "              (or open the Screenshot app → Options → Save to)"
echo "  Set 'Save to' →  $INCOMING"
echo

separator

echo "Done! To run the sorter manually at any time:"
echo
echo "  python3 \"$SCRIPT_PATH\" \\"
echo "    --incoming \"$INCOMING\" \\"
echo "    --archive  \"$ARCHIVE\""
echo
