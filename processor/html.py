"""
processor/html.py
─────────────────
The HTML contact sheet: one self-contained index.html per roll, next to the scans.

It looks like the roll's page in the app (same colours, type and layout: the roll's
facts, notes and foldable summary, then the frames) and keeps what makes a contact
sheet handy on its own: search across the frames, favourites pinned on top, and a
lightbox laid out like the app's frame view. Dark by default; the sun/moon in the
corner switches, and the browser remembers it.
"""

from pathlib import Path

from .roll import _split_list_field, load_roll_yaml
from .sidecar import _xe

# The app's palette (contact_gui/theme.py), repeated here so the sheet needs nothing
# from the app. Keep the two in step.
_ORANGE = "#f5961d"
_ORANGE_DEEP = "#b85e00"


def _version(path: Path) -> str:
    """Changes whenever the file does (an edit, a rotation), so browsers fetch it anew."""
    try:
        stat = path.stat()
    except OSError:
        return "0"
    return f"{int(stat.st_mtime)}-{stat.st_size}"


def write_roll_html(folder: Path, pairs: list, roll: dict) -> None:
    """pairs: [(image_path, meta), ...]. Reloads roll.yaml to pick up the generated summary."""
    info = load_roll_yaml(folder)

    def listed(key: str) -> str:
        return ", ".join(_split_list_field(info.get(key, "")))

    locations = _split_list_field(info.get("location", ""))
    title = info.get("label", "").strip() or " — ".join(
        p for p in [locations[0] if locations else "", info.get("date", "")] if p
    ) or folder.name

    starred = sum(1 for _, meta in pairs if meta.get("starred"))
    counts = [info.get("date", ""), f"{len(pairs)} frame{'s' if len(pairs) != 1 else ''}"]
    if starred:
        counts.append(f"{starred} favourite{'s' if starred != 1 else ''}")
    counts_html = _xe(" · ".join(c for c in counts if c))

    # Facts in two columns, as on the roll page: the gear left, where and who right
    left = [("film", info.get("film", "")), ("camera", info.get("camera", "")),
            ("lenses", listed("lens")), ("lab", info.get("lab", "")),
            ("lab notes", info.get("lab_notes", ""))]
    right = [("location", listed("location")), ("people", listed("subjects")),
             ("landmarks", listed("landmarks"))]

    def column(rows) -> str:
        return "".join(f'<div class="fact"><span class="key">{_xe(k)}</span>'
                       f'<span>{_xe(v)}</span></div>' for k, v in rows if v)

    facts_html = ""
    if any(v for _, v in left + right):
        facts_html = (f'<div class="facts"><div class="facts-col">{column(left)}</div>'
                      f'<div class="facts-col">{column(right)}</div></div>')
    notes = info.get("notes", "").strip()
    notes_html = f'<p class="notes">{_xe(notes)}</p>' if notes else ""
    summary = info.get("summary", "").strip()
    summary_html = ""
    if summary:
        summary_html = (
            '<div class="summary-block">'
            '<button class="summary-toggle" id="summary-toggle" aria-expanded="true">'
            '<span class="chev">&#8250;</span>summary</button>'
            f'<p class="summary" id="summary">{_xe(summary)}</p></div>'
        )

    cards = []
    for img_path, meta in pairs:
        place = meta.get("place", "") or (locations[0] if len(locations) == 1 else "")
        people, landmarks = meta.get("people", []), meta.get("landmarks", [])
        tags = meta.get("tags", [])
        search = " ".join([img_path.name, meta.get("description", ""),
                           meta.get("category", ""), *people, *landmarks, place, *tags])
        src = f"{img_path.name}?v={_version(img_path)}"
        star_attr = ' data-starred="1"' if meta.get("starred") else ""
        cards.append(
            f'<figure class="card" data-img="{_xe(img_path.name)}" data-src="{_xe(src)}"'
            f' data-search="{_xe(search.lower())}"'
            f' data-description="{_xe(meta.get("description", ""))}"'
            f' data-category="{_xe(meta.get("category", ""))}"'
            f' data-people="{_xe(" | ".join(people))}"'
            f' data-landmarks="{_xe(" | ".join(landmarks))}"'
            f' data-place="{_xe(place)}"'
            f' data-tags="{_xe(" | ".join(tags))}"'
            f'{star_attr}>'
            f'<div class="frame"><img src="{_xe(src)}" alt="" loading="lazy">'
            '<button class="star-btn" aria-label="Favourite">&#9734;</button></div>'
            f'<figcaption>{_xe(img_path.name)}</figcaption></figure>'
        )

    html = (
        "<!DOCTYPE html>\n"
        '<html lang="en" data-theme="dark">\n<head>\n<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_xe(title)}</title>\n"
        # set the remembered theme before anything is drawn, so a light page never
        # flashes dark
        "<script>try{var t=localStorage.getItem('contact-theme');"
        "if(t)document.documentElement.dataset.theme=t}catch(e){}</script>\n"
        f"<style>\n{_CSS}</style>\n</head>\n<body>\n"
        '<header class="top"><span class="wordmark">contact</span>'
        f'<span class="crumb">{_xe(title)}</span><span class="grow"></span>'
        '<button id="theme" class="icon-btn" aria-label="Switch theme"></button></header>\n'
        '<main>\n<section class="about">'
        f'<div class="title-row"><h1>{_xe(title)}</h1>'
        f'<span class="counts">{counts_html}</span></div>'
        f"{facts_html}{notes_html}{summary_html}</section>\n"
        '<div class="search-row"><input type="search" id="search" '
        'placeholder="Search these frames" autocomplete="off">'
        '<span class="hits" id="hits"></span></div>\n'
        '<p id="no-results" class="no-results" hidden>No frames match.</p>\n'
        '<section id="starred-section" hidden><div class="section-label">favourites</div>'
        '<div id="starred-grid" class="grid"></div></section>\n'
        '<div id="main-grid" class="grid">\n' + "".join(cards) + "\n</div>\n</main>\n"
        + _LIGHTBOX + _JS + "\n</body>\n</html>"
    )
    (folder / "index.html").write_text(html, encoding="utf-8")
    print("  → index.html")


