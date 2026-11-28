"""The Comps tab's suggestion cards (static/index.html), run in node with a stub of the page's h(): rank medals, the score
ring, the five part bars (a part with no real value hatched, never a plain 50), the pay gauge's marker positions, the
stat tiles and the one-click nudges. The data is made up."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from .test_page_js import page_const, page_function

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="needs node")

PIECES = [page_const(n) for n in ("partText", "SUGGEST_PARTS", "SUGGEST_NUDGES", "HEAD_GOOD", "HEAD_BAD", "PAY_KINDS",
                                  "MEDALS", "GAUGE_STEP", "NEXT_STAGE", "STAGE_SCORE", "ICONS", "ROW_STYLE", "COMP_ROWS")] \
    + [page_function(n) for n in ("sourceLabel", "sourceLinks", "scoreMoves", "rowGroup", "compRowClass", "compLabel",
                                  "compActions", "compHead")] \
    + [page_function(n) for n in ("money", "scoreTone", "rankHeadline", "gaugeScale", "gaugePct", "payMarker",
                                  "suggestStats", "statTile", "rankMedal", "scoreRing", "partBar", "nudge", "payGauge",
                                  "rankFacts", "partWhy", "rankWhyBody", "rankStep", "trapTab", "openRankWhy",
                                  "suggestCard", "suggestionPanel")]

# a stand-in for the page's h() and the bits of the DOM the dialog touches: nodes are plain objects, document keeps its
# keydown listeners, and press() sends a key to them the way the browser would
STUBS = """
const all = (n, f, out = []) => { if (typeof n !== "object") return out; if (f(n)) out.push(n); n.kids.forEach(k => all(k, f, out)); return out; };
const h = (tag, attrs, ...kids) => ({ tag, attrs: attrs || {}, kids: kids.flat(Infinity).filter(k => k != null && k !== false),
  append(...k) { this.kids.push(...k); }, remove() { this.removed = true; }, focus() { document.activeElement = this; },
  contains(x) { return x === this || all(this, y => y === x).length > 0; },
  querySelectorAll() { return all(this, x => (x.tag === "button" && !x.attrs.disabled) || (x.tag === "a" && x.attrs.href)); } });
const fill = (el, ...kids) => { el.kids = kids.flat(Infinity).filter(k => k != null && k !== false); };
const text = n => typeof n === "object" ? n.kids.map(text).join("") : String(n);
const byClass = (n, c) => all(n, x => (x.attrs.class || "").split(" ").includes(c));
const link = (url, t) => h("a", { href: url }, t);
const monogram = name => h("div", { class: "mono" }, name[0]);
const icon = (name, size) => h("svg", { "data-icon": name, width: size });
const closeButton = onclick => h("button", { class: "btn btn-close", type: "button", onclick }, "Close");
const listeners = [];
const document = { activeElement: null, body: h("body"),
  addEventListener: (t, f, c) => listeners.push({ t, f, c }),
  removeEventListener: (t, f) => { const i = listeners.findIndex(l => l.f === f); if (i >= 0) listeners.splice(i, 1); } };
const press = (key, extra = {}) => {
  const e = { key, shiftKey: false, prevented: false, stopped: false, preventDefault() { this.prevented = true; },
    stopImmediatePropagation() { this.stopped = true; }, ...extra };
  [...listeners].forEach(l => l.t === "keydown" && l.f(e));
  return e;
};
const dialogs = () => all(document.body, n => (n.attrs.class || "").split(" ").includes("rank-shade") && !n.removed);
const count = () => text(byClass(dialogs()[0], "rk-count")[0]);
const who = () => text(all(dialogs()[0], n => n.tag === "h2")[0]);
let opened = [], rendered = 0;
const openDetails = key => opened.push(key);
const render = () => { rendered++; };
const detailsButton = o => h("button", { class: "btn act-details" }, "Details");
const pickSave = () => {};
const compView = { editing: null, health: null, reveal: false, ranks: null, picked: null };
const P = (known, score, input) => ({ known, score, input });
const row = (key, company, status, total, parts, pay, assumed) => ({ key, company, title: "Engineer", status, url: "https://example.com/" + key,
  total, reason: "Why.", pay, assumed, mostly_assumed: assumed.length >= 3, fill: [], parts });
const full = { career: P(true, 95, "tech"), pay: P(true, 90, "x"), fit: P(true, 84, "x"), progress: P(true, 100, "offer"), health: P(true, 75, "x") };
const thin = { career: P(false, 50, "no kind or role kept"), pay: P(false, 50, "no pay known"), fit: P(false, 50, "not scored"),
  progress: P(true, 40, "screening"), health: P(false, 50, "no company health kept") };
