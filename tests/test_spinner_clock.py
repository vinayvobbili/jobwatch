"""The spinner clock: every spinner and busy state on the page shows the seconds it has been running. The helper's
block of the page script runs in node against a small fake page (a fake clock, timers and elements): the words, the
tick, one timer for all tickers, cleanup, a hidden tab, the estimate's wording and what a screen reader hears. Then
each spinner builder is checked for its ticker, and one spinner runs in a real browser on the browser's own clock."""

# ruff: noqa: F811  (a test's `page` argument is the fixture imported from test_browser)
import json
import re
import shutil
import subprocess
from importlib import resources

import pytest

from .test_browser import browser, page, sync_api, watchlist  # noqa: F401 (fixtures)
from .test_page_js import page_const, page_function

needs_node = pytest.mark.skipif(not shutil.which("node"), reason="needs node")

PAGE = resources.files("jobwatch").joinpath("static/index.html").read_text(encoding="utf-8")


def clock_block() -> str:
    """The spinner clock's source in the page script, between its markers."""
    m = re.search(r"// SPINNER-CLOCK-START\n(.*?)// SPINNER-CLOCK-END", PAGE, re.S)
    assert m, "the page has no spinner clock block"
    return m.group(1)


# A page in miniature: elements with classes, attributes and children, timers and Date.now under the test's control,
# a document that can hide and come back, and the browser's storage as a Map.
FAKE_PAGE = r"""
class Classes {
  constructor() { this.set = new Set(); }
  add(...c) { c.forEach(x => this.set.add(x)); }
  remove(...c) { c.forEach(x => this.set.delete(x)); }
  contains(c) { return this.set.has(c); }
  toggle(c, on) { (on === undefined ? !this.set.has(c) : on) ? this.set.add(c) : this.set.delete(c); }
  [Symbol.iterator]() { return this.set[Symbol.iterator](); }
}
class El {
  constructor(tag) { this.tag = tag; this.kids = []; this.attrs = {}; this.classList = new Classes(); this.parent = null; this.title = ""; }
  get isConnected() { let e = this; while (e.parent) e = e.parent; return e === document.body; }
  get tagName() { return this.tag.toUpperCase(); }
  get textContent() { return this.kids.map(k => typeof k === "string" ? k : k.textContent).join(""); }
  set textContent(t) { this.kids.forEach(k => { if (k instanceof El) k.parent = null; }); this.kids = [String(t)]; }
  set className(c) { this.classList = new Classes(); c.split(" ").filter(Boolean).forEach(x => this.classList.add(x)); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  adopt(k) { if (k instanceof El) { k.parent?.drop(k); k.parent = this; } return k; }
  drop(k) { this.kids = this.kids.filter(x => x !== k); }
  append(...ks) { ks.forEach(k => this.kids.push(this.adopt(k))); }
  prepend(...ks) { this.kids.unshift(...ks.map(k => this.adopt(k))); }
  replaceChildren(...ks) { this.kids.forEach(k => { if (k instanceof El) k.parent = null; }); this.kids = []; this.append(...ks); }
  remove() { this.parent?.drop(this); this.parent = null; }
  querySelector(sel) { return this.find(e => sel.startsWith(".") && e.classList.contains(sel.slice(1))); }
  find(test) { for (const k of this.kids) if (k instanceof El) { if (test(k)) return k; const f = k.find(test); if (f) return f; } return null; }
}
const dom = { handlers: {}, byId: new Map() };
const document = {
  hidden: false, body: new El("body"),
  addEventListener: (type, fn) => { (dom.handlers[type] ||= []).push(fn); },
  getElementById: id => dom.byId.get(id) || null,
  fire(type) { (dom.handlers[type] || []).forEach(fn => fn()); },
};
document.body.parent = null;
function h(tag, attrs, ...kids) {
  const el = new El(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v; else if (k === "id") { el.setAttribute(k, v); dom.byId.set(v, el); } else el.setAttribute(k, v);
  }
  el.append(...kids.flat(Infinity).filter(k => k !== null && k !== undefined && k !== false));
  return el;
}
const icon = name => h("svg", { "data-icon": name });
let now = 1_000_000;
Date.now = () => now;
const timers = { active: new Map(), next: 1, started: 0 };
global.setInterval = (fn) => { const id = timers.next++; timers.active.set(id, fn); timers.started++; return id; };
global.clearInterval = id => { timers.active.delete(id); };
// the time passes by `ms`, and every running timer fires once (the page's own tick recomputes from Date.now())
const pass = ms => { now += ms; [...timers.active.values()].forEach(fn => fn()); };
const storage = new Map();
const remembered = (key, fallback) => storage.get(key) || fallback;
const remember = (key, value) => storage.set(key, value);
const attach = el => { document.body.append(el); return el; };
"""


