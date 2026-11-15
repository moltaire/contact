"""
processor/tagger.py
───────────────────
Ollama API helpers, prompts, per-frame analysis, refinement, and roll summary generation.
"""

import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from .roll import (
    GENERATED_MARKER,
    _split_list_field,
    normalize_name,
    normalize_place,
    split_place,
)
from .sidecar import _load_image_b64

# ── Constants ─────────────────────────────────────────────────────────────────

OLLAMA_BASE = "http://localhost:11434"

# Used when no installed model can be detected. `ollama pull gemma4:e4b` provides it.
FALLBACK_MODEL = "gemma4:e4b"
# Installed vision models are ranked by the first prefix they match.
_PREFERRED_MODELS = ("gemma4:e4b", "gemma4:12b", "gemma4", "qwen3.5", "llama3.2-vision")
VALID_CATEGORIES = {
    "landscape", "portrait", "street", "architecture",
    "nature", "abstract", "other",
}

# ── Prompts ───────────────────────────────────────────────────────────────────

_CATEGORY_RULES = """\
- category: exactly one of
  portrait      a person's face is clearly visible and is the main subject (people only — \
never an animal; a figure seen from behind or at a distance is not a portrait)
  street        candid scene in a public urban setting with people or activity
  architecture  a building or structure is the main subject
  landscape     outdoor scenery — countryside, water, a wide city view — where no person dominates
  nature        plants or animals are the main subject
  abstract      pattern, texture or shape is the subject, with no recognisable scene
  other         anything not covered above"""

_TAG_RULES = """\
- tags: 6 to 10 generic keywords for what is visible, most important first. Lowercase, \
one or two words each ("cobblestone", "street lamp"). People by type only (man, woman, \
child, group). Add a lighting keyword only if it is obvious (backlight, high contrast, \
golden hour, window light). Never use names of people or places as tags."""

_DESCRIPTION_RULES = """\
- description: 2-3 factual sentences on subject, setting and composition. Describe only \
what is visible. No "The image shows" phrasing, no mood or atmosphere, no mention of film, \
grain or equipment."""

ANALYZE_SYSTEM = (
    "You are a cataloguing assistant for a photographer's archive of analog film scans. "
    "You describe photographs accurately and answer with JSON only."
)

ANALYZE_PROMPT = f"""\
Catalogue the attached photograph. Rules:
{_DESCRIPTION_RULES} Refer to people generically (a man, a woman, two people) and do \
not guess who or where — no names of people, landmarks, cities or countries.
{_TAG_RULES}
{_CATEGORY_RULES}"""

# Fallback when the full prompt makes a model loop or return nothing
ANALYZE_PROMPT_SHORT = f"""\
Catalogue the attached photograph briefly.
- description: one or two plain sentences naming the main subject and setting.
- tags: up to 6 lowercase keywords for what is visible.
{_CATEGORY_RULES}"""

ROLL_SUMMARY_SYSTEM = "You are a photography archivist. Write concise, factual roll summaries."

ROLL_SUMMARY_PROMPT_TMPL = """\
Roll metadata:
  Location: {location}
  Subjects: {subjects}
  Date: {date}

Frame descriptions:
{descriptions}

Write 2-3 sentences summarising this roll as a whole. \
You may reference subject names from the roll metadata as general context for the roll \
(e.g. "a roll with Felix and Bea"), but do not attribute specific actions, poses, or \
positions to named individuals — you cannot identify who is in which frame; \
describe people in individual frames generically (a man, a woman, the group). \
Anchor the location to the roll metadata — do not infer or add location details not stated there. \
Describe only what is directly stated in the frame descriptions — do not speculate. \
Do not describe mood, atmosphere, or emotional qualities. \
Do not mention film, camera, equipment, or technical qualities."""

REFINE_SYSTEM = (
    "You are a cataloguing assistant for a photographer's archive. "
    "You update a photo's metadata using facts the photographer gives you. "
    "You answer with JSON only."
)