const ranking = [
  row("a", "Initech", "offer", 82, full, { kind: "offered", figure: 140000, rate: null, w2: false }, []),
  row("b", "Globex", "interviewing", 61, { ...full, career: P(false, 50, "no kind or role kept"), pay: P(true, 64, "x") },
      { kind: "base", figure: 166400, rate: "$80/hr", w2: true }, ["career"]),
  row("c", "Umbrella", "screening", 48, thin, null, ["career", "pay", "fit", "health"]),
  row("d", "Hooli", "applied", 35, { ...full, health: P(true, 20, "layoffs") }, { kind: "posted", figure: 125000, rate: null, w2: false }, []),
];
const s = { weights: { career: .25, pay: .3, fit: .2, progress: .1, health: .15 }, target: "$150K-$170K", target_low: 150000,
  target_high: 170000, ranking };
"""


def run(body: str):
    script = "\n".join(PIECES) + STUBS + body
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_ranks_get_gold_silver_bronze_medals_then_plain_numbers():
    out = run("""
const panel = suggestionPanel(s, [{ key: "c", pay_estimate: { mid: 135000 } }]);
const cards = byClass(panel, "cmp-card");
console.log(JSON.stringify({
  medals: cards.map(c => byClass(c, "medal")[0].attrs.class + ":" + text(byClass(c, "medal")[0])),
  glows: cards.map(c => c.attrs.class),
  order: cards.map(c => text(c.kids[0].kids[2].kids[0])),
}));""")
    assert out["medals"] == ["medal gold:1", "medal silver:2", "medal bronze:3", "medal plain:4"]
    assert out["glows"][:3] == ["cmp-card m-gold", "cmp-card m-silver", "cmp-card m-bronze"] and out["glows"][3] == "cmp-card"
    assert out["order"] == ["Initech", "Globex", "Umbrella", "Hooli"]


def test_a_part_with_no_real_value_is_a_hatched_bar_with_its_default_named():
    out = run("""
const known = partBar("fit", P(true, 84, "fit 84/100"));
const mid = partBar("pay", P(true, 55, "x")), low = partBar("health", P(true, 20, "layoffs"));
const unk = partBar("career", P(false, 50, "no kind or role kept"));
console.log(JSON.stringify({
  classes: [known, mid, low, unk].map(b => b.attrs.class),
  width: byClass(known, "pt")[0].kids[0].attrs.style, unkWidth: byClass(unk, "pt")[0].kids[0].attrs.style,
  values: [known, unk].map(b => text(byClass(b, "pv")[0])), title: unk.attrs.title, aria: unk.attrs["aria-label"],
}));""")
    assert out["classes"] == ["pbar tone-hi", "pbar tone-mid", "pbar tone-lo", "pbar assumed"]
    assert out["width"] == "width:84%" and out["unkWidth"] == "width:50%"
    assert out["values"] == ["84", "~50"]
    assert out["title"] == out["aria"] == "career: not found, default 50 assumed (no kind or role kept)"


def test_the_card_calls_out_assumed_parts_and_each_has_a_nudge_that_opens_its_editor():
    out = run("""
const panel = suggestionPanel(s, []);
const [a, b, c] = byClass(panel, "cmp-card");
const nudges = card => byClass(card, "nudge").map(n => text(n));
const rings = [a, b, c].map(card => byClass(card, "cmp-ring")[0]);
const badge = card => byClass(card, "asm-badge").map(n => text(n) + ":" + n.attrs.class);
// the nudges act: pay and health open their editors, fit opens the job's details
const go = (k, r) => { compView.editing = compView.health = null; compView.reveal = false; opened = []; rendered = 0; nudge(k, r).attrs.onclick();
  return { editing: compView.editing, health: compView.health, reveal: compView.reveal, opened, rendered }; };
console.log(JSON.stringify({
  a: { nudges: nudges(a), badge: badge(a), ring: rings[0].attrs.class },
  b: { nudges: nudges(b), badge: badge(b), ring: rings[1].attrs.class },
  c: { nudges: nudges(c), badge: badge(c), ring: rings[2].attrs.class, mark: text(rings[2]) },
  pay: go("pay", ranking[2]), health: go("health", ranking[2]), career: go("career", ranking[1]), fit: go("fit", ranking[2]),
}));""")
    assert out["a"] == {"nudges": [], "badge": [], "ring": "cmp-ring tone-hi"}
    assert out["b"]["nudges"] == ["+ Add kind and role"] and out["b"]["badge"] == ["1 assumed:asm-badge"]
    assert out["b"]["ring"] == "cmp-ring tone-mid assumed"
    assert out["c"]["nudges"] == ["+ Add kind and role", "+ Add pay", "+ Read posting to score fit", "+ Add health"]
    assert out["c"]["badge"] == ["mostly assumed (4):asm-badge heavy"] and out["c"]["mark"] == "48*"
    assert out["pay"] == {"editing": "c", "health": None, "reveal": True, "opened": [], "rendered": 1}
    assert out["health"] == {"editing": None, "health": "Umbrella", "reveal": True, "opened": [], "rendered": 1}
    assert out["career"]["health"] == "Globex" and out["career"]["rendered"] == 1
    assert out["fit"] == {"editing": None, "health": None, "reveal": False, "opened": ["c"], "rendered": 0}


def test_the_gauge_puts_the_marker_and_the_target_band_on_one_shared_scale():
    out = run("""
