# Features, Fixes, Ideas

## User experience

- [x] Select Folder should load an overview of the images in the folder
- [x] On the Roll Info page, show a collapsible image browser so you can check subjects/locations while filling in the form
- [x] Show the roll label or folder path throughout the process (title reads `contact · ~/path` or `contact · Label` once a label is set)
- [x] Contact sheet shouldn't auto-open when reaching the final step
- [x] Fixed misleading tooltip on Rebuild button (removed "no AI" phrasing)
- [ ] Title should only show folder name or roll label. Not full path
- [ ] Long tags are abbreviated. That's not good, especially for lenses, subjects, locations

## Documentation

- [x] Add screenshots of the UI
- [x] Make sample contact sheet into a GitHub page
- [ ] Add installation instructions for ollama + llama3.2-vision (e.g., brew)

## Features

- [ ] We could AI generate a missing roll label / use the default renaming pattern
- [ ] Add a (default?) option to rename the folder using GUI. CLI already allows for this
- [ ] It would be nice to also have an index of contact sheets in a folder. To browser rolls basically. Could have a rather simple table format that shows some of the metadata, maybe allows for sorting. Searching across rolls would be a killer feature.

## Bugs

- [ ] Somehow, I ended up with a roll without AI summary. I did switch tabs during processing, so the tagging page was reloaded. Maybe that led to confusion. Question here: Should the tagging process continue in the background? I think yes. If so, we should also persist the process bar.

## Improvements

- The review process is very slow (saving and moving on to the next). Basically no fun at all to do right now.