def run_node(tmp_path, body: str, extra: str = ""):
    js = tmp_path / "spinner.js"
    js.write_text(FAKE_PAGE + clock_block() + extra + body, encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@needs_node
def test_the_clock_says_seconds_then_minutes_and_the_estimate_in_a_calm_voice(tmp_path):
    out = run_node(tmp_path, """
console.log(JSON.stringify({
  words: [0, 7.9, 12, 59, 60, 65, 600, 3725].map(elapsedWords),
  spoken: [1, 12, 60, 65, 120].map(elapsedSpoken),
  plain: clockWords(12),
  expected: clockWords(12, 40),
  nearly: clockWords(50, 40),
  late: clockWords(61, 40),
  short: clockWords(12, 40, true),
  tiny: [clockSlow(14, 10), clockSlow(26, 10), clockSlow(40, 40), clockSlow(61, 40), clockSlow(500, null)],
}));
""")
    assert out["words"] == ["0s", "7s", "12s", "59s", "1m 00s", "1m 05s", "10m 00s", "62m 05s"]
    assert out["spoken"] == ["1 second", "12 seconds", "1 minute", "1 minute 5 seconds", "2 minutes"]
    assert out["plain"] == "12s"
    assert out["expected"] == "12s of about 40s"
    assert out["nearly"] == "50s of about 40s"  # past the estimate, not yet worth a remark: half the runs are
    assert out["late"] == "1m 01s of about 40s · taking longer than usual"
    assert out["short"] == "12s"  # a ring too small for words
    assert out["tiny"] == [False, True, False, True, False]


@needs_node
def test_a_ticker_counts_from_the_clock_with_one_timer_for_all_of_them(tmp_path):
    out = run_node(tmp_path, """
const a = attach(h("span")), b = attach(h("span")), c = attach(h("span"));
spinnerClock(a); spinnerClock(b); spinnerClock(c, { expected: 40 });
const first = [a.textContent, b.textContent, c.textContent];
pass(3000);
const third = a.textContent;
pass(9000);
const later = [a.textContent, c.textContent];
pass(55000);
console.log(JSON.stringify({ first, third, later, minute: a.textContent, timers: timers.started, running: timers.active.size,
  live: a.getAttribute("aria-live"), tabular: a.classList.contains("spin-clock"), long: a.classList.contains("long") }));
""")
    assert out["first"] == ["0s", "0s", "0s of about 40s"]
    assert out["third"] == "3s"
    assert out["later"] == ["12s", "12s of about 40s"]
    assert out["minute"] == "1m 07s"
    assert out["timers"] == 1 and out["running"] == 1  # three tickers, one timer
    assert out["live"] == "off"  # a screen reader is not told every second
    assert out["tabular"] and out["long"]


@needs_node
def test_the_owners_name_changes_every_ten_seconds_at_most_and_start_and_finish_are_spoken_once(tmp_path):
    out = run_node(tmp_path, """
const ring = attach(h("div", { role: "status", "aria-label": "Scoring…" })), tick = h("span");
ring.append(tick);
const stop = spinnerClock(tick, { owner: ring, say: "Scoring" });
const labels = [ring.getAttribute("aria-label")], said = [dom.byId.get("announcer").textContent];
let changes = 0, last = labels[0];
for (let i = 0; i < 25; i++) {  // 25 seconds of one-second ticks
  pass(1000);
  const now = ring.getAttribute("aria-label");
  if (now !== last) { changes++; labels.push(now); last = now; }
  said.push(dom.byId.get("announcer").textContent);
}
stop();
console.log(JSON.stringify({ labels, changes, said: [...new Set(said)], after: ring.getAttribute("aria-label"),
  finished: dom.byId.get("announcer").textContent }));
""")
    assert out["labels"] == ["Scoring, 0 seconds so far", "Scoring, 10 seconds so far", "Scoring, 20 seconds so far"]
    assert out["changes"] == 2
    assert out["said"] == ["Scoring…"]  # nothing was said while it ticked
    assert out["after"] == "Scoring…"  # the owner's own name comes back
    assert out["finished"] == "Scoring finished"


@needs_node
def test_a_ticker_that_leaves_the_page_is_dropped_and_the_timer_stops_with_the_last_one(tmp_path):
    out = run_node(tmp_path, """
const a = attach(h("span")), b = attach(h("span")), loose = h("span");  // loose is never put on the page
spinnerClock(a); spinnerClock(b); spinnerClock(loose);
pass(1000);
const both = CLOCKS.size;
a.remove();
pass(1000);
const afterA = CLOCKS.size;
const stopB = spinnerClock(attach(h("span")));
stopB(); b.remove();
pass(1000);
pass(11000);  // the never-attached one is dropped after a while too
console.log(JSON.stringify({ both, afterA, left: CLOCKS.size, running: timers.active.size }));
""")
    assert out == {"both": 3, "afterA": 2, "left": 0, "running": 0}


@needs_node
def test_a_hidden_tab_runs_no_timer_and_the_count_is_right_when_it_returns(tmp_path):
    out = run_node(tmp_path, """
const a = attach(h("span"));
spinnerClock(a);
pass(2000);
document.hidden = true; document.fire("visibilitychange");
const whileHidden = timers.active.size;
now += 125_000;  // two minutes pass with no tick at all
const stale = a.textContent;
document.hidden = false; document.fire("visibilitychange");
console.log(JSON.stringify({ whileHidden, stale, back: a.textContent, running: timers.active.size }));
""")
    assert out == {"whileHidden": 0, "stale": "2s", "back": "2m 07s", "running": 1}


@needs_node
def test_estimates_come_only_from_real_runs_and_a_redrawn_spinner_keeps_counting(tmp_path):
    out = run_node(tmp_path, """
const none = attach(h("span"));
spinnerClock(none, { usual: "score" });
const nothing = none.textContent;
for (const s of [30, 50]) storage.set("score-seconds", JSON.stringify([...JSON.parse(storage.get("score-seconds") || "[]"), s]));
const known = usualSeconds("score");
const withUsual = attach(h("span"));
const stop = spinnerClock(withUsual, { usual: "score" });
pass(41_000);
stop(true);  // a run that worked is kept for next time
const kept = JSON.parse(storage.get("score-seconds"));
const failed = spinnerClock(attach(h("span")), { usual: "score" });
pass(2000); failed();  // a failed one is not
const tooShort = attach(h("span"));
storage.set("quick-seconds", "[2,3]");
spinnerClock(tooShort, { usual: "quick" });  // under 5s: nothing worth saying
pass(12_000);
const tooShortText = tooShort.textContent;
// the same work drawn again (its card was redrawn) keeps its start
const one = attach(h("span")); spinnerClock(one, { key: "scoring:k" });
pass(7000); one.remove(); pass(500);
const two = attach(h("span")); spinnerClock(two, { key: "scoring:k" });
pass(1000); pass(0);
two.remove();  // and when the work has long been over, the next one starts at zero
pass(CLOCK_GAP_MS + 1000);
const fresh = attach(h("span")); spinnerClock(fresh, { key: "scoring:k" });
console.log(JSON.stringify({ nothing, known, withText: withUsual.textContent, kept, tooShort: tooShortText,
  redrawn: two.textContent, fresh: fresh.textContent }));
""")
    assert out["nothing"] == "0s"  # no history, no estimate invented
    assert out["known"] == 40
    assert out["withText"] == "41s of about 40s"
    assert out["kept"] == [30, 50, 41]
    assert out["tooShort"] == "12s"  # the seconds only, however long it runs
    assert out["redrawn"] == "8s"  # 7s, a redraw, and one more second
    assert out["fresh"] == "0s"


@needs_node
def test_the_builders_put_a_ticker_in_what_they_return(tmp_path):
    out = run_node(tmp_path, """
const note = attach(busyNote("Saving…"));
const loading = attach(loadingNote());
const btn = attach(h("button", { class: "btn" }));
const stop = buttonBusy(btn, "Scoring…", { usual: "score" });
const ring = noFitBox({ key: "k", unscored: { code: "scoring" } });
attach(ring);
const clockOf = el => el.find(e => e.classList.contains("spin-clock"));
pass(4000);
console.log(JSON.stringify({
  note: [note.textContent, clockOf(note).getAttribute("aria-live")],
  loading: loading.textContent,
  button: btn.textContent, buttonName: btn.getAttribute("aria-label"), ring: clockOf(ring).textContent,
  ringRole: ring.getAttribute("role"), ringName: ring.getAttribute("aria-label"),
  ringIsShort: clockOf(ring).title,
  clocks: CLOCKS.size,
}));
stop(); note.stop();
""", extra=page_const("SCORING_WORD") + "\n" + page_const("scoringNow") + "\n" + page_function("noFitBox") + "\n")
    assert out["note"] == ["Saving… 4s", "off"]
    assert out["loading"] == "Loading… 4s"
    assert out["button"] == "Scoring… 4s"
    assert out["buttonName"] == "Scoring, 0 seconds so far"
    assert out["ring"] == "4s"  # the number inside the ring
    assert out["ringRole"] == "status" and out["ringName"] == "Scoring, 0 seconds so far"
    assert out["clocks"] == 4


@needs_node
def test_a_pressed_button_ticks_and_puts_its_label_back(tmp_path):
    out = run_node(tmp_path, """
const btn = attach(h("button", { class: "btn act-queue" }, "Queue"));
const undo = pending(null, btn);
pass(3000);
const during = btn.textContent, busy = btn.classList.contains("busy");
undo();
pass(1000);
console.log(JSON.stringify({ during, busy, after: btn.textContent, name: btn.getAttribute("aria-label"), clocks: CLOCKS.size,
  busyNow: btn.classList.contains("busy") }));
""", extra=page_const("BUSY") + "\nlet lastAct = null;\n" + page_function("pending") + "\n")
    assert out == {"during": "Queuing… 3s", "busy": True, "after": "Queue", "name": None, "clocks": 0, "busyNow": False}


def test_no_busy_state_is_left_without_its_clock():
    """The lint for the next busy state someone adds: a spinner word set as plain text has no seconds."""
    word = (r'"(?:Saving|Loading|Thinking|Asking|Uploading|Looking|Starting|Reading|Scoring|Checking|Preparing|Drafting'
            r'|Transcribing)[^"]*…"')
    # send( is Add the posting's one call, which puts its word through buttonBusy
    ticking = ("buttonBusy", "busyNote", "loadingNote", "spinnerClock", "send(")
    loose = [line.strip() for line in PAGE.splitlines()
             if re.search(rf"(?:textContent\s*=\s*|,\s*){word}", line) and not any(t in line for t in ticking)]
    assert loose == []


def test_every_spinner_builder_has_its_ticker():
    wants = {
        "pending": "spinnerClock", "noFitBox": "spinnerClock", "scoreButton": "buttonBusy", "detailsScore": "buttonBusy",
        "readButton": "buttonBusy", "followupButton": "buttonBusy", "loading": "spinnerClock", "buttonBusy": "spinnerClock",
        "busyNote": "spinnerClock",
    }
    for name, call in wants.items():
        assert call in page_function(name), f"{name} has no {call}"
    page = PAGE
    fetch = page[page.index('document.getElementById("fetchBtn").onclick'):]
    assert "spinnerClock" in fetch[:900] and "busyNote" in fetch[:900]
    chat = page[page.index("async function ask(text)"):][:2500]
    assert "spinnerClock" in chat and "setInterval" not in chat  # the chat's thinking line shares the one timer
    assert page.count("setInterval(tickClocks") == 1


def test_a_ring_with_seconds_inside_holds_still_when_motion_is_reduced():
    css = PAGE[:PAGE.index("</style>")]
    reduced = css[css.index(".score-spin-wrap"):]
    assert ".score-spin { animation: none !important; }" in reduced
    assert "font-variant-numeric: tabular-nums" in css  # the width doesn't jump


def test_a_slow_request_counts_in_a_real_browser_on_the_browsers_own_clock(page, watchlist):
    """Press Check for new jobs while the server's answer is held: the button counts 0s, 3s, then 1m 05s (the page's
    clock is moved, not waited for), and gives its label back when the answer comes."""
    held = []
    page.route("**/api/fetch", lambda route: held.append(route))
    start = 1_800_000_000_000  # a fixed day, so the page's time moves only when the test moves it
    page.clock.install(time=start)
    page.reload()
    page.wait_for_load_state("networkidle")
    page.clock.pause_at(start + 1000)
    btn = page.locator("#fetchBtn")
    btn.click()
    sync_api.expect(btn).to_contain_text("Checking… 0s")
    page.clock.run_for(3000)
    sync_api.expect(btn).to_contain_text("Checking… 3s")
    assert btn.get_attribute("aria-label") == "Checking every company, 0 seconds so far"
    sync_api.expect(page.locator("#fetchStatus")).to_contain_text("Checking every company… 3s")
    page.clock.run_for(62000)
    sync_api.expect(btn).to_contain_text("Checking… 1m 05s")
    assert btn.get_attribute("aria-label") == "Checking every company, 1 minute so far"  # every 10 seconds, not every one
    assert page.locator("#fetchBtn .spin-clock").get_attribute("aria-live") == "off"
    held[0].fulfill(json=dict(new=0, jobs=0, errors={}, warnings={}))
    sync_api.expect(btn).to_have_text("Check for new jobs")
    assert btn.get_attribute("aria-label") is None
    assert page.errors == []
