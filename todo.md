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
- [ ] README screenshots still show the Streamlit UI — retake

### 3. Keep tags, people and places apart
- [ ] Tags are generic keywords only, always lowercase — enforced in code, not left to the model
- [ ] Seen again in testing: refine put "National Theatre", "Prague" and "Czechia" into tags
- [ ] Sanitation step after every model answer and every refine: lowercase, de-duplicate, and drop any tag that is a person on the frame or part of its place (seen: "Krefeld, Germany", "Berlin, Germany" and "ines" ending up in tags)
- [ ] Named things (Hamburger Bahnhof, Varvakios Market, an exhibition) go in the place's local part and the description, where capitals are kept — not in tags
- [ ] Refine: when a fact names someone from the roll's subjects ("celebrating ines birthday"), mark that person on the frame instead of adding a tag
- [ ] Do this together with the single structured call for tagging (see Improvements): both define what the model returns

### 4. Settings menu
- [ ] Move vision/text model selection out of the tagging step into a small settings overlay, with a short explanation of what each model does
- [ ] Manage the remembered options there (places, lenses, cameras, film stocks, labs, people): rename, merge, delete
- [ ] Quit button that stops the app, so there is no need to close the tab and Ctrl-C the process

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
- [ ] Add installation instructions for ollama + llama3.2-vision (e.g., brew)

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
- [ ] Replace the two-stage vision + synthesis calls with one structured call (faster; fixes wordy tags and wrong categories such as cat = portrait)
- [ ] Option to re-process only frames with empty descriptions
- [x] Remove the Streamlit app once the NiceGUI app has proven itself
- [ ] Add tests (parser, roll.yaml and XMP round-trips)
