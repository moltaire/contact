#!/usr/bin/env python3
"""
app.py
──────
Streamlit UI for contact — analog film scan tagger.

Run with:
    streamlit run app.py
    streamlit run app.py -- --folder /path/to/roll
"""

import subprocess
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import streamlit.components.v1 as _components
from PIL import Image, ImageOps

from processor.html import write_roll_html
from processor.roll import (
    IMAGE_EXTS,
    KNOWN_CAMERAS,
    KNOWN_FILM_STOCKS,
    _history_sorted,
    _join_list_field,
    _load_history,
    _record,
    _save_history,
    _split_list_field,
    load_roll_yaml,
    write_roll_yaml,
)
from processor.sidecar import _read_xmp_meta, write_xmp
from processor.tagger import VALID_CATEGORIES, analyze_image, write_roll_summary

_roll_label = (st.session_state.get("roll") or {}).get("label", "").strip()
st.set_page_config(
    page_title=f"contact · {_roll_label}" if _roll_label else "contact",
    page_icon="🎞️",
    layout="wide",
)

_VISION_KEYWORDS = {"vision", "llava", "minicpm", "bakllava", "moondream", "cogvlm"}

_CSS = """
<style>
[data-testid="stImage"] { position: relative; }
[data-testid="stImage"] > button {
    position: absolute !important;
    top: 0.4rem !important; right: 0.4rem !important;
    left: auto !important; bottom: auto !important;
}
/* Make tertiary buttons look like muted inline text */
[data-testid="baseButton-tertiary"] {
    color: rgba(128,128,128,0.85) !important;
    font-size: 0.8rem !important;
    padding: 0 2px !important;
    min-height: 0 !important;
}
</style>
"""

_TAB_NAMES = [
    "Select Folder",
    "Roll Info",
    "Frame Analysis",
    "Review & Edit",
]


# ── Helpers ────────────────────────────────────────────────────────────────────


@st.cache_data(ttl=300)
def _get_ollama_models() -> list[str]:
    try:
        r = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=5
        )
        if r.returncode != 0:
            return []
        lines = r.stdout.strip().split("\n")
        return [line.split()[0] for line in lines[1:] if line.split()]
    except Exception:
        return []


def _switch_tab(index: int):
    """Switch the active tab by index via JS. Call after all tab content is rendered."""
    _components.html(
        f"""<script>
        (function() {{
            function go() {{
                var tabs = window.parent.document.querySelectorAll(
                    'button[data-baseweb="tab"], .stTabs button[role="tab"]'
                );
                if (tabs.length > {index}) {{ tabs[{index}].click(); return; }}
                setTimeout(go, 200);
            }}
            go();
        }})();
        </script>""",
        height=0,
    )


def _is_vision_model(name: str) -> bool:
    return any(kw in name.lower() for kw in _VISION_KEYWORDS)


def _thumb(path: Path, size: int = 300) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    img.thumbnail((size, size))
    return img


def _dedup(items: list) -> list:
    seen: set = set()
    out: list = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _step_desc(text: str, mt: str = "1.2rem"):
    """Step description with consistent vertical rhythm."""
    st.markdown(
        f"<p style='color:rgba(128,128,128,0.85); font-size:0.875rem; "
        f"margin:{mt} 0 0.25rem 0'>{text}</p>",
        unsafe_allow_html=True,
    )


def _page_header(
    desc: str, btn_label: str, btn_disabled: bool = False, help: str | None = None
) -> bool:
    """Description left + primary button right (1/4 width). Returns True if clicked."""
    desc_col, btn_col = st.columns([3, 1])
    with desc_col:
        _step_desc(desc, mt="0.5rem")
    with btn_col:
        clicked = st.button(
            btn_label,
            type="primary",
            use_container_width=True,
            disabled=btn_disabled,
            help=help,
        )
    return clicked


def _render_title():
    folder = st.session_state.get("folder")
    roll = st.session_state.get("roll", {})
    label = (roll.get("label", "") if roll else "").strip()
    if folder is None:
        st.markdown("# contact")
        return
    home = Path.home()
    try:
        display_path = "~/" + str(folder.relative_to(home))
    except ValueError:
        display_path = str(folder)
    subtitle = label if label else display_path
    st.markdown(
        f"<h1 style='margin-bottom:0'>contact "
        f"<span style='color:#888; font-weight:400'>· {subtitle}</span>"
        f"</h1>",
        unsafe_allow_html=True,
    )


