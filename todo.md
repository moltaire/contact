# Features, Fixes, Ideas

## Next up (in this order)

### 1. Small UI fixes + finish testing
- [x] Review: the thumbnail bar must not scroll up and down, only sideways
- [x] Header: drop the "·" separator now that the orange dot is there
- [x] Header: left-align the "contact" wordmark with the content below
- [x] Make the "AI" marker faint, small grey reminder text — or drop it
- [x] Review: "Add person…" must stay visible however many names there are
- [x] Person names are always capitalized (typed in review or in roll info)
- [x] Test what was coded but not exercised: place dropdown and duplicate handling, summary refresh on the contact sheet step, re-tag keeping people/place/facts, refine on several frames, light theme

### 2. Remove Streamlit
- [x] Delete `app.py`, `contact_ui.py`, the dependency and the README section (git tag `last-streamlit` marks the last commit that has it)
- [x] Command name: `contact-ui` now starts the new app; `contact-gui` is kept as an alias
- [x] README screenshots retaken from the new app (headless Chrome against `/?tab=<step>` on the sample roll)

### 3. Keep tags, people and places apart
- [x] Tags are generic keywords only, always lowercase — enforced in code, not left to the model
- [x] Seen again in testing: refine put "National Theatre", "Prague" and "Czechia" into tags
- [x] Sanitation step after every model answer and every refine: lowercase, de-duplicate, and drop any tag that is a person on the frame or part of its place (seen: "Krefeld, Germany", "Berlin, Germany" and "ines" ending up in tags)
- [x] Named things (Hamburger Bahnhof, Varvakios Market, an exhibition) go in the place's local part and the description, where capitals are kept — not in tags
- [x] Refine: when a fact names someone from the roll's subjects ("celebrating ines birthday"), mark that person on the frame instead of adding a tag
- [x] Do this together with the single structured call for tagging (see Improvements): both define what the model returns

### 4. Settings menu
- [x] Move vision/text model selection out of the tagging step into a small settings overlay, with a short explanation of what each model does
- [x] Manage the remembered options there (places, lenses, cameras, film stocks, labs, people): rename, merge, delete
- [x] Quit button that stops the app, so there is no need to close the tab and Ctrl-C the process

### 5. Landmarks as their own class
- [x] Place is always "City, Country"; landmarks (Neue Nationalgalerie) are chips like people, several per frame
- [x] Refine fills landmarks from the facts given; sidecars written with a three-part place are split on read
- [x] Settings: move remembered entries between People and Landmarks
- [ ] Rolls saved earlier still list landmarks under subjects, and their frames under people — no bulk fix yet

### Ideas for later
- [x] Slash commands in the refine field for keyboard-only review: `/person`, `/landmark`, `/place`, `/tag` set the field directly without calling the model; `/` jumps to the field, Esc leaves it

### 6. Review as one entry line and a sheet
- [x] One entry line with five modes (fact, tags, people, landmarks, place): Return opens, Tab switches mode on an empty line, Return applies and leaves; T/P/L/W/F open a mode directly; the last mode is remembered
- [x] The frame's labels are a plain sheet (who, what, where, tags, category); click an entry or press Backspace on an empty line to remove
- [ ] Next priority: cross-roll index and search — plan agreed 2026-11-15:

### 7. Library: cross-roll index and search
Decisions: all processed rolls live in ONE parent folder (set it in Settings). The contact sheets stay the product for browsing and sharing; the Library is an extra screen in the app. Search returns frames, each with a clear roll origin and the roll's date.
- [x] `processor/library.py`: scan the library folder for subfolders with a `roll.yaml`, read roll info and every frame's sidecar; cache and re-read only changed folders. With tests (the project's first)
- [x] Search logic: free text over descriptions, tags, people, landmarks, places and roll fields (film, camera, lens, date); pure functions, tested
- [x] Library folder: chosen on the Library screen itself ("Change"), saved in settings.json
- [x] (redone 2026-11-16 as roll cards — eight frames as a mini contact sheet, year headings, Rolls/Frames toggle, filters collapsed, no hover text; the table was rejected) Library screen before a roll is opened: sortable roll table (label, date, film, camera, place, people, frame count, first frame as thumbnail); click opens the roll
- [x] Search box and result grid of frames, grouped by roll with label and date; filters for people, places, film
- [x] Open a roll in review at a given frame from a result (thumbnail route must serve frames from any roll in the library, not just the open one)
- [ ] Later: static library page that links the rolls' contact sheets, for browsing and sharing without the app

### Later
- Tests, cross-roll index and search, contact sheet redesign, coordinates for places, AI-suggested roll label, Ollama install instructions

## User experience

- [x] Select Folder should load an overview of the images in the folder
- [x] On the Roll Info page, show a collapsible image browser so you can check subjects/locations while filling in the form
- [x] Show the roll label or folder path throughout the process (title reads `contact · ~/path` or `contact · Label` once a label is set)
- [x] Contact sheet shouldn't auto-open when reaching the final step
- [x] Fixed misleading tooltip on Rebuild button (removed "no AI" phrasing)
- [x] Title should only show folder name or roll label. Not full path (NiceGUI app)
- [x] Long tags are abbreviated. That's not good, especially for lenses, subjects, locations (NiceGUI app: chips wrap)

## Documentation

- [x] Add screenshots of the UI
- [x] Make sample contact sheet into a GitHub page
- [x] Add installation instructions for ollama (brew) and the default model

## Features

- [ ] We could AI generate a missing roll label / use the default renaming pattern
- [x] Add an option to rename the folder using GUI (NiceGUI app, contact sheet step). Not a default yet.
- [ ] It would be nice to also have an index of contact sheets in a folder. To browser rolls basically. Could have a rather simple table format that shows some of the metadata, maybe allows for sorting. Searching across rolls would be a killer feature.

- [x] Review: tell the model a fact about a frame and let it rewrite the metadata (NiceGUI app)
- [x] Review: assign people and a place per frame, for one or several frames (NiceGUI app)
- [ ] Coordinates / map for places (place names only for now; stored as their own field so GPS can be added later)
- [ ] Roll summary could name who actually appears in the frames
- [ ] Improve the generated contact sheet

## Bugs

- [x] (NiceGUI app: tagging runs in the background with persistent progress; summary now covers all tagged frames) Somehow, I ended up with a roll without AI summary. I did switch tabs during processing, so the tagging page was reloaded. Maybe that led to confusion. Question here: Should the tagging process continue in the background? I think yes. If so, we should also persist the process bar.
- [x] When ollama isn't running, it just throws "Connection refused" errors. Now starts ollama automatically, or explains what to do.
- [x] Thinking models (gemma4, qwen3.5) returned empty descriptions for most frames; empty results were saved as tagged.
- [x] Portrait frames were sent to the model sideways (EXIF orientation ignored).

## Improvements

- [x] The review process is very slow (saving and moving on to the next). NiceGUI app: one frame at a time, autosave, arrow keys.
- [x] Replace the two-stage vision + synthesis calls with one structured call (about 5.5 s per frame instead of 9; short lowercase tags; animals are no longer "portrait")
- [ ] Option to re-process only frames with empty descriptions
- [x] Remove the Streamlit app once the NiceGUI app has proven itself
- [ ] Add more tests (roll.yaml and XMP round-trips, tag clean-up); `tests/test_library.py` covers the library (run `uv run pytest`)