const scale = gaugeScale([166400, 140000, 125000], [150000, 170000]);
const g = payGauge(payMarker(ranking[0], null), scale, 150000, 170000);
const w2 = payGauge(payMarker(ranking[1], null), scale, 150000, 170000);
const est = payGauge(payMarker(ranking[2], { pay_estimate: { mid: 135000 } }), scale, 150000, 170000);
const none = payGauge(payMarker(ranking[2], null), scale, 150000, 170000);
const noBand = payGauge(payMarker(ranking[3], null), scale, null, null);
const mark = n => byClass(n, "pg-mark")[0];
console.log(JSON.stringify({
  scale, pcts: [110000, 150000, 190000, 50000, 999999].map(v => gaugePct(scale, v)),
  offered: { left: mark(g).attrs.style, flag: text(mark(g)), pill: text(byClass(g, "pk")[0]), band: byClass(g, "pg-band")[0].attrs.style },
  contract: { cls: mark(w2).attrs.class, flag: text(mark(w2)), pill: text(byClass(w2, "pk")[0]), pillCls: byClass(w2, "pk")[0].attrs.class },
  est: { cls: mark(est).attrs.class, pill: text(byClass(est, "pk")[0]), left: mark(est).attrs.style },
  none: text(none), noBand: { bands: byClass(noBand, "pg-band").length, pill: text(byClass(noBand, "pk")[0]) },
  tiny: gaugeScale([100000], null),
}));""")
    assert out["scale"] == {"min": 110000, "max": 190000}  # a tenth of room either side, on round numbers
    assert out["pcts"] == [0, 50, 100, 0, 100]  # clamped to the ends of the gauge
    assert out["offered"] == {"left": "left:37.5%", "flag": "$140K", "pill": "Offered", "band": "left:50%;width:25%"}
    assert out["contract"] == {"cls": "pg-mark w2", "flag": "$166K", "pill": "Told $80/hr", "pillCls": "pk w2"}
    assert out["est"] == {"cls": "pg-mark est", "pill": "Est.", "left": "left:31.3%"}
    assert out["none"] == "PayNo pay known yet"
    assert out["noBand"] == {"bands": 0, "pill": "Posted"}
    assert out["tiny"] == {"min": 90000, "max": 110000}  # a lone figure still gets a gauge with room either side


def test_stat_tiles_come_from_the_ranking():
    out = run("""
console.log(JSON.stringify({
  tiles: suggestStats(s).map(t => [t.key, t.value + (t.unit || ""), t.label, t.sub]),
  noTarget: suggestStats({ ...s, target_low: null, target_high: null }).map(t => t.value + "|" + t.sub).slice(3),
  none: suggestStats({ ...s, ranking: [row("z", "Hooli", "applied", 35, thin, null, ["pay"])] }).map(t => t.value + "|" + t.sub),
  under: suggestStats({ ...s, ranking: [ranking[0], ranking[3]] }).slice(2).map(t => t.value + "|" + t.sub),
  tile: statTile(suggestStats(s)[1], 1).attrs.class,
}));""")
    assert out["tiles"] == [
        ["count", "4", "Jobs compared", "side by side"],
        ["best", "82/100", "Best score", "Initech"],
        ["pay", "$166K", "Highest pay told", "Globex"],  # posted pay is not "told"; the offer and the base are
        ["near", "In band", "Closest to target", "Globex"],  # $166K sits inside $150K-$170K
    ]
    assert out["noTarget"] == ["—|no pay target set"]
    assert out["none"] == ["1|one in the running", "35|Hooli", "—|none told yet", "—|no pay known yet"]
    # only an offer ($140K) and a posted figure ($125K): the offer is the closest, $10K under the band
    assert out["under"] == ["$140K|Initech", "$10K under|Initech"]
    assert out["tile"] == "cmp-stat t-best"


def test_the_headline_is_one_short_sentence_from_the_parts_with_a_real_value():
    out = run("""
