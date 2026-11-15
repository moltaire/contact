"""
contact_gui/help.py
───────────────────
Keyboard shortcuts overlay: a centred panel on top of everything, toggled with "?".
"""

from nicegui import ui

# (keys, what they do) per section. A key written as "a b" renders as two key caps.
_SECTIONS = {
    "Review": [
        ("← →", "Previous / next frame"),
        ("1 … 9", "Toggle a person on the frame"),
        ("Return", "Jump to the fact field ( / works too)"),
        ("Esc", "Leave the field you are typing in"),
        ("Return", "In the field: apply, and leave it"),
        ("⌘ click", "Add a frame to the selection (Ctrl on Windows and Linux)"),
        ("⇧ click", "Select a range of frames"),
        ("A", "Select all frames"),
        ("Esc", "Clear the selection"),
    ],
    "Commands in the fact field": [
        ("/person Name", "Mark a person — several with commas"),
        ("/landmark Name", "Mark a landmark"),
        ("/place City, Country", "Set the place"),
        ("/tag keyword", "Add tags"),
        ("/pe /l /pl /t", "Short forms"),
        ("Tab", "Complete the command or a known name"),
    ],
    "Anywhere": [
        ("?", "Show or hide this overview"),
    ],
}

_NOTE = ("Edits are saved as you make them. People, landmarks, place, facts and commands "
         "apply to the current frame and to every frame selected in the filmstrip.")


class HelpDialog:
    def __init__(self) -> None:
        with ui.dialog() as self.dialog, ui.card().classes("help-card"):
            with ui.row().classes("w-full items-center"):
                ui.label("Keyboard shortcuts").classes("text-lg wordmark-plain")
                ui.space()
                ui.button(icon="close", on_click=self.dialog.close).props("flat round dense")
            with ui.row().classes("w-full no-wrap gap-10 items-start"):
                columns = list(_SECTIONS.items())
                # the command column has longer keys, so it gets a wider key gutter
                for group, gutter in ((columns[:1], "6.5rem"), (columns[1:], "12rem")):
                    with ui.column().classes("gap-4 w-1/2"):
                        for title, rows in group:
                            self._section(title, rows, gutter)
            ui.label(_NOTE).classes("text-sm help-note")

    @staticmethod
    def _section(title: str, rows: list[tuple[str, str]], gutter: str) -> None:
        with ui.column().classes("w-full gap-1"):
            ui.label(title).classes("help-title")
            for keys, what in rows:
                with ui.row().classes("w-full items-baseline no-wrap gap-3"):
                    with ui.row().classes("gap-1 no-wrap shrink-0").style(f"width: {gutter}"):
                        # commands stay in one cap; plain keys get one cap each
                        for key in ([keys] if keys.startswith("/") and " " in keys and keys.count("/") == 1
                                    else keys.split(" ")):
                            ui.label(key).classes("kbd")
                    ui.label(what).classes("text-sm")

    def toggle(self) -> None:
        self.dialog.close() if self.dialog.value else self.dialog.open()

    @property
    def is_open(self) -> bool:
        return bool(self.dialog.value)
