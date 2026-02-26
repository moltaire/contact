# screenshot-sorter

Automatically renames and archives screenshots using a local vision model.

New screenshots land in an **inbox** folder. A scheduled job runs Ollama,
describes each image, renames it to `YYYY-MM-DD_brief-description.ext`,
moves it to your **archive**, and shuts Ollama back down. No cloud, no
manual sorting.

```
inbox/
  Screenshot 2026-02-26 at 10.19.30.png
  Screenshot 2026-02-24 at 09.05.11.png

          ↓  runs overnight  ↓

archive/
  2026-02-26_checkerboard-illusion-lecture.png
  2026-02-24_concert-listing-berlin.png
```

---

## Prerequisites

| Requirement | Notes |
|---|---|
| macOS | LaunchAgent scheduling is macOS-only |
| Python 3 | Ships with macOS; `python3 --version` to check |
| [Ollama](https://ollama.com) | Local model runner — installer can set this up |
| A vision model | Default: `moondream` (fast, ~1.8 GB). Also works with `llava:7b`, `llama3.2-vision`, etc. |

---

## Install

Clone or download the repo, then run the installer:

```bash
git clone https://github.com/you/screenshot-sorter
cd screenshot-sorter
bash install.sh
```

The installer will:

1. Check for Python and Ollama (offer to install Ollama via Homebrew if missing)
2. Pull the vision model if not already present
3. Ask for your **inbox** and **archive** folder paths
4. Ask for a schedule (daily or weekly, what time)
5. Generate and install a macOS LaunchAgent — no further action needed

After install, point macOS to save screenshots to your inbox:
**macOS Settings → Keyboard Shortcuts → Screenshots → Save to → [your inbox]**
(or open the Screenshot app → Options → Save to)

---

## Manual usage

```bash
python3 sort_screenshots.py \
  --incoming /path/to/inbox \
  --archive  /path/to/archive
```

Optional flags:

| Flag | Default | Description |
|---|---|---|
| `--model` | `moondream` | Any Ollama vision model |

---

## How it works

- Dates are read from the filename (works with all macOS screenshot formats and
  iPhone screenshots). Falls back to file modification time for other images.
- Ollama is started only if not already running, and stopped when the job
  finishes — it won't interfere if you have it open for other reasons.
- If two files would get the same name, a counter suffix is appended
  (`_1`, `_2`, …).
- The LaunchAgent log lives next to your archive as `sorter.log`.

---

## Updating

```bash
git pull
bash install.sh   # re-run to apply any changes to the LaunchAgent
```

---

## Supported model alternatives

| Model | Size | Notes |
|---|---|---|
| `moondream` | ~1.8 GB | Fast, good for simple captioning |
| `llava:7b` | ~4 GB | Better descriptions, needs ~8 GB RAM |
| `llama3.2-vision:11b` | ~8 GB | High quality, needs ~16 GB RAM |

Change model by re-running `install.sh` or editing the LaunchAgent plist at
`~/Library/LaunchAgents/com.screenshot-sorter.plist`.

---

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.screenshot-sorter.plist
rm ~/Library/LaunchAgents/com.screenshot-sorter.plist
```

Your inbox, archive, and screenshots are untouched.