_CSS = f"""\
:root, [data-theme="dark"] {{
  --page: #161616; --top: #0e0e0e; --panel: #1e1e1e; --edge: #333333; --text: #f1f0ec;
  --muted: #a9a8a3; --accent: {_ORANGE}; --on-accent: #141414; --stage: #0a0a0a;
}}
[data-theme="light"] {{
  --page: #ecebe8; --top: #f7f6f3; --panel: #ffffff; --edge: #d5d4cf; --text: #161616;
  --muted: #6b6a66; --accent: {_ORANGE_DEEP}; --on-accent: #ffffff; --stage: #dcdbd7;
}}
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif; background: var(--page);
  color: var(--text); -webkit-font-smoothing: antialiased;
}}
.mono, .key, .counts, figcaption, .crumb, .summary-toggle, .section-label, .hits,
.lb-counter, .sheet-row {{
  font-family: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
}}
button {{ font: inherit; color: inherit; background: none; border: none; cursor: pointer; }}

/* The app's header: wordmark with its orange dot, the roll as the crumb */
.top {{
  display: flex; align-items: center; gap: 14px; padding: 10px 32px; background: var(--top);
  border-bottom: 1px solid var(--edge); position: sticky; top: 0; z-index: 5;
}}
.wordmark {{
  font-family: ui-monospace, "SF Mono", Menlo, monospace; font-weight: 700;
  letter-spacing: .08em; font-size: 1.25rem;
}}
.wordmark::after {{
  content: ""; display: inline-block; width: .5em; height: .5em; margin-left: .35em;
  border-radius: 50%; background: {_ORANGE}; vertical-align: middle; position: relative;
  top: -.04em;
}}
.crumb {{ color: var(--muted); font-size: 1.05rem; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }}
.grow {{ flex: 1; }}
.icon-btn {{ width: 32px; height: 32px; border-radius: 50%; color: var(--muted);
  display: inline-flex; align-items: center; justify-content: center; }}
.icon-btn:hover {{ color: var(--accent); }}
.icon-btn svg {{ width: 20px; height: 20px; }}

main {{ padding: 28px 32px 48px; }}
.about {{ max-width: 62rem; }}
.title-row {{ display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }}
h1 {{ font-size: 1.5rem; font-weight: 600; }}
.counts {{ font-size: .8rem; color: var(--muted); }}
.facts {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 40px;
  margin-top: 16px; max-width: 52rem; }}
.facts-col {{ display: flex; flex-direction: column; gap: 4px; min-width: 0; }}
.fact {{ display: grid; grid-template-columns: 6rem minmax(0, 1fr); font-size: .88rem;
  line-height: 1.45; }}
.key {{ font-size: .75rem; letter-spacing: .04em; color: var(--muted); padding-top: 1px; }}
.notes {{ max-width: 46rem; line-height: 1.55; font-size: .92rem; margin-top: 16px;
  white-space: pre-line; }}
.summary-block {{ margin-top: 14px; max-width: 46rem; }}
.summary-toggle {{ font-size: .75rem; letter-spacing: .04em; color: var(--muted);
  display: inline-flex; align-items: center; gap: 6px; }}
.summary-toggle:hover {{ color: var(--accent); }}
.chev {{ display: inline-block; transition: transform .15s ease; font-size: 1rem; line-height: 1; }}
.summary-toggle[aria-expanded="true"] .chev {{ transform: rotate(90deg); }}
.summary {{ line-height: 1.55; font-size: .88rem; color: var(--muted); margin-top: 4px; }}

/* Search, as in the app's library */
.search-row {{ display: flex; align-items: center; gap: 14px; margin: 24px 0 18px; }}
#search {{
  flex: 1; font: inherit; font-size: .9rem; padding: 9px 12px; border-radius: 3px;
  border: 1px solid var(--edge); background: var(--panel); color: var(--text);
}}
#search:focus {{ outline: none; border-color: var(--accent); }}
.hits {{ font-size: .75rem; color: var(--muted); white-space: nowrap; }}
.no-results {{ color: var(--muted); font-size: .88rem; margin-bottom: 16px; }}
.section-label {{ font-size: .75rem; letter-spacing: .04em; color: var(--muted);
  margin-bottom: 8px; }}
#starred-section {{ margin-bottom: 22px; padding-bottom: 18px;
  border-bottom: 1px solid var(--edge); }}

/* Frames, as on the roll page */
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }}
.card {{ min-width: 0; }}
.frame {{ position: relative; }}
.frame img {{
  width: 100%; aspect-ratio: 3 / 2; object-fit: cover; display: block; cursor: zoom-in;
  background: #0a0a0a; border-radius: 2px;
}}
.frame img:hover {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
figcaption {{ font-size: .68rem; color: var(--muted); margin-top: 3px; }}
.star-btn {{
  position: absolute; top: 3px; right: 5px; color: #fff; font-size: 1rem; line-height: 1;
  text-shadow: 0 0 3px #000; opacity: 0; transition: opacity .15s;
}}
.card:hover .star-btn {{ opacity: .85; }}
.card.starred .star-btn {{ opacity: 1; color: {_ORANGE}; }}

/* Lightbox: the app's frame view */
#lightbox {{ position: fixed; inset: 0; z-index: 10; background: var(--page); display: none;
  flex-direction: column; }}
#lightbox.open {{ display: flex; }}
.lb-top {{ display: flex; align-items: center; gap: 12px; padding: 10px 24px;
  border-bottom: 1px solid var(--edge); }}
.lb-title {{ font-weight: 600; font-size: .9rem; display: inline-flex; align-items: center; gap: 8px; }}
.lb-title:hover {{ color: var(--accent); }}
.lb-counter {{ font-size: .75rem; color: var(--muted); }}
#lb-star.on {{ color: {_ORANGE}; }}
.lb-main {{ flex: 1; min-height: 0; display: flex; gap: 32px; padding: 28px 32px 24px; }}
.lb-stage {{ flex: 1; min-width: 0; background: var(--stage); border-radius: 2px;
  display: flex; align-items: center; justify-content: center; position: relative; }}
#lb-img {{ max-width: 100%; max-height: 100%; object-fit: contain; display: block; }}
.lb-side {{ width: 400px; flex: none; display: flex; flex-direction: column; gap: 12px;
  overflow-y: auto; }}
.lb-desc {{ border: 1px solid var(--edge); border-radius: 3px; background: var(--panel);
  padding: 4px 11px 8px; font-size: 14px; line-height: 1.5; }}
.lb-desc .label {{ font-size: 12px; color: var(--muted); margin: 5px 0 1px; }}
.lb-side .grow {{ flex: 1; }}
.sheet-row {{ display: grid; grid-template-columns: 5.5rem minmax(0, 1fr); gap: 12px;
  border-top: 1px solid var(--edge); padding: 4px 2px; font-size: .82rem; line-height: 1.5rem; }}
.sheet-row .key {{ font-size: .72rem; letter-spacing: .06em; line-height: 1.5rem; }}
.sheet-row .empty {{ color: var(--muted); }}

@media (max-width: 800px) {{
  .top, main {{ padding-left: 16px; padding-right: 16px; }}
  .facts {{ grid-template-columns: 1fr; }}
  .grid {{ grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }}
  .lb-main {{ flex-direction: column; padding: 12px; gap: 12px; }}
  .lb-side {{ width: auto; max-height: 40vh; }}
}}
"""