const parts = o => ({ ...full, ...o });
console.log(JSON.stringify([
  rankHeadline({ parts: full }),
  rankHeadline({ parts: parts({ pay: P(true, 45, "x"), progress: P(true, 100, "offer") }) }),
  rankHeadline({ parts: parts({ career: P(false, 50, "no kind or role kept"), fit: P(true, 82, "x"), pay: P(true, 70, "x"),
    health: P(true, 70, "x"), progress: P(true, 70, "x") }) }),
  rankHeadline({ parts: thin }),
  rankHeadline({ parts: { career: P(false, 50, "x"), pay: P(false, 50, "x"), fit: P(false, 50, "x"), progress: P(false, 50, "x"),
    health: P(false, 50, "x") } }),
  rankHeadline({ parts: parts({ career: P(true, 55, "x"), pay: P(true, 55, "x"), fit: P(true, 55, "x"), progress: P(true, 55, "x"),
    health: P(true, 55, "x") }) }),
]));""")
    assert out[0] == "Well along."  # progress 100 is the strongest part; nothing is a worry
    assert out[1] == "Well along, but pay is under target."
    assert out[2] == "Strong fit."  # the unknown career is no evidence either way
    assert out[3] == "Still early."  # the only part with a real value is progress 40, which is a worry
    assert out[4] == "Little is known about it yet."
    assert out[5] == "Middling so far."


def test_a_card_is_compact_and_why_this_rank_is_a_button_not_an_inline_expander():
    out = run("""
const panel = suggestionPanel(s, []);
const cards = byClass(panel, "cmp-card");
console.log(JSON.stringify({
  details: cards.map(c => all(c, n => n.tag === "details").length),
  buttons: cards.map(c => byClass(c, "why-btn").map(b => text(b) + ":" + b.attrs["aria-haspopup"])),
  how: all(panel, n => n.tag === "details").map(n => n.attrs.class),
}));""")
    assert out["details"] == [0, 0, 0, 0]  # nothing expands inside a card, so the cards line up
    assert out["buttons"] == [["Why this rank:dialog"]] * 4
    assert out["how"] == ["cmp-how"]  # only the rules disclosure is inline


def test_the_dialog_opens_on_the_card_you_chose_and_esc_closes_it_returning_focus():
    out = run("""
const panel = suggestionPanel(s, []);
const btn = byClass(panel, "why-btn")[1];
btn.attrs.onclick();
const shade = dialogs()[0], box = shade.kids[0];
const opening = { n: dialogs().length, role: box.attrs.role, modal: box.attrs["aria-modal"], label: box.attrs["aria-label"],
  count: count(), who: who(), focus: document.activeElement === box, listeners: listeners.length,
  ring: byClass(box, "cmp-ring")[0].attrs.class, head: text(all(byClass(box, "rk-lead")[0], n => n.tag === "h3")[0]) };
const e = press("Escape");
console.log(JSON.stringify({ opening, esc: { stopped: e.stopped, open: dialogs().length, back: document.activeElement === btn, listeners: listeners.length } }));""")
    assert out["opening"] == {"n": 1, "role": "dialog", "modal": "true", "label": "Why this rank", "count": "2 of 4",
                              "who": "Globex", "focus": True, "listeners": 1, "ring": "cmp-ring tone-mid assumed big",
                              "head": "Well along."}
    assert out["esc"] == {"stopped": True, "open": 0, "back": True, "listeners": 0}  # the page's own Esc handler never sees it


def test_the_backdrop_and_the_close_chip_close_it_but_a_click_inside_does_not():
    out = run("""
const panel = suggestionPanel(s, []);
const btn = byClass(panel, "why-btn")[0];
btn.attrs.onclick();
const shade = dialogs()[0], box = shade.kids[0];
shade.attrs.onclick({ target: box });  // a click inside the dialog bubbles to the backdrop with the dialog as target
const inside = dialogs().length;
shade.attrs.onclick({ target: shade });
const afterBackdrop = { open: dialogs().length, back: document.activeElement === btn, listeners: listeners.length };
btn.attrs.onclick();
byClass(dialogs()[0], "btn-close")[0].attrs.onclick();
console.log(JSON.stringify({ inside, afterBackdrop, afterChip: dialogs().length, listeners: listeners.length }));""")
    assert out == {"inside": 1, "afterBackdrop": {"open": 0, "back": True, "listeners": 0}, "afterChip": 0, "listeners": 0}


def test_arrow_keys_step_to_the_previous_or_next_ranked_job_and_stop_at_the_ends():
    out = run("""
