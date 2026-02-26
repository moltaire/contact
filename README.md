# screenshot-sorter

Renames and archives screenshots using local AI. Screenshots land in an inbox
folder; a scheduled job renames each to `YYYY-MM-DD_brief-description.ext` and
moves it to your archive.

```
inbox/
  Screenshot 2026-02-26 at 10.19.30.png

          ↓  runs overnight  ↓

archive/
  2026-02-26_multi-panel-behavioral-results.png
```

---

## How it works

Each image goes through three stages:

1. **Vision model** (Ollama) — describes the visual content, including titles, labels, and axis names
2. **OCR** (Tesseract) — extracts all text from the image; supports English and German
3. **Text LLM** (Ollama) — combines the visual description and OCR text into a 3–5 word hyphenated slug

Additional details:

- Dates are read from the filename (macOS, older macOS, and iPhone formats). Falls back to file modification time.
- Ollama is started if not already running and stopped when done.
- If two files would get the same name, a counter suffix is appended (`_1`, `_2`, …).
- The LaunchAgent log lives next to your archive as `sorter.log`.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| macOS | LaunchAgent scheduling is macOS-only |
| Python 3 | Ships with macOS; `python3 --version` to check |
| [Ollama](https://ollama.com) | Local model runner |
| A vision model | Default: `llama3.2-vision:11b` (~8 GB). See model options below. |
| [Tesseract](https://github.com/tesseract-ocr/tesseract) | OCR engine |

---

## Install

```bash
git clone https://github.com/you/screenshot-sorter
cd screenshot-sorter
bash install.sh
```

The installer will:

1. Check for Python, Ollama, and Tesseract (offer to install missing tools via Homebrew)
2. Ask which vision model to use and pull it if not already present
3. Optionally configure a separate, lighter text model for the synthesis step
4. Ask for your inbox and archive folder paths
5. Ask whether to keep originals after archiving
6. Ask for a schedule (daily or weekly, what time)
7. Generate and install a macOS LaunchAgent

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

| Flag | Default | Description |
|---|---|---|
| `--model` | `llama3.2-vision:11b` | Ollama vision model |
| `--text-model` | same as `--model` | Separate Ollama text model for slug synthesis |
| `--no-ocr` | off | Skip Tesseract OCR |
| `--dry-run` | off | Preview renames without moving any files |
| `--keep-originals` | off | Copy to archive and move originals to `inbox/processed/` |
| `--verbose` | off | Print vision description, OCR output, and slug for each image |

`--dry-run` runs the full pipeline but moves nothing. Pair with `--verbose` to inspect intermediate output:

```
  Screenshot 2026-02-26 at 10.19.30.png
    [vision] A bar chart titled "Reaction Times by Condition" with four groups on the x-axis.
    [ocr]    Reaction Times by Condition ms Control Low High Very High p < 0.001
    [slug]   bar-chart-reaction-times
  → 2026-02-26_bar-chart-reaction-times.png  [dry-run, not moved]
```

`--keep-originals` copies each renamed file to the archive and moves the original to `inbox/processed/`. Originals are preserved but won't be re-processed on the next run.

`--text-model` lets you use a lighter model for slug synthesis:

```bash
python3 sort_screenshots.py \
  --incoming ~/Pictures/Screenshots/incoming \
  --archive  ~/Pictures/Screenshots \
  --model llama3.2-vision:11b \
  --text-model llama3.2:3b
```

---

## Supported models

### Vision models

| Model | Size | Notes |
|---|---|---|
| `llama3.2-vision:11b` | ~8 GB | **Default** |
| `llava:7b` | ~4.7 GB | Lighter alternative |
| `llava:13b` | ~8.0 GB | |
| `llava-phi3` | ~2.9 GB | Lightweight, weaker descriptions |
| `moondream` | ~1.8 GB | Very fast but produces generic names |

### Text models (for slug synthesis)

Without `--text-model`, the vision model handles synthesis as well. Any Ollama text model works for this step; smaller models are sufficient:

| Model | Size |
|---|---|
| `llama3.2:3b` | ~2 GB |
| `mistral` | ~4 GB |
| `gemma3:4b` | ~3 GB |

Change model by re-running `install.sh` or editing `~/Library/LaunchAgents/com.screenshot-sorter.plist`.

---

## Updating

```bash
git pull
bash install.sh
```

---

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.screenshot-sorter.plist
rm ~/Library/LaunchAgents/com.screenshot-sorter.plist
```

Your inbox, archive, and screenshots are untouched.