def _pick_folder_dialog() -> str:
    """Open a native folder picker. Returns path string or empty string."""
    import platform

    try:
        if platform.system() == "Darwin":
            r = subprocess.run(
                [
                    "osascript",
                    "-e",
                    'POSIX path of (choose folder with prompt "Select roll folder")',
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            return r.stdout.strip() if r.returncode == 0 else ""
        else:
            r = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import tkinter; from tkinter import filedialog; "
                    "root = tkinter.Tk(); root.withdraw(); "
                    "root.wm_attributes('-topmost', True); "
                    "print(filedialog.askdirectory(), end=''); root.destroy()",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _init_state():
    defaults: dict = {
        "folder": None,
        "roll": {},
        "images": [],
        "vision_model": "llama3.2-vision:11b",
        "text_model": "llama3.2-vision:11b",
        "folder_input_initialized": False,
        "review_idx": 0,
        "next_tab": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _cli_folder() -> str:
    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg == "--folder" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--folder="):
            return arg[len("--folder=") :]
    return ""


def _clear_folder_state():
    for key in [
        "film_sel",
        "cam_sel",
        "lab_sel",
        "ms_lens",
        "ms_location",
        "ms_subjects",
        "label_input",
        "date_input",
        "lab_notes_input",
        "notes_input",
        "selected_images",
    ]:
        st.session_state.pop(key, None)
    for key in [
        k
        for k in list(st.session_state.keys())
        if k.startswith(("rev_", "sel_", "confirm_"))
    ]:
        del st.session_state[key]
    st.session_state.review_idx = 0


def _html_pairs(folder: Path) -> list:
    return [
        (img, _read_xmp_meta(img.with_suffix(".xmp")))
        for img in sorted(
            f
            for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS
        )
        if img.with_suffix(".xmp").exists()
    ]


# ── Step renderers ─────────────────────────────────────────────────────────────


def _render_folder():
    continue_clicked = _page_header(
        "Choose a folder containing your scanned film images.",
        "Continue to Roll Info",
        btn_disabled=st.session_state.folder is None,
    )

    browse_col, input_col = st.columns([0.9, 4], gap="small")
    with browse_col:
        if st.button("Choose folder…", use_container_width=True):
            picked = _pick_folder_dialog()
            if picked:
                st.session_state["folder_input"] = picked
                st.rerun()
    with input_col:
        folder_val: str = st.text_input(
            "folder",
            key="folder_input",
            placeholder="/path/to/scans/roll_01",
            label_visibility="collapsed",
        )

    folder = st.session_state.folder
    if folder_val:
        fp = Path(folder_val).expanduser().resolve()
        if fp.is_dir():
            new_images = sorted(
                f
                for f in fp.iterdir()
                if f.is_file() and f.suffix.lower() in IMAGE_EXTS
            )
            new_roll = load_roll_yaml(fp) if (fp / "roll.yaml").exists() else {}
            n_tagged_new = sum(
                1 for img in new_images if img.with_suffix(".xmp").exists()
            )

            if folder != fp:
                _clear_folder_state()
                st.session_state.folder = fp
                st.session_state.roll = new_roll
                st.session_state.images = new_images
                st.rerun()

            parts = [f"{len(new_images)} image{'s' if len(new_images) != 1 else ''}"]
            if n_tagged_new:
                parts.append(f"{n_tagged_new} tagged")
            parts.append("roll.yaml found" if new_roll else "no roll.yaml")
            st.caption("✓ " + " · ".join(parts))

            if new_images:
                grid_cols = st.columns(4)
                for i, img in enumerate(new_images):
                    with grid_cols[i % 4]:
                        tagged = img.with_suffix(".xmp").exists()
                        try:
                            st.image(_thumb(img), width="stretch")
                        except Exception:
                            pass
                        st.caption(("✓ " if tagged else "") + img.name)
        else:
            st.error("Folder not found.")

    if continue_clicked:
        st.session_state.next_tab = 1
        st.rerun()


def _render_roll():
    folder = st.session_state.folder
    if folder is None:
        st.info("Select a folder first.")
        return

    roll = st.session_state.roll
    images = st.session_state.images
    history = _load_history()

    save_clicked = _page_header(
        "Enter roll metadata like film stock, camera, date, location, etc.",
        "Save and continue",
    )

    form_col, img_col = st.columns([2, 1], gap="large")

    with form_col:
        label = st.text_input(
            "Label",
            value=roll.get("label", ""),
            placeholder="e.g. Oslo Summer 2024",
            key="label_input",
        )

        current_film = roll.get("film", "")
        film_hist = _history_sorted(history, "film")
        film_opts = _dedup(
            ([current_film] if current_film else []) + film_hist + KNOWN_FILM_STOCKS
        )
        film = st.selectbox(
            "Film stock",
            film_opts,
            index=(
                film_opts.index(current_film) if current_film in film_opts else None
            ),
            accept_new_options=True,
            key="film_sel",
            placeholder="Select or type a film stock…",
        )

        current_cam = roll.get("camera", "")
        cam_hist = _history_sorted(history, "camera")
        cam_opts = _dedup(
            ([current_cam] if current_cam else []) + cam_hist + KNOWN_CAMERAS
        )
        camera = st.selectbox(
            "Camera",
            cam_opts,
            index=cam_opts.index(current_cam) if current_cam in cam_opts else None,
            accept_new_options=True,
            key="cam_sel",
            placeholder="Select or type a camera…",
        )

        current_lens = _split_list_field(roll.get("lens", ""))
        lens_opts = _dedup(current_lens + _history_sorted(history, "lens"))
        lens_sel = st.multiselect(
            "Lens",
            options=lens_opts,
            default=current_lens,
            accept_new_options=True,
            key="ms_lens",
        )

        date = st.text_input(
            "Date",
            value=roll.get("date", ""),
            placeholder="YYYY-MM or YYYY-MM-DD",
            key="date_input",
        )

        current_location = _split_list_field(roll.get("location", ""))
        loc_opts = _dedup(current_location + _history_sorted(history, "location"))
        location_sel = st.multiselect(
            "Location",
            options=loc_opts,
            default=current_location,
            accept_new_options=True,
            key="ms_location",
        )

        current_subjects = _split_list_field(roll.get("subjects", ""))
        subj_opts = _dedup(current_subjects + _history_sorted(history, "subjects"))
        subjects_sel = st.multiselect(
            "Subjects",
            options=subj_opts,
            default=current_subjects,
            accept_new_options=True,
            key="ms_subjects",
        )

        current_lab = roll.get("lab", "")
        lab_opts = _dedup(
            ([current_lab] if current_lab else []) + _history_sorted(history, "lab")
        )
        lab = st.selectbox(
            "Lab",
            lab_opts,
            index=lab_opts.index(current_lab) if current_lab in lab_opts else None,
            accept_new_options=True,
            key="lab_sel",
            placeholder="Select or type a lab…",
        )

        lab_notes = st.text_input(
            "Lab notes",
            value=roll.get("lab_notes", ""),
            placeholder="e.g. push 1 stop",
            key="lab_notes_input",
        )
        notes = st.text_input("Notes", value=roll.get("notes", ""), key="notes_input")

    with img_col:
        st.space("small")
        if images:
            grid_cols = st.columns(2)
            for i, img in enumerate(images):
                with grid_cols[i % 2]:
                    try:
                        st.image(_thumb(img, 150), width="stretch")
                    except Exception:
                        pass
                    st.caption(img.name)

    if save_clicked:
        lens = _join_list_field(lens_sel)
        location = _join_list_field(location_sel)
        subjects = _join_list_field(subjects_sel)
        data = {
            "film": film or "",
            "camera": camera or "",
            "lens": lens,
            "date": date,
            "location": location,
            "subjects": subjects,
            "lab": lab or "",
            "lab_notes": lab_notes,
            "notes": notes,
            "label": label,
        }
        write_roll_yaml(folder, data)
        _record(history, "film", film or "")
        _record(history, "camera", camera or "")
        for item in _split_list_field(lens):
            _record(history, "lens", item)
        for item in _split_list_field(location):
            _record(history, "location", item)
        for item in _split_list_field(subjects):
            _record(history, "subjects", item)
        _record(history, "lab", lab or "")
        _record(history, "lab_notes", lab_notes)
        _save_history(history)
        st.session_state.roll = load_roll_yaml(folder)
        st.session_state.next_tab = 2
        st.rerun()


def _render_images():
    folder = st.session_state.folder
    if folder is None:
        st.info("Select a folder first.")
        return

    images = st.session_state.images
    roll = st.session_state.roll

    if not images:
        st.info("No images found in this folder.")
        return

    if "selected_images" not in st.session_state:
        st.session_state.selected_images = {img.name for img in images}

    tag_untagged = _page_header(
        "Analyze each image with a local vision model and write a description, "
        "category, and tag metadata. Select images to include, then tag.",
        "Tag untagged",
        help="AI-tag images that don't have metadata yet.",
    )

    # ── Re-tag row ─────────────────────────────────────────────────────────────
    left, retag_col, rem_col = st.columns([3, 0.5, 0.5])
    with retag_col:
        retag_selected = st.button(
            "Re-tag selected",
            use_container_width=True,
            help="Force AI re-tagging on all checked images.",
            type="tertiary",
        )
    with rem_col:
        remove_tags = st.button(
            "Un-tag selected",
            use_container_width=True,
            help="Delete sidecar metadata from selected images.",
            type="tertiary",
        )

    with left:
        # ── Model settings ────────────────────────────────────────────────────────
        with st.popover("Advanced"):
            st.caption(
                "contact uses two [ollama](https://ollama.com) models: a **vision model** that "
                "looks at each image and writes a description, and a **text model** that "
                "synthesizes the roll summary. Both must be installed locally with ollama. "
                "Good vision models: `llama3.2-vision`, `moondream`, `llava`. "
                "For the text model, any instruction-following model works (e.g. `llama3.2`, `mistral`). "
                "Install with: `ollama pull llama3.2-vision:11b`"
            )
            all_models = _get_ollama_models()
            vision_models = [m for m in all_models if _is_vision_model(m)]
            text_models = all_models
            col1, col2 = st.columns(2)
            with col1:
                if vision_models:
                    vm_idx = (
                        vision_models.index(st.session_state.vision_model)
                        if st.session_state.vision_model in vision_models
                        else 0
                    )
                    st.selectbox(
                        "Vision model", vision_models, index=vm_idx, key="vision_model"
                    )
                else:
                    st.text_input("Vision model", key="vision_model")
            with col2:
                if text_models:
                    tm_idx = (
                        text_models.index(st.session_state.text_model)
                        if st.session_state.text_model in text_models
                        else 0
                    )
                    st.selectbox(
                        "Text model", text_models, index=tm_idx, key="text_model"
                    )
                else:
                    st.text_input("Text model", key="text_model")

    # ── Remove tags ────────────────────────────────────────────────────────────
    if remove_tags:
        selected = [
            img for img in images if img.name in st.session_state.selected_images
        ]
        for img in selected:
            xmp = img.with_suffix(".xmp")
            if xmp.exists():
                xmp.unlink()
        for key in [
            k
            for k in list(st.session_state.keys())
            if k.startswith(("rev_", "confirm_"))
        ]:
            del st.session_state[key]
        st.session_state.review_idx = 0
        pairs = _html_pairs(folder)
        if pairs:
            write_roll_html(folder, pairs, roll)
        st.rerun()

    # ── AI processing — runs BEFORE grid so progress appears above images ─────
    if tag_untagged or retag_selected:
        selected_images = [
            img for img in images if img.name in st.session_state.selected_images
        ]
        to_process = (
            selected_images
            if retag_selected
            else [
                img for img in selected_images if not img.with_suffix(".xmp").exists()
            ]
        )
        if not to_process:
            if tag_untagged:
                # All selected already tagged — silently advance to Review & Edit
                st.session_state.next_tab = 3
                st.rerun()
            else:
                st.info("Select at least one image.")
        else:
            n = len(to_process)
            prog = st.progress(0, text=f"Starting… (0 / {n})")
            all_meta: list = []

            for i, img in enumerate(to_process):
                prog.progress(i / n, text=f"Tagging {img.name}  ({i + 1} / {n})")
                try:
                    meta = analyze_image(
                        img,
                        st.session_state.vision_model,
                        st.session_state.text_model,
                        roll,
                        verbose=True,
                    )
                    write_xmp(img, meta, roll)
                    all_meta.append(meta)
                except Exception as e:
                    st.error(f"{img.name}: {e}")

            prog.progress(1.0, text="Finalizing…")
            if all_meta:
                write_roll_summary(
                    folder,
                    all_meta,
                    roll,
                    st.session_state.vision_model,
                    st.session_state.text_model,
                )
            pairs = _html_pairs(folder)
            if pairs:
                write_roll_html(folder, pairs, roll)
            prog.empty()

            for key in [
                k
                for k in list(st.session_state.keys())
                if k.startswith(("rev_", "confirm_"))
            ]:
                del st.session_state[key]
            st.session_state.review_idx = 0
            st.session_state.next_tab = 3
            st.rerun()

    # ── Image grid ────────────────────────────────────────────────────────────
    grid_cols = st.columns(4)
    for i, img in enumerate(images):
        with grid_cols[i % 4]:
            tagged = img.with_suffix(".xmp").exists()
            try:
                st.image(_thumb(img), width="stretch")
            except Exception:
                pass
            checked = st.checkbox(
                img.name + (" · tagged ✓" if tagged else ""),
                key=f"sel_{img.name}",
                value=img.name in st.session_state.selected_images,
            )
            if checked:
                st.session_state.selected_images.add(img.name)
            else:
                st.session_state.selected_images.discard(img.name)


def _render_metadata():
    folder = st.session_state.folder
    if folder is None:
        st.info("Select a folder first.")
        return

    images = st.session_state.images
    tagged_images = [img for img in images if img.with_suffix(".xmp").exists()]
    roll = st.session_state.roll

    if not tagged_images:
        st.info("No tagged images yet. Tag images in the Frame Analysis step first.")
        return

    for img in tagged_images:
        if f"rev_cat_{img.name}" not in st.session_state:
            meta = _read_xmp_meta(img.with_suffix(".xmp"))
            st.session_state[f"rev_cat_{img.name}"] = meta.get("category", "other")
            st.session_state[f"rev_desc_{img.name}"] = meta.get("description", "")
            st.session_state[f"rev_tags_{img.name}"] = meta.get("tags", [])

    all_known_tags = sorted(
        {
            tag
            for img in tagged_images
            for tag in st.session_state.get(f"rev_tags_{img.name}", [])
        }
    )

    n = len(tagged_images)
    review_idx = st.session_state.review_idx

    desc_col, build_col = st.columns([3, 1])
    with desc_col:
        _step_desc(
            "Review and edit the AI-generated metadata for each image. ",
            mt="0.5rem",
        )
    with build_col:
        build_clicked = st.button(
            "Save and make contact",
            type="primary",
            use_container_width=True,
            disabled=not tagged_images,
            help="Save all edits and open the contact sheet in the browser.",
        )

    index_path = folder / "index.html"

    if build_clicked:
        for img in tagged_images:
            write_xmp(
                img,
                {
                    "category": st.session_state[f"rev_cat_{img.name}"],
                    "description": st.session_state[f"rev_desc_{img.name}"],
                    "tags": list(st.session_state[f"rev_tags_{img.name}"]),
                },
                roll,
            )
        pairs = _html_pairs(folder)
        if pairs:
            write_roll_html(folder, pairs, roll)
            webbrowser.open(index_path.as_uri())
            st.success(f"Contact sheet created: `{index_path}`")

    sorted_cats = sorted(VALID_CATEGORIES)
    for i, img in enumerate(tagged_images):
        with st.expander(img.name, expanded=(i == review_idx)):
            c1, c2 = st.columns([1, 2])
            with c1:
                try:
                    st.image(_thumb(img, 800), width="stretch")
                except Exception:
                    pass
            with c2:
                st.selectbox("Category", sorted_cats, key=f"rev_cat_{img.name}")

                desc_text = st.session_state.get(f"rev_desc_{img.name}", "")
                desc_lines = max(4, len(desc_text) // 55 + desc_text.count("\n") + 1)
                st.text_area(
                    "Description",
                    key=f"rev_desc_{img.name}",
                    height=desc_lines * 22,
                )

                st.multiselect(
                    "Tags",
                    options=all_known_tags,
                    accept_new_options=True,
                    key=f"rev_tags_{img.name}",
                )

                prev_col, next_col = st.columns(2)
                with prev_col:
                    if st.button(
                        "← Previous",
                        key=f"prev_{img.name}",
                        disabled=(i == 0),
                        use_container_width=True,
                    ):
                        st.session_state.review_idx = i - 1
                        st.rerun()
                with next_col:
                    if st.button(
                        "Next →",
                        key=f"next_{img.name}",
                        disabled=(i == n - 1),
                        use_container_width=True,
                    ):
                        st.session_state.review_idx = i + 1
                        st.rerun()


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    _init_state()
    st.markdown(_CSS, unsafe_allow_html=True)

    if not st.session_state.folder_input_initialized:
        st.session_state.folder_input_initialized = True
        cli_f = _cli_folder()
        if cli_f:
            st.session_state["folder_input"] = cli_f

    _render_title()

    tab1, tab2, tab3, tab4 = st.tabs(_TAB_NAMES)
    with tab1:
        _render_folder()
    with tab2:
        _render_roll()
    with tab3:
        _render_images()
    with tab4:
        _render_metadata()

    # Fire tab switch after all content is rendered, then clear the flag
    if st.session_state.next_tab is not None:
        _switch_tab(st.session_state.next_tab)
        st.session_state.next_tab = None


if __name__ == "__main__":
    main()