REFINE_PROMPT_TMPL = """\
Current metadata of the attached photograph:

CATEGORY: {category}
TAGS: {tags}
DESCRIPTION: {description}

The photographer, who took this photo, states these facts about it:
{notes}

Rewrite the metadata so that it reflects these facts. Rules:
- The photographer's facts are true, even where the image alone would not prove them. \
Where they name something the current description refers to generically, use the name \
(for example "an ancient temple" becomes "the Parthenon").
- Names are often typed casually ("parthenon", "st nicholas"). Never copy that as typed: \
write every proper name with its correct spelling and capitalization.
- Every fact must end up in the description, including occasions and events \
("celebrating a birthday") that the image alone does not show. People the photographer \
names are written by name ("Ines' birthday", not "someone's birthday").
- Keep everything else that is still accurate. Do not add details that are neither \
visible in the image nor stated by the photographer.
{description_rules}
{tag_rules} Named things belong in the description and the landmarks, not in the \
tags: for "the Parthenon" the tag is "temple".
{category_rules}
- landmarks: the named buildings, monuments, venues, sites or exhibitions the \
photographer's facts mention (for example "Parthenon", "Neue Nationalgalerie"), each \
with its proper spelling. Only names the photographer gave — never guess one from the \
image. An empty list if they named none.
- place: the city and country the photo was taken in, as "City, Country" (for example \
"Athens, Greece"), only if the photographer's facts name the city; otherwise an empty \
string. Never guess. A landmark is not part of the place."""

# ── Answer formats ────────────────────────────────────────────────────────────

_ANALYZE_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "category": {"type": "string", "enum": sorted(VALID_CATEGORIES)},
    },
    "required": ["description", "tags", "category"],
}
_REFINE_SCHEMA = {
    "type": "object",
    "properties": {
        **_ANALYZE_SCHEMA["properties"],
        "landmarks": {"type": "array", "items": {"type": "string"}},
        "place": {"type": "string"},
    },
    "required": ["description", "tags", "category", "landmarks", "place"],
}

# Escalating attempts: full prompt, then a shorter one with a stronger repeat penalty.
# Budgets are generous on purpose: a truncated answer is worse than a slow one.
_ANALYZE_ATTEMPTS = [
    (ANALYZE_PROMPT,       {"num_predict": 600, "repeat_penalty": 1.1}),
    (ANALYZE_PROMPT,       {"num_predict": 600, "repeat_penalty": 1.3}),
    (ANALYZE_PROMPT_SHORT, {"num_predict": 300, "repeat_penalty": 1.5}),
]
_REFINE_OPTS = {"num_predict": 600}
_SUMMARY_OPTS = {"num_predict": 300, "repeat_penalty": 1.1}
_MAX_TAG_WORDS = 3

# ── Ollama helpers ─────────────────────────────────────────────────────────────


def ollama_ready() -> bool:
    try:
        urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=2)
        return True
    except Exception:
        return False


def wait_for_ollama(timeout: int = 30) -> bool:
    for _ in range(timeout):
        if ollama_ready():
            return True
        time.sleep(1)
    return False