const panel = suggestionPanel(s, []);
const buttons = byClass(panel, "why-btn");
buttons[0].attrs.onclick();
const seen = [];
const note = key => { const e = press(key); seen.push([key, count(), who(), e.prevented]); };
note("ArrowLeft");   // already the first: nothing moves
note("ArrowRight"); note("ArrowRight"); note("ArrowRight"); note("ArrowRight");  // the last stops the walk
note("ArrowLeft");
const arrows = byClass(dialogs()[0], "rk-arrow").map(b => [b.attrs["aria-label"], !!b.attrs.disabled]);
byClass(dialogs()[0], "rk-arrow")[1].attrs.onclick();  // the Next button does the same as the key
const viaButton = count();
press("Escape");
const back = document.activeElement === buttons[3];
buttons[1].attrs.onclick(); press("ArrowRight");
console.log(JSON.stringify({ seen, arrows, viaButton, back, focusOnStep: document.activeElement === dialogs()[0].kids[0] }));""")
    assert out["seen"] == [
        ["ArrowLeft", "1 of 4", "Initech", False],
        ["ArrowRight", "2 of 4", "Globex", True], ["ArrowRight", "3 of 4", "Umbrella", True],
        ["ArrowRight", "4 of 4", "Hooli", True], ["ArrowRight", "4 of 4", "Hooli", False],
        ["ArrowLeft", "3 of 4", "Umbrella", True]]
    assert out["arrows"] == [["Previous job", False], ["Next job", False]]
    assert out["viaButton"] == "4 of 4"
    assert out["back"] is True  # focus returns to the card of the job last shown
    assert out["focusOnStep"] is True


def test_tab_stays_inside_the_dialog():
    out = run("""
const panel = suggestionPanel(s, []);
byClass(panel, "why-btn")[0].attrs.onclick();
const box = dialogs()[0].kids[0], items = box.querySelectorAll(), first = items[0], last = items[items.length - 1];
last.focus(); const fwd = press("Tab");
const afterLast = document.activeElement === first;
first.focus(); const back = press("Tab", { shiftKey: true });
const afterFirst = document.activeElement === last;
document.activeElement = box; const fromBox = press("Tab", { shiftKey: true });
const fromBoxLast = document.activeElement === last;
document.activeElement = items[1]; const middle = press("Tab");
console.log(JSON.stringify({ n: items.length, fwd: fwd.prevented, afterLast, back: back.prevented, afterFirst,
  fromBox: fromBox.prevented && fromBoxLast, middle: middle.prevented }));""")
    assert out["n"] >= 3  # Next, Close and the title link at least (Previous is disabled on the first job)
    assert out["fwd"] and out["afterLast"] and out["back"] and out["afterFirst"] and out["fromBox"]
    assert out["middle"] is False  # inside the dialog Tab moves on by itself


def test_the_dialog_gives_every_part_its_reasoning_and_each_missing_part_its_fix():
    out = run("""
const opps = [{ key: "b", comp: { base: "$80/hr W-2", role: "product" }, pay: "$110K-$140K", status: "interviewing",
  applied_at: "2026-10-01T09:00:00", next_step: "Panel on Monday", places: ["Boulder, CO", "Remote"],
  fit: { score: 82, met: 5, total: 6, gaps: ["Rust", "Kafka"] },
  health: { listing: "private", stage: "Series B", kind: "tech", layoffs: "none", headcount: "growing", rating: "4.1",
    risk: "one big customer", sources: "https://example.com/globex", as_of: "2026-09-01", stale: true } }];
const panel = suggestionPanel(s, opps);
byClass(panel, "why-btn")[1].attrs.onclick();
const box = dialogs()[0].kids[0];
const rows = byClass(box, "pwhy").map(t => text(byClass(t, "pw-txt")[0]));
const callout = byClass(box, "rk-callout")[0];
const facts = byClass(box, "rk-card").slice(1).map(c => [text(c.kids[0]), c.kids[1].kids.map(k => text(k))]);
const before = dialogs().length;
byClass(callout, "nudge")[0].attrs.onclick();  // a fix closes the dialog first, then opens its editor behind it
console.log(JSON.stringify({ rows, callout: text(callout), nudges: byClass(callout, "nudge").map(n => text(n)), facts,
  gauge: byClass(box, "pgauge")[0].attrs.class, closed: [before, dialogs().length], health: compView.health, rendered }));""")
    assert out["rows"] == [  # a default is named, with its share of the score and what it adds
        "Not found, default 50 assumed (no kind or role kept) · 25% of the score · adds 13 points",
        "X · 30% of the score · adds 19 points", "X · 20% of the score · adds 17 points",
        "Offer · 10% of the score · adds 10 points", "X · 15% of the score · adds 11 points"]
    assert out["callout"].startswith("1 of the 5 parts has no real value")
    assert out["nudges"] == ["+ Add kind and role"]
    assert out["gauge"] == "pgauge big"
    assert out["closed"] == [1, 0] and out["health"] == "Globex" and out["rendered"] == 1
    pairs = {title: list(zip(rows[::2], rows[1::2], strict=True)) for title, rows in out["facts"]}  # the dl's dt, dd, ...
    assert pairs == {
        "Pay": [("Told", "$166K ($80/hr, W-2)"), ("Posted", "$110K-$140K"), ("Base told", "$80/hr W-2"),
                ("Your target", "$150K-$170K")],
        "Company health the rank used": [
            ("Listing", "private"), ("Stage", "Series B"), ("Kind", "Tech company"), ("Layoffs", "none"),
            ("Headcount", "growing"), ("Rating", "4.1"), ("Risk", "one big customer"),
            ("Sources", "example.com"), ("As of", "2026-09-01 (stale: look it up again)")],
        "The job and where it stands": [
            ("Stage", "interviewing"), ("Applied", "2026-10-01"), ("Next step", "Panel on Monday"),
            ("Place", "Boulder, CO; Remote"), ("Fit", "82/100, must-haves 5/6"), ("Gaps", "Rust, Kafka"),
            ("Role", "product")],
    }


def test_each_source_is_its_own_link_labelled_by_its_site():
    out = run("""
