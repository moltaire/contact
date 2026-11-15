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


def completions(people: list[str], landmarks: list[str], places: list[str]) -> list[str]:
    """Full commands for the field's inline completion (Tab accepts)."""
    return [
        *(f"/person {name}" for name in people),
        *(f"/landmark {name}" for name in landmarks),
        *(f"/place {place}" for place in places),
    ]