def ensure_ollama(timeout: int = 30) -> "subprocess.Popen | None":
    """Make sure the Ollama server is reachable, starting it if necessary.

    Returns the process we started (so the caller can stop it again), or None
    if Ollama was already running. Raises RuntimeError if it cannot be reached.
    """
    if ollama_ready():
        return None
    try:
        proc = subprocess.Popen(
            ["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Ollama is not installed (the `ollama` command was not found). "
            "Install it from https://ollama.com, then run `ollama pull gemma4:e4b`."
        ) from None
    if not wait_for_ollama(timeout):
        proc.terminate()
        raise RuntimeError(
            f"Ollama did not start within {timeout}s. Try running `ollama serve` in a terminal."
        )
    return proc


def _post(endpoint: str, body: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        f"{OLLAMA_BASE}{endpoint}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Ollama returned HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Cannot reach Ollama at {OLLAMA_BASE} ({e.reason}). "
            "Is it running? Start it with `ollama serve`."
        ) from e


def list_models() -> list[str]:
    """Names of all locally installed Ollama models (empty if Ollama is unreachable)."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=5) as resp:
            return [m["name"] for m in json.loads(resp.read()).get("models", [])]
    except Exception:
        return []


def model_capabilities(model: str) -> set[str]:
    """Capabilities Ollama reports for a model, e.g. {'completion', 'vision', 'thinking'}."""
    try:
        return set(_post("/api/show", {"model": model}, timeout=10).get("capabilities") or [])
    except Exception:
        return set()


def list_vision_models() -> list[str]:
    """Installed models that accept images, best default first."""
    models = [m for m in list_models() if "vision" in model_capabilities(m)]

    def rank(name: str) -> int:
        for i, prefix in enumerate(_PREFERRED_MODELS):
            if name.startswith(prefix):
                return i
        return len(_PREFERRED_MODELS)

    # Cloud models send images off the machine — never pick one by default.
    return sorted(models, key=lambda m: (m.endswith("-cloud"), rank(m)))


def default_vision_model() -> str:
    models = list_vision_models()
    return models[0] if models else FALLBACK_MODEL


def _generate(
    model: str,
    prompt: str,
    system: str,
    options: dict | None = None,
    images: list[str] | None = None,
    timeout: int = 300,
    schema: dict | None = None,
) -> str:
    """One non-streaming completion. Raises RuntimeError on an empty or cut-off answer.

    Thinking is switched off: for these short descriptive tasks it roughly doubles
    the time per frame without improving the result, and reasoning tokens count
    against num_predict — a long chain of thought leaves no room for the answer.
    """
    body: dict = {
        "model": model,
        "system": system,
        "prompt": prompt,
        "stream": False,
        "think": False,
    }
    if images:
        body["images"] = images
    if options:
        body["options"] = options
    if schema:
        body["format"] = schema  # constrains the answer to JSON matching the schema
    try:
        data = _post("/api/generate", body, timeout)
    except RuntimeError as e:
        # Some models reject the `think` field outright; retry without it.
        if "HTTP 400" not in str(e) or "think" not in str(e).lower():
            raise
        del body["think"]
        data = _post("/api/generate", body, timeout)

    text = (data.get("response") or "").strip()
    if not text:
        reason = data.get("done_reason", "unknown")
        hint = " (token budget spent on reasoning)" if data.get("thinking") else ""
        raise RuntimeError(f"model returned an empty answer, done_reason={reason}{hint}")
    return text



def _call_text(model: str, prompt: str, system: str, options: dict | None = None) -> str:
    return _generate(model, prompt, system, options, timeout=120)



# ── Repetition guard ──────────────────────────────────────────────────────────


def _is_repetitive(text: str) -> bool:
    # Degenerate symbol runs (soft hyphens, em dashes, ellipses)
    for sym, limit in [("—", 15), ("…", 8), (" .. ", 6), ("\xad", 10)]:
        if text.count(sym) > limit:
            return True

    # Sentence-level repetition: any sentence appearing 3+ times
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+|\n', text) if len(s.strip()) > 20]
    if sentences:
        sc: dict[str, int] = {}
        for s in sentences:
            sc[s] = sc.get(s, 0) + 1
        if max(sc.values()) >= 3:
            return True

    # 4-gram repetition: repeated phrases
    words = text.split()
    if len(words) >= 12:
        ngrams = [" ".join(words[i:i+4]) for i in range(len(words) - 3)]
        nc: dict[str, int] = {}
        for ng in ngrams:
            nc[ng] = nc.get(ng, 0) + 1
        if max(nc.values()) >= 3:
            return True

    # Word-level frequency (original check)
    clean = [w.strip(",.;:!?\"'()[]") for w in words]
    clean = [w for w in clean if w]
    if len(clean) < 6:
        return False
    wc: dict[str, int] = {}
    for w in clean:
        wc[w] = wc.get(w, 0) + 1
    return max(wc.values()) / len(clean) >= 0.35


# ── Reading the model's answer ────────────────────────────────────────────────


def sanitize_tags(
    tags: list, names: list[str] | None = None, place: str = "", max_words: int | None = None
) -> list[str]:
    """Tags are generic keywords: lowercase, unique, and never a person, landmark or place.

    The model is told this too, but it is enforced here. People, landmarks and places
    have their own fields (`names` takes the people and landmarks of the frame); a tag
    that repeats one of them, or a part of the place such as the city, is dropped.
    `max_words` is set for model output only: it also drops over-long phrases and
    category names.
    """
    taken = {n.casefold() for n in names or []}
    proper_words: set[str] = set()
    for name in names or []:
        proper_words |= set(name.casefold().split())
    if place:
        taken |= {place.casefold(), *(seg.strip().casefold() for seg in place.split(","))}
        proper_words |= set(place.casefold().replace(",", " ").split())
    clean: list[str] = []
    for item in tags or []:
        # some answers pack every tag into one comma-separated string
        for tag in str(item).split(","):
            tag = " ".join(tag.strip().strip("*`_.#").lower().split())
            if not tag or tag in clean or tag in taken:
                continue
            words = tag.split()
            # recombinations such as "prague national theatre"; a single generic word
            # that happens to be part of a name ("tower", "bridge") stays
            in_place = bool(place) and set(words) <= set(place.casefold().replace(",", " ").split())
            if in_place or (len(words) > 1 and set(words) <= proper_words):
                continue
            # model output only: no over-long phrases, no category names posing as tags
            if max_words and (len(words) > max_words or tag in VALID_CATEGORIES):
                continue
            clean.append(tag)
    return clean


def people_mentioned(text: str, known_people: list[str]) -> list[str]:
    """People from the roll whose name appears in the photographer's own words.

    Decided here rather than by the model, which tends to add everyone on the list.
    A full name always counts; a first name counts when only one person has it.
    "ines' birthday" and "Ines's" match "Ines".
    """
    words = set(re.findall(r"[^\W\d_]+", text.casefold()))
    firsts = [p.split()[0].casefold() for p in known_people if p.split()]
    found = []
    for person in known_people:
        parts = person.casefold().split()
        if not parts:
            continue
        full = re.search(r"(?<!\w)" + re.escape(person.casefold()) + r"(?!\w)", text.casefold())
        first_only = firsts.count(parts[0]) == 1 and (
            parts[0] in words or parts[0] + "s" in words and parts[0].endswith("s") is False
        )
        if full or first_only:
            found.append(person)
    return found


def landmarks_mentioned(candidates: list, notes: list[str], known: list[str]) -> list[str]:
    """Landmarks from the model's answer that the photographer actually named.

    The model may tidy the spelling ("st nicholas" → "St. Nicholas Church") but must not
    invent a landmark from the image, so at least half of a candidate's words have to
    occur in the photographer's notes. Spelling follows `known` landmarks where one matches.
    """
    note_words = set(re.findall(r"[^\W\d_]+", " ".join(notes).casefold()))
    found: list[str] = []
    for candidate in candidates or []:
        name = normalize_name(str(candidate).strip().strip("."), known)
        words = re.findall(r"[^\W\d_]+", name.casefold())
        if not words or sum(w in note_words for w in words) * 2 < len(words):
            continue
        if name.casefold() not in {f.casefold() for f in found}:
            found.append(name)
    return found


def _place_from_facts(answered: str, notes_text: str, known_places: list[str]) -> str:
    """The place the model derived, accepted only if the facts really name its city.

    Uses the roll's spelling when the city matches one of its places, so "Prague, Czechia"
    does not appear next to "Prague, Czech Republic".
    """
    place = normalize_place(answered, known_places)
    city = place.split(",")[0].strip().casefold()
    if not city or not re.search(r"(?<!\w)" + re.escape(city) + r"(?!\w)", notes_text):
        return ""
    for known in known_places:
        if known.split(",")[0].strip().casefold() == city:
            return known
    return place


def _parse_answer(raw: str) -> dict:
    """Decode a JSON answer and normalise description and category."""
    try:
        answer = json.loads(raw)
        description = " ".join(str(answer["description"]).split())
    except (ValueError, KeyError, TypeError) as e:
        raise RuntimeError(f"model returned an unusable answer: {raw[:120]!r}") from e
    if not description:
        raise RuntimeError("model returned an empty answer (no description)")
    category = str(answer.get("category", "")).strip().lower()
    return {
        **answer,
        "description": description,
        "category": category if category in VALID_CATEGORIES else "other",
    }


# ── Main pipeline ─────────────────────────────────────────────────────────────


def analyze_image(
    path: Path,
    vision_model: str,
    text_model: str,
    roll: dict,
    verbose: bool,
) -> dict:
    """Describe one frame: a single call that returns description, tags and category.

    `text_model` and `roll` are unused here (the text model only writes the roll summary);
    they stay in the signature so callers need not care.
    """
    b64 = _load_image_b64(path)

    answer = None
    problem = ""
    for attempt, (prompt, options) in enumerate(_ANALYZE_ATTEMPTS, 1):
        try:
            raw = _generate(vision_model, prompt, ANALYZE_SYSTEM, options,
                            images=[b64], schema=_ANALYZE_SCHEMA)
            candidate = _parse_answer(raw)
        except RuntimeError as e:
            problem = str(e)
            # An unreachable server or a missing model won't fix itself — fail fast.
            if "empty answer" not in problem and "unusable answer" not in problem:
                raise RuntimeError(f"analysis failed (attempt {attempt}): {e}") from e
            print(f"    [model] {problem} — attempt {attempt}")
            continue
        if _is_repetitive(candidate["description"]):
            problem = "model produced repetitive output"
            print(f"    [model] loop on attempt {attempt}")
            continue
        answer = candidate
        break

    if answer is None:
        # No sidecar is written for a failed frame, so it stays "untagged" and is retried next run.
        raise RuntimeError(
            f"no usable description after {len(_ANALYZE_ATTEMPTS)} attempts ({problem})"
        )

    meta = {
        "category": answer["category"],
        "tags": sanitize_tags(answer.get("tags"), max_words=_MAX_TAG_WORDS),
        "description": answer["description"],
        # The model's own words, kept unchanged when the description is edited later
        "vision_raw": answer["description"],
    }
    if verbose:
        print(f"    [category]    {meta['category']}")
        print(f"    [tags]        {', '.join(meta['tags'])}")
        print(f"    [description] {meta['description']}")
    return meta


# ── Refinement ────────────────────────────────────────────────────────────────


def refine_frame(
    path: Path,
    meta: dict,
    note: str | None,
    model: str,
    known_places: list[str] | None = None,
    known_people: list[str] | None = None,
    known_landmarks: list[str] | None = None,
) -> dict:
    """Rewrite a frame's metadata so it reflects facts stated by the photographer.

    `note` is a new fact ("this is the Parthenon in Athens"); it is added to the
    notes already stored with the frame and all of them are given to the model, so
    facts accumulate. Pass note=None to re-apply the stored notes, e.g. after a re-tag.

    The known_* lists are the roll's locations, subjects and landmarks. A place or
    landmark the facts name is written in the spelling already in use, and anyone from
    the roll's people that the facts mention is marked as being in the frame.
    Returns a new meta dict; raises RuntimeError if the model gives no usable answer.
    """
    notes = list(meta.get("notes") or [])
    if note and note.strip() and note.strip() not in notes:
        notes.append(note.strip())
    if not notes:
        return dict(meta)

    # The roll's people and places are deliberately not shown to the model: given such a
    # list it uses it unasked — everyone ends up in the description, and every frame is
    # "taken in" the roll's city. What the facts mention is decided in code below.
    prompt = REFINE_PROMPT_TMPL.format(
        category=meta.get("category", "other"),
        tags=", ".join(meta.get("tags", [])) or "(none)",
        description=meta.get("description", "") or "(none)",
        notes="\n".join(f"- {n}" for n in notes),
        description_rules=_DESCRIPTION_RULES,
        tag_rules=_TAG_RULES,
        category_rules=_CATEGORY_RULES,
    )
    raw = _generate(model, prompt, REFINE_SYSTEM, _REFINE_OPTS,
                    images=[_load_image_b64(path)], schema=_REFINE_SCHEMA)
    answer = _parse_answer(raw)

    # A model that still writes "Parthenon, Athens, Greece" as the place: split it
    extra_landmark, answered_place = split_place(str(answer.get("place") or ""))
    candidates = [*(answer.get("landmarks") or []), *([extra_landmark] if extra_landmark else [])]
    known = [*(meta.get("landmarks") or []), *(known_landmarks or [])]
    notes_text = " ".join(notes).casefold()
    # Landmarks of the roll that the facts name outright count even if the model, which
    # is unsure whether a river or a square is a "landmark", leaves them out
    named = [k for k in known_landmarks or [] if k.casefold() in notes_text]
    landmarks = list(dict.fromkeys(
        [*(meta.get("landmarks") or []), *named, *landmarks_mentioned(candidates, notes, known)]
    ))
    # The photographer's own choice of place wins over one derived from a note
    place = meta.get("place") or _place_from_facts(answered_place, notes_text, known_places or [])
    people = list(dict.fromkeys(
        [*(meta.get("people") or []), *people_mentioned(" ".join(notes), known_people or [])]
    ))

    names = [*people, *landmarks]
    tags = sanitize_tags(answer.get("tags"), names, place, max_words=_MAX_TAG_WORDS)
    return {
        **meta,
        "description": answer["description"],
        "tags": tags or sanitize_tags(meta.get("tags"), names, place),
        "category": answer["category"],
        "place": place,
        "landmarks": landmarks,
        "people": people,
        "notes": notes,
    }


# ── Roll summary ──────────────────────────────────────────────────────────────


def _generate_roll_prose(all_meta: list, roll: dict, text_model: str) -> str:
    descs = [
        m["description"] for m in all_meta
        if m.get("description") and not m.get("vision_raw", "").startswith("(vision")
    ]
    if not descs:
        return ""
    prompt = ROLL_SUMMARY_PROMPT_TMPL.format(
        location=", ".join(_split_list_field(roll.get("location", ""))) or "not specified",
        subjects=", ".join(_split_list_field(roll.get("subjects", ""))) or "not specified",
        date=roll.get("date", "not specified"),
        descriptions="\n".join(f"- {d}" for d in descs[:40]),
    )
    try:
        return _call_text(text_model, prompt, ROLL_SUMMARY_SYSTEM, _SUMMARY_OPTS)
    except Exception as e:
        print(f"  ✗ roll summary failed: {e}")
        return ""


def write_roll_summary(
    folder: Path, all_meta: list, roll: dict, vision_model: str, text_model: str
) -> None:
    cat_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    for m in all_meta:
        cat = m.get("category", "other")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        for t in m.get("tags", []):
            tag_counts[t] = tag_counts.get(t, 0) + 1

    categories_str = ", ".join(
        f"{cat}: {n}" for cat, n in sorted(cat_counts.items(), key=lambda x: -x[1])
    )
    top_tags_str = ", ".join(
        t for t, _ in sorted(tag_counts.items(), key=lambda x: -x[1])[:12]
    )

    print("Generating roll summary…")
    prose = _generate_roll_prose(all_meta, roll, text_model)

    path = folder / "roll.yaml"
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    idx = content.find(GENERATED_MARKER)
    base = content[:idx].rstrip() + "\n" if idx != -1 else content

    model_line = (
        f'model:      "{vision_model}"\n' if vision_model == text_model
        else f'vision_model: "{vision_model}"\ntext_model:   "{text_model}"\n'
    )
    generated = (
        f"\n{GENERATED_MARKER} ─────────────────────────────────────────────────\n"
        f'processed:  "{datetime.now().strftime("%Y-%m-%d")}"\n'
        + model_line
        + f'frames:     "{len(all_meta)}"\n'
        f'categories: "{categories_str}"\n'
        f'top_tags:   "{top_tags_str}"\n'
    )
    if prose:
        generated += f'summary:    "{prose.replace(chr(34), chr(39))}"\n'

    path.write_text(base + generated, encoding="utf-8")
    print(f"  → roll.yaml updated\n")