const hl = { sources: "https://www.initech.example/news/2026 https://globex.example/ratings?c=7 see Umbrella filings" };
const rows = rankFacts(ranking[0], { health: { ...hl, as_of: "2026-09-01" } }, s).find(sec => sec.title.startsWith("Company")).rows;
const cell = rows.find(([k]) => k === "Sources")[1];
const links = all(cell, n => n.tag === "a");
console.log(JSON.stringify({ cls: cell.attrs.class, links: links.map(a => [text(a), a.attrs.href, a.attrs.title, a.attrs.target, a.attrs.rel]),
  note: text(byClass(cell, "muted")[0]), plain: sourceLinks("a note, no links"), bad: sourceLabel("not a url") }));""")
    assert out["cls"] == "src-list"
    assert out["links"] == [
        ["initech.example", "https://www.initech.example/news/2026", "https://www.initech.example/news/2026", "_blank",
         "noopener noreferrer"],
        ["globex.example", "https://globex.example/ratings?c=7", "https://globex.example/ratings?c=7", "_blank",
         "noopener noreferrer"]]
    assert out["note"] == "see Umbrella filings"  # words that aren't links stay as text
    assert out["plain"] == "a note, no links" and out["bad"] == "not a url"


def test_sources_become_links_whatever_separates_them_and_never_markup():
    out = run("""
const one = t => { const n = sourceLinks(t); return typeof n === "string" ? n : { links: all(n, x => x.tag === "a").map(a =>
  [a.attrs.href, text(a), a.attrs.title, a.attrs["aria-label"], a.attrs.target, a.attrs.rel]), rest: byClass(n, "muted").map(text) }; };
console.log(JSON.stringify({
  many: one("https://www.initech.example/a, https://globex.example/b;\\nhttps://umbrella.example/c/d."),
  punct: one("(see https://initech.example/q?x=1&y=2), https://globex.example/wiki/Item_(Corp))."),
  scheme: one("javascript:alert(1) ftp://files.example/x mailto:hr@initech.example"),
  mixed: one("see https://initech.example/ and javascript:alert(1)"),
  markup: one('https://initech.example/<img src=x onerror=alert(1)> "https://globex.example/"><script>alert(1)</script>'),
  noUrl: one("just words"),
}));""")
    link = lambda href, label: [href, label, href, href, "_blank", "noopener noreferrer"]  # noqa: E731
    assert out["many"] == {"links": [link("https://www.initech.example/a", "initech.example"),
                                     link("https://globex.example/b", "globex.example"),
                                     link("https://umbrella.example/c/d", "umbrella.example")], "rest": []}
    assert out["punct"]["links"] == [link("https://initech.example/q?x=1&y=2", "initech.example"),
                                     link("https://globex.example/wiki/Item_(Corp)", "globex.example")]
    assert out["punct"]["rest"] == ["(see"]
    assert out["scheme"] == "javascript:alert(1) ftp://files.example/x mailto:hr@initech.example"  # no http(s): plain text
    assert out["mixed"] == {"links": [link("https://initech.example/", "initech.example")], "rest": ["see and javascript:alert(1)"]}
    # the data is only ever text or an href set by the DOM: no tag in it is an element
    markup = out["markup"]
    assert [a[0] for a in markup["links"]] == ["https://initech.example/<img"]  # an href is an attribute, never parsed
    assert markup["rest"] == ['src=x onerror=alert(1)> "https://globex.example/"><script>alert(1)</script>']  # plain text
    assert out["noUrl"] == "just words"


def test_what_would_move_the_score_is_plain_arithmetic_on_the_weights_and_parts():
    out = run("""