_LIGHTBOX = """\
<div id="lightbox" role="dialog" aria-modal="true">
<div class="lb-top">
<button class="lb-title" id="lb-close-title"><span aria-hidden="true">&#8592;</span><span id="lb-roll"></span></button>
<span class="lb-counter" id="lb-counter"></span><span class="grow"></span>
<button class="icon-btn" id="lb-star" aria-label="Favourite (S)">&#9734;</button>
<button class="icon-btn" id="lb-close" aria-label="Close (Esc)">&#215;</button>
</div>
<div class="lb-main">
<div class="lb-stage"><img id="lb-img" alt=""></div>
<div class="lb-side">
<div class="lb-desc"><div class="label">Description</div><div id="lb-desc"></div></div>
<div class="grow"></div>
<div id="lb-sheet"></div>
</div>
</div>
</div>
"""

_JS = """\
<script>
(function () {
  var root = document.documentElement;
  var SUN = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM2 13h2a1 1 0 0 0 0-2H2a1 1 0 0 0 0 2zm18 0h2a1 1 0 0 0 0-2h-2a1 1 0 0 0 0 2zM11 2v2a1 1 0 0 0 2 0V2a1 1 0 0 0-2 0zm0 18v2a1 1 0 0 0 2 0v-2a1 1 0 0 0-2 0zM5.99 4.58a1 1 0 0 0-1.41 1.41l1.06 1.06a1 1 0 0 0 1.41-1.41L5.99 4.58zm12.37 12.37a1 1 0 0 0-1.41 1.41l1.06 1.06a1 1 0 0 0 1.41-1.41l-1.06-1.06zm1.06-10.96a1 1 0 0 0-1.41-1.41l-1.06 1.06a1 1 0 0 0 1.41 1.41l1.06-1.06zM7.05 18.36a1 1 0 0 0-1.41-1.41l-1.06 1.06a1 1 0 0 0 1.41 1.41l1.06-1.06z"/></svg>';
  var MOON = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.1-1.36a5.39 5.39 0 0 1-4.4 2.26 5.4 5.4 0 0 1-3.14-9.8c-.44-.06-.9-.1-1.36-.1z"/></svg>';

  // ── Theme: dark by default, remembered by the browser ─────────────────────
  var themeBtn = document.getElementById('theme');
  function showTheme() {
    var dark = root.dataset.theme !== 'light';
    themeBtn.innerHTML = dark ? SUN : MOON;  // the button offers the other theme
    themeBtn.title = dark ? 'Light theme' : 'Dark theme';
  }
  themeBtn.addEventListener('click', function () {
    root.dataset.theme = root.dataset.theme === 'light' ? 'dark' : 'light';
    try { localStorage.setItem('contact-theme', root.dataset.theme); } catch (e) {}
    showTheme();
  });
  showTheme();

  // ── Summary: folded or not, remembered ───────────────────────────────────
  var summaryToggle = document.getElementById('summary-toggle');
  if (summaryToggle) {
    var summary = document.getElementById('summary');
    var setSummary = function (open) {
      summary.hidden = !open;
      summaryToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    };
    setSummary(localStorage.getItem('contact-summary') !== 'closed');
    summaryToggle.addEventListener('click', function () {
      var open = summary.hidden;
      setSummary(open);
      try { localStorage.setItem('contact-summary', open ? 'open' : 'closed'); } catch (e) {}
    });
  }

  // ── Search: every word must match; case and accents don't matter ─────────
  var fold = function (s) {
    return s.normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase();
  };
  var searchEl = document.getElementById('search');
  var hitsEl = document.getElementById('hits');
  var noRes = document.getElementById('no-results');
  var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
  cards.forEach(function (c) { c._search = fold(c.dataset.search); });
  function search() {
    var words = fold(searchEl.value).split(/\\s+/).filter(Boolean);
    var visible = 0;
    cards.forEach(function (c) {
      var show = words.every(function (w) { return c._search.indexOf(w) !== -1; });
      c.hidden = !show;
      if (show) visible++;
    });
    hitsEl.textContent = words.length ? visible + ' of ' + cards.length : cards.length + ' frames';
    noRes.hidden = !(words.length && visible === 0);
    updateSections();
  }
  searchEl.addEventListener('input', search);

  // ── Favourites, pinned on top ──────────────────────────────────────────────
  // Baked into this page from the sidecars (data-starred). Opened through the app, a
  // click is saved back to the sidecar; opened as a plain file there is nowhere to
  // save to, so this browser remembers it on top of what the page was built with.
  var LEGACY_KEY = 'film-stars:' + location.pathname;
  var LOCAL_KEY = 'contact-stars:' + location.pathname;
  var legacy = JSON.parse(localStorage.getItem(LEGACY_KEY) || '[]');
  var local = JSON.parse(localStorage.getItem(LOCAL_KEY) || '{}');
  var starredGrid = document.getElementById('starred-grid');
  var mainGrid = document.getElementById('main-grid');
  var starredSection = document.getElementById('starred-section');
  function isStarred(card) {
    var name = card.dataset.img;
    if (Object.prototype.hasOwnProperty.call(local, name)) return local[name];
    return card.dataset.starred === '1' || legacy.indexOf(name) !== -1;
  }
  function updateSections() {
    starredSection.hidden = !Array.prototype.some.call(starredGrid.children,
      function (c) { return !c.hidden; });
  }
  function applyStars() {
    cards.forEach(function (card) {
      var on = isStarred(card);
      card.classList.toggle('starred', on);
      card.querySelector('.star-btn').innerHTML = on ? '&#9733;' : '&#9734;';
      (on ? starredGrid : mainGrid).appendChild(card);
    });
    updateSections();
    if (lbCard) showLbStar();
  }
  function toggleStar(card) {
    var on = !isStarred(card);
    local[card.dataset.img] = on;
    localStorage.setItem(LOCAL_KEY, JSON.stringify(local));
    applyStars();
    if (location.protocol === 'file:') return;
    fetch('/api/star', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: card.dataset.img, starred: on})
    }).then(function (response) {
      if (!response.ok) return;
      card.dataset.starred = on ? '1' : '';  // saved in the sidecar
      delete local[card.dataset.img];
      localStorage.setItem(LOCAL_KEY, JSON.stringify(local));
    }).catch(function () {});
  }
  cards.forEach(function (card) {
    card.querySelector('.star-btn').addEventListener('click', function (e) {
      e.stopPropagation();
      toggleStar(card);
    });
  });

  // ── Lightbox: the app's frame view ────────────────────────────────────────
  var lb = document.getElementById('lightbox');
  var lbImg = document.getElementById('lb-img');
  var lbCard = null;
  document.getElementById('lb-roll').textContent = document.querySelector('h1').textContent;
  function shown() {
    return Array.prototype.slice.call(document.querySelectorAll('.card'))
      .filter(function (c) { return !c.hidden; });
  }
  function showLbStar() {
    var star = document.getElementById('lb-star');
    var on = isStarred(lbCard);
    star.innerHTML = on ? '&#9733;' : '&#9734;';
    star.classList.toggle('on', on);
  }
  function row(key, values) {
    var div = document.createElement('div');
    div.className = 'sheet-row';
    var k = document.createElement('span');
    k.className = 'key';
    k.textContent = key;
    var v = document.createElement('span');
    v.textContent = values.length ? values.join(', ') : '\\u2014';
    if (!values.length) v.className = 'empty';
    div.appendChild(k);
    div.appendChild(v);
    return div;
  }
  var split = function (s) { return (s || '').split('|').map(function (x) { return x.trim(); }).filter(Boolean); };
  function showLb(card) {
    lbCard = card;
    lbImg.src = card.dataset.src;
    var list = shown();
    document.getElementById('lb-counter').textContent =
      (list.indexOf(card) + 1) + ' / ' + list.length + ' \\u00b7 ' + card.dataset.img;
    document.getElementById('lb-desc').textContent = card.dataset.description;
    var sheet = document.getElementById('lb-sheet');
    sheet.innerHTML = '';
    sheet.appendChild(row('people', split(card.dataset.people)));
    sheet.appendChild(row('landmarks', split(card.dataset.landmarks)));
    sheet.appendChild(row('place', split(card.dataset.place)));
    sheet.appendChild(row('tags', split(card.dataset.tags)));
    sheet.appendChild(row('category', split(card.dataset.category)));
    showLbStar();
  }
  function openLb(card) { showLb(card); lb.classList.add('open'); document.body.style.overflow = 'hidden'; }
  function closeLb() { lb.classList.remove('open'); lbImg.removeAttribute('src'); lbCard = null; document.body.style.overflow = ''; }
  function step(by) {
    var list = shown();
    var i = list.indexOf(lbCard);
    showLb(list[(i + by + list.length) % list.length]);
  }
  cards.forEach(function (card) {
    card.querySelector('img').addEventListener('click', function () { openLb(card); });
  });
  document.getElementById('lb-close').addEventListener('click', closeLb);
  document.getElementById('lb-close-title').addEventListener('click', closeLb);
  document.getElementById('lb-star').addEventListener('click', function () { if (lbCard) toggleStar(lbCard); });

  // ── Keys ───────────────────────────────────────────────────────────────────
  document.addEventListener('keydown', function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (lb.classList.contains('open')) {
      if (e.key === 'ArrowLeft') { e.preventDefault(); step(-1); }
      else if (e.key === 'ArrowRight') { e.preventDefault(); step(1); }
      else if (e.key === 's' || e.key === 'S') toggleStar(lbCard);
      else if (e.key === 'Escape') closeLb();
      return;
    }
    if (document.activeElement === searchEl) {
      if (e.key === 'Escape') {
        if (searchEl.value) { searchEl.value = ''; search(); } else searchEl.blur();
      }
      return;
    }
    if (e.key === '/' || e.key === 'Enter') { e.preventDefault(); searchEl.focus(); }
  });

  applyStars();
  search();
})();
</script>"""
