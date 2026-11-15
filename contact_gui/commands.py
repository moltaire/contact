"""
contact_gui/commands.py
───────────────────────
Slash commands for the refine field in review. A line that starts with "/" sets a
field directly, without calling the model:

    /person Felix                 /person Felix, Bea
    /landmark Neue Nationalgalerie
    /place Athens, Greece
    /tag scaffolding, cranes

Anything else typed into the field is a fact for the model.
"""

# command → the names it answers to. Any unambiguous prefix works too: /pe, /l, /pl, /t.
COMMANDS = {
    "person": ("person", "people"),
    "landmark": ("landmark", "lm"),
    "place": ("place",),
    "tag": ("tag", "tags"),
}
USAGE = "/person Name · /landmark Name · /place City, Country · /tag keyword"


class CommandError(ValueError):
    """The text looked like a command but cannot be run; the message says why."""


def is_command(text: str) -> bool:
    return text.lstrip().startswith("/")


def parse_command(text: str) -> tuple[str, list[str]]:
    """Split "/person Felix, Bea" into ("person", ["Felix", "Bea"]).

    A place is one value, commas included. Raises CommandError for an unknown or
    ambiguous command, or one without a value.
    """
    word, _, rest = text.strip()[1:].partition(" ")
    word = word.casefold()
    matches = [
        command for command, names in COMMANDS.items()
        if word and any(name.startswith(word) for name in names)
    ]
    exact = [command for command, names in COMMANDS.items() if word in names]
    if len(exact) == 1:
        matches = exact
    if len(matches) != 1:
        problem = "Unknown command" if not matches else "Ambiguous command"
        raise CommandError(f"{problem} “/{word}”. Use {USAGE}")
    command = matches[0]
    values = [rest.strip()] if command == "place" else [v.strip() for v in rest.split(",")]
    values = [v for v in values if v]
    if not values:
        raise CommandError(f"/{command} needs a value. Use {USAGE}")
    return command, values


def complete(text: str, people: list[str], landmarks: list[str], places: list[str]) -> str:
    """What Tab turns the text into: the full command, then the first known name that
    starts with what was typed. "/pe in" → "/person Ines". Returns the text unchanged
    if there is nothing to complete. For several comma-separated names, the last one
    is completed.
    """
    if not is_command(text):
        return text
    word, space, rest = text.lstrip()[1:].partition(" ")
    try:
        command, _ = parse_command(f"/{word} x")
    except CommandError:
        return text
    if not space:
        return f"/{command} "
    known = {"person": people, "landmark": landmarks, "place": places}.get(command)
    if not known:
        return f"/{command} {rest}"
    done, typed = ("", rest) if command == "place" else rest.rpartition(",")[::2]
    done = rest[: len(rest) - len(typed)]
    prefix = typed.strip().casefold()
    match = next((name for name in known if prefix and name.casefold().startswith(prefix)), None)
    if match is None:
        return f"/{command} {rest}"
    lead = done + (" " if done and not done.endswith(" ") else "")
    return f"/{command} {lead}{match}"


def split_values(text: str) -> list[str]:
    """ "Ines, Bea" → ["Ines", "Bea"]: several values on one entry line."""
    return [value.strip() for value in text.split(",") if value.strip()]


def complete_value(text: str, known: list[str], single: bool = False) -> str:
    """Complete what is being typed on an entry line against known names.

    With several comma-separated values the last one is completed; `single` treats the
    whole text as one value (a place contains a comma itself).
    """
    done, _, typed = ("", "", text) if single else text.rpartition(",")
    prefix = typed.strip().casefold()
    match = next((name for name in known if prefix and name.casefold().startswith(prefix)), None)
    if match is None:
        return text
    return f"{done}, {match}" if done else match


def completions(people: list[str], landmarks: list[str], places: list[str]) -> list[str]:
    """Full commands for the field's inline completion (Tab accepts)."""
    return [
        *(f"/person {name}" for name in people),
        *(f"/landmark {name}" for name in landmarks),
        *(f"/place {place}" for place in places),
    ]