const parts = { career: P(true, 55, "x"), pay: P(true, 44, "x"), fit: P(true, 66, "x"), progress: P(true, 40, "screening"),
  health: P(true, 60, "x") };
const r = row("z", "Hooli", "screening", 50, parts, null, []);
const lines = rs => rs.map(m => `+${m.points} ${m.text}`);
const noTarget = scoreMoves(r, { ...s, target: null });
const withDefaults = row("y", "Globex", "offer", 60, { ...parts, pay: P(false, 50, "no pay known"), progress: P(true, 100, "offer") }, null, ["pay"]);
console.log(JSON.stringify({ moves: lines(scoreMoves(r, s)), noTarget: lines(noTarget), offer: lines(scoreMoves(withDefaults, s)),
  none: scoreMoves(ranking[0], s) }));""")
    assert out["moves"] == ["+11 Pay at your $150K-$170K target (the pay part is 44, 80 at target)", "+4 Career at 70, from 55",
                            "+3 Reaching interviewing, from screening", "+2 Health at 70, from 60"]  # the fifth, +1, is cut
    assert out["noTarget"][0] == "+4 Career at 70, from 55"  # no target, no pay line
    assert out["offer"] == ["+4 Career at 70, from 55", "+2 Health at 70, from 60", "+1 Fit at 70, from 66"]  # nothing past an offer;
    #                                                                                                          an assumed pay is no evidence
    assert out["none"] == []


def test_the_left_column_ends_with_the_callout_when_parts_are_missing_else_with_what_would_move_the_score():
    out = run("""
const partsAt = { career: P(true, 55, "x"), pay: P(true, 44, "x"), fit: P(true, 66, "x"), progress: P(true, 40, "screening"),
  health: P(true, 60, "x") };
const kinds = rank => {
  suggestionPanel({ ...s, ranking: [rank] }, []);
  byClass(suggestionPanel({ ...s, ranking: [rank] }, []), "why-btn")[0].attrs.onclick();
  const col = byClass(dialogs()[0], "rk-col")[0], last = col.kids[col.kids.length - 1];
  const out = { last: last.attrs.class, afterBars: col.kids.slice(-6).map(k => k.attrs.class), moves: byClass(last, "rk-moves").length,
    items: all(last, n => n.tag === "li").map(li => text(li)) };
  press("Escape");
  return out;
};
console.log(JSON.stringify({ moves: kinds(row("z", "Hooli", "screening", 50, partsAt, null, [])),
  callout: kinds(row("y", "Globex", "screening", 50, { ...partsAt, health: P(false, 50, "no company health kept") }, null, ["health"])) }));""")
    assert out["moves"]["last"] == "rk-card" and out["moves"]["moves"] == 1
    assert out["moves"]["items"][:2] == ["+11 Pay at your $150K-$170K target (the pay part is 44, 80 at target)",
                                         "+4 Career at 70, from 55"]
    assert out["callout"]["last"] == "rk-callout" and out["callout"]["moves"] == 0
    assert out["callout"]["afterBars"] == ["pwhy"] * 5 + ["rk-callout"]  # below the five bars, where the space was empty


def test_every_comparison_row_has_a_labelled_icon_chip_in_its_group_colour():
    out = run("""
const labels = COMP_ROWS.map(r => r[0]);
const el = compLabel("Posted pay"), chip = el.kids[0];
console.log(JSON.stringify({
  labels, missing: labels.filter(l => !ROW_STYLE[l]), noIcon: labels.filter(l => !(ROW_STYLE[l] && ICONS[ROW_STYLE[l][0]])),
  groups: [...new Set(Object.values(ROW_STYLE).map(v => v[1]))].sort(),
  chips: labels.map(l => { const e = compLabel(l); return [e.attrs.class, e.kids[0].attrs.class, e.kids[0].attrs["aria-hidden"],
    e.kids[0].kids[0].attrs["data-icon"], text(e.kids[1])]; }),
  one: { cls: el.attrs.class, svg: chip.kids[0].attrs["data-icon"], label: text(el.kids[1]), tag: chip.tag },
  rowClasses: labels.map((l, i) => compRowClass(i)),
}));""")
    labels = out["labels"]
    assert out["missing"] == [] and out["noIcon"] == []  # every row has an icon that exists in the page's icon set
    assert out["groups"] == ["company", "fit", "money", "people", "process"]
    assert all(c[1] == "rl-chip" and c[2] == "true" and c[4] == label for c, label in zip(out["chips"], labels, strict=True))
    assert out["one"] == {"cls": "rowlab g-money", "svg": "dollar", "label": "Posted pay", "tag": "i"}
    group = {label: c[0] for label, c in zip(labels, out["chips"], strict=True)}
    assert [group[x] for x in ("Applied", "Next step", "Place")] == ["rowlab g-process"] * 3
    assert [group[x] for x in ("Posted pay", "Base", "Bonus", "Equity", "Sign-on", "You asked", "Offered", "Glassdoor")] \
        == ["rowlab g-money"] * 8
    assert [group[x] for x in ("Fit", "Gaps")] == ["rowlab g-fit"] * 2
    assert [group[x] for x in ("You know", "Note")] == ["rowlab g-people"] * 2
    assert group["Layoffs"] == "rowlab g-company"
    # each block's first row starts a rule, and the rows inside it don't
    starts = [label for label, cls in zip(labels, out["rowClasses"], strict=True) if "g-first" in cls]
    assert starts[:4] == ["Applied", "Posted pay", "Fit", "You know"] and "Base" not in starts and "Gaps" not in starts


def test_a_column_head_keeps_the_buttons_for_the_row_below_and_the_card():
    out = run("""
