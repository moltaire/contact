# 🎞️ contact

<img src="docs/contact.png" width="100%" alt="contact screenshot">

contact is a tool to tag and archive analog film scans using locally running AI. Set up a roll, point it at a folder of scans, and it generates descriptions, tags, and categories for each frame, writing XMP sidecar files and creating a [browsable HTML contact sheet](https://moltaire.github.io/contact).

---

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) with a vision model pulled

```bash
brew install ollama        # or download it from ollama.com
ollama pull gemma4:e4b     # about 10 GB; runs comfortably in 16 GB of RAM
```

contact starts Ollama itself when it is not running.

---

## Install

```bash
uv tool install .
```

This installs two commands: `contact` (CLI) and `contact-ui` (browser app; `contact-gui` is the same thing).

---

## App

```bash
contact-ui
# or with a folder pre-loaded:
contact-ui --folder ~/scans/tuscany/
```

The app runs locally and opens in your browser.

**Library** — point it once at the folder that holds all your roll folders. It lists every roll in a sortable table (date, film, camera, place, people, frames) and searches across all frames: descriptions, tags, people, landmarks, places, and the roll's film, camera, lens and date. Results are frames grouped by roll, with the roll's date; click one to open its roll in review at that frame. Search ignores case and accents, quotes keep words together, and a prefix limits a word to one field (`person:ines`, `place:athens`, `film:hp5`, `tag:tower`, `date:2024`). The library only reads your folders; the contact sheets stay the thing you browse and share.

A single roll goes through five steps:

1. **Folder** — type or browse to a folder of scans
2. **Roll info** — describe the roll: film stock, camera, lens, date, location, people, landmarks, lab
3. **Tagging** — choose frames and let the model describe them. Runs in the background: you can switch tabs, reload or close the browser and the run carries on. Failed frames are listed and stay untagged so they can be retried.
4. **Review** — one frame at a time, built for the keyboard. Edits are saved automatically; ← → or the filmstrip move between frames. Below the description there is one entry line and a sheet listing who, what, where, the tags and the category.
   - **The entry line has five modes:** fact, tags, people, landmarks, place. Return opens it, Tab switches mode while it is empty, Return applies and leaves it. `T`, `P`, `L`, `W`, `F` open it straight in a mode, and it remembers the last one.
   - **Fact:** tell the model something it cannot know ("this is the Parthenon in Athens") and it rewrites description, tags and category, with undo. Facts are stored with the frame and re-applied when it is re-tagged.
   - **People, landmarks, place, tags:** type names, several with commas; Tab completes a known name. The roll's people, landmarks and places appear under the line to click. New names are added to the roll.
   - **Removing:** click an entry in the sheet, or press Backspace on an empty line.
   - **Several frames:** ⌘/Ctrl-click or Shift-click frames in the filmstrip (`A` selects all, Esc clears) and whatever you enter applies to all of them.
   - Slash commands also work in fact mode (`/person Felix`, `/landmark …`, `/place …`, `/tag …`), and `?` shows all shortcuts.
5. **Contact sheet** — rebuilt from your edits, with the roll summary refreshed. The folder can be renamed to the standard `date_label` pattern here.

Dark theme by default; start with `--light` for the light one.

<p>
  <img src="docs/screenshots/contact_2_roll.png" width="49%" alt="Roll info">
  <img src="docs/screenshots/contact_3_tagging.png" width="49%" alt="Tagging">
</p>
<p>
  <img src="docs/screenshots/contact_4_review.png" width="49%" alt="Review">
  <img src="docs/screenshots/contact_5_sheet.png" width="49%" alt="Contact sheet">
</p>

The gear icon opens **Settings**: choose the vision and text model, tidy the remembered options (places, people, landmarks, lenses, cameras, film stocks, labs) — including moving landmarks that were filed under people, and quit the app.

---

## CLI

```bash
# Set up a roll interactively, then tag it
contact --init ~/scans/tuscany/

# Tag without setup
contact ~/scans/tuscany/

# Multiple rolls — pass several folders or a parent folder
contact --init ~/scans/2024/
contact ~/scans/2024/

# Common flags
contact ~/scans/tuscany/ --dry-run    # preview without writing
contact ~/scans/tuscany/ --force      # re-tag already-tagged images
contact ~/scans/tuscany/ --verbose    # show full AI output per frame
```

### Options

| Flag | Description |
|---|---|
| `--init` | Run interactive roll setup |
| `--model MODEL` | Vision model (default: the best installed vision model, e.g. `gemma4:e4b`) |
| `--text-model MODEL` | Separate model for the roll summary (default: same as `--model`) |
| `--dry-run` | Preview without writing any files |
| `--force` | Re-tag images that already have a sidecar |
| `--verbose` | Print full AI output for each frame |
| `--no-rename-folder` | Skip renaming the folder after processing |

---

## Roll setup

Roll-level metadata is saved to `roll.yaml` in the scan folder:

- **Film stock, camera** — pick from suggestions or type your own
- **Lenses, locations, people, landmarks** — multiple values allowed; previous entries are suggested. Locations are written as `City, Country`.
- **Lab, lab notes, date, notes** — free text
- **Label** — short name used as the contact sheet title (e.g. `Oslo Summer 2024`)

History is remembered across sessions in `~/.config/contact/history.json`.

---

## Output

**XMP sidecars** (one per image) contain the AI-generated description, tags, and category, plus roll metadata and anything added in review: people, landmarks, place and the facts you gave the model. Readable by Lightroom, darktable, Finder, and Spotlight.

**`index.html`** — a self-contained contact sheet with:
- Image overview and lightbox
- Roll metadata
- Full-text search across descriptions, tags, filenames, and categories (`/` or `Enter` to focus)
- Star frames to pin them to the top

---

## How it works

Each frame is sent to a local vision model once. It answers with a 2–3 sentence description of what is physically visible, a handful of generic lowercase tags, and one category. It is told not to guess who or where — names, landmarks and places are yours to add in review, where a fact you state is passed back to the model to rewrite the frame.

Tags are cleaned in code after every answer and edit: lowercased, de-duplicated, and never a person, landmark or place, which have their own fields.

After all frames are processed, a short summary of the whole roll is written to the HTML index. It is refreshed when you open the contact sheet step after editing frames.

## Try it out

A sample roll is included at `docs/example/sample-roll/`. It has pre-tagged images, XMP sidecars, and a rendered `index.html`. See a live version [here](https://moltaire.github.io/contact). Or run the UI on it yourself:

```bash
# Open the contact sheet directly
open docs/example/sample-roll/index.html

# Or load it in the app (no Ollama needed to browse and edit by hand)
contact-ui --folder docs/example/sample-roll/
```

To re-process it from scratch:

```bash
contact docs/example/sample-roll/ --force
```

---

## Limitations

The AI model runs locally, which I prefer for privacy, bandwidth and cost. But the smaller model also comes with limitations. Sometimes descriptions and tags are off. You can use the UI version to review and edit metadata, or just roll with the AI errors. If you have a computer with lots of RAM, feel free to load a bigger vision model and/or a separate text model for text synthesis.