compView.ranks = new Map([["a", { n: 0, r: ranking[0] }]]);
const o = { key: "a", kind: "job", company: "Initech", title: "Data Lead With A Very Long Title Indeed", url: "https://example.com/a", status: "offer" };
const slim = compHead(o, false), card = compHead(o);
const wrap = parts => ({ tag: "x", attrs: {}, kids: parts.filter(Boolean) });
const buttons = parts => all(wrap(parts), n => n.tag === "button").map(b => text(b).trim());
console.log(JSON.stringify({ slimParts: slim.filter(Boolean).length, fullParts: card.filter(Boolean).length, slimClasses: slim.map(p => p && p.attrs.class),
  slimButtons: buttons(slim), fullButtons: buttons(card), acts: buttons([compActions(o)]),
  title: byClass(slim[1], "co-title").map(t => [t.attrs.title, text(t)]), badge: byClass(slim[1], "stagebadge").map(text),
  ring: byClass(slim[0], "cmp-ring").length, medal: byClass(slim[0], "medal").length }));""")
    assert out["slimParts"] == 2 and out["slimClasses"][:2] == ["co-cell", "co-sub"] and out["fullParts"] == 3
    assert out["slimButtons"] == []  # the sticky head has no buttons: they sit in the row below, which scrolls away
    assert out["acts"] == ["Pay details", "Company health", "Details"] and out["fullButtons"] == out["acts"]  # a phone's card keeps them
    assert out["title"] == [["Data Lead With A Very Long Title Indeed", "Data Lead With A Very Long Title Indeed"]]
    assert out["badge"] == ["offer"] and out["ring"] == 1 and out["medal"] == 1


PAGE = Path(__file__).resolve().parent.parent.joinpath("jobwatch/static/index.html").read_text(encoding="utf-8")


def rule(selector: str) -> str:
    return re.search(re.escape(selector) + r"\s*\{([^}]*)\}", PAGE).group(1)


def test_the_table_head_sticks_under_the_nav_opaque_above_the_rows_and_below_the_nav():
    head = rule("table.comps thead tr.hd th")
    assert "position: sticky" in head and "top: var(--head, 64px)" in head  # --head is the nav's measured height
    z = int(re.search(r"z-index:\s*(\d+)", head).group(1))
    assert 1 < z < 5  # over the rows (the label column is 1), under the nav (header is 5) and the dialogs
    assert "var(--panel-solid)" in head and "transparent)" in head and "rgba" not in head  # a tint over a solid base
    assert int(re.search(r"z-index:\s*(\d+)", rule("table.comps thead tr.hd th.lbl")).group(1)) > z  # the corner is over the heads
    assert "sticky" in rule("table.comps th.lbl") and "left: 0" in rule("table.comps th.lbl")  # the labels stick sideways
    assert "overflow: visible" in rule(".comp-table:not(.hscroll)")  # no scroll box to stop the head sticking to the page
    assert "max-height" in rule(".comp-table.hscroll") and "overflow: auto" in rule(".comp-table.hscroll")
    assert "top: 0" in rule(".comp-table.hscroll table.comps thead tr.hd th")  # inside its own scroll box it sticks to the box's top
    assert "box-shadow" in rule(".comp-table.stuck table.comps thead tr.hd th")
    assert "transition: none" in PAGE.split("prefers-reduced-motion: reduce) { .comp-table.stuck")[1].split("}")[0]
    assert "sticky" not in rule("table.comps thead tr.acts th")  # the buttons' row scrolls away
    assert re.search(r"^header \{ position: sticky; top: 0; z-index: 5", PAGE, re.M)
