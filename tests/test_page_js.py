import json
import re
import shutil
import subprocess
from importlib import resources
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_page_script_parses(tmp_path):
    """A syntax error in the page's script leaves a blank page with no test failing elsewhere: node reads it."""
    page = resources.files("jobwatch").joinpath("static/index.html").read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    assert scripts
    js = tmp_path / "page.js"
    js.write_text("\n".join(scripts), encoding="utf-8")
    r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def page_function(name: str) -> str:
    """One top-level function's source from the page's script: a one-liner, or up to the first closing brace in
    column 0."""
    page = resources.files("jobwatch").joinpath("static/index.html").read_text(encoding="utf-8")
    m = (re.search(rf"^(?:async )?function {name}\(.*\}}$", page, re.M)
         or re.search(rf"^(?:async )?function {name}\(.*?^}}$", page, re.S | re.M))
    assert m, f"no function {name} in the page"
    return m.group(0)


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_todays_quick_narrowing(tmp_path):
    jobs = {
        "remote": {"where": ["remote"], "fit": {"score": 82}, "salary_max": 260000},
        "city": {"where": ["onsite"], "fit": {"score": 65}, "salary_max": 180000},
        "both": {"where": ["remote", "onsite"], "fit": None, "salary_max": None},  # not scored, no pay listed
        "nowhere": {"where": [], "fit": {"score": 50}, "salary_max": 300000},
    }
    views = {
        "off": {"where": "any", "fit": 0, "pay": 0},
        "remote": {"where": "remote", "fit": 0, "pay": 0},
        "onsite": {"where": "onsite", "fit": 0, "pay": 0},
        "fit70": {"where": "any", "fit": 70, "pay": 0},
        "pay250": {"where": "any", "fit": 0, "pay": 250000},
        "all": {"where": "remote", "fit": 80, "pay": 250000},
    }
    js = tmp_path / "narrow.js"
    js.write_text(page_function("quickNarrow") + f"""
const jobs = {json.dumps(jobs)}, views = {json.dumps(views)};
const out = {{}};
for (const [v, view] of Object.entries(views)) out[v] = Object.keys(jobs).filter(k => quickNarrow(jobs[k], view));
console.log(JSON.stringify(out));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {
        "off": ["remote", "city", "both", "nowhere"],
        "remote": ["remote", "both", "nowhere"],     # no location given isn't hidden
        "onsite": ["city", "both", "nowhere"],
        "fit70": ["remote", "both"],                 # not scored yet still shows
        "pay250": ["remote", "both", "nowhere"],     # no listed pay still shows
        "all": ["remote", "both"],
    }


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_page_stays_on_the_persons_side(tmp_path):
    """Every stage gets its own kind word (a no is put in its place, never just "marked rejected"), and Today
    says hello for the time of day."""
    js = tmp_path / "words.js"
    js.write_text("const pick = list => list[0], PASSED = [\"Their loss. Onward.\"];\n" + page_function("stageWords")
                  + page_function("greeting") + page_function("todayLine") + """
const stages = ["screening", "interviewing", "offer", "rejected", "withdrawn", "applied", "someday"];
console.log(JSON.stringify({ words: Object.fromEntries(stages.map(s => [s, stageWords("Acme", s)])),
  hello: [3, 9, 14, 20].map(greeting), line: todayLine(greeting(20), 5) }));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got["words"]["rejected"] == "🌱 Acme passed. Their loss. Onward."
    assert got["words"]["withdrawn"] == "Withdrawn from Acme. Good call: your time is worth protecting."
    assert got["words"]["offer"].startswith("🥂")
    assert got["words"]["someday"] == "Acme: marked someday."  # a stage with no words of its own still says something
    assert got["hello"] == ["Burning the midnight oil 🌙", "Good morning ☀️", "Good afternoon 🌤️", "Good evening 🌆"]
    # a dash after the emoji, not a stray ". "
    assert got["line"] == "Good evening 🌆 — new roles at the 5 companies you watch, best fit first."


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_a_slow_tab_shows_it_is_loading(tmp_path):
    """A tab that loads quickly never flickers a spinner; a slow one spins its button and dims the page until
    it's done; and when another tab is clicked meanwhile, the first one finishing doesn't clear the second's."""
    js = tmp_path / "loading.js"
    js.write_text("""
const button = name => { const c = new Set(); return { name, classList: { add: x => c.add(x), remove: x => c.delete(x),
  has: x => c.has(x) } }; };
const today = button("today"), queue = button("queue"), applied = button("applied"), all = [today, queue, applied];
const attrs = {};
const main = { setAttribute: (k, v) => { attrs[k] = v; }, removeAttribute: k => { delete attrs[k]; } };
const document = { querySelectorAll: () => all.filter(b => b.classList.has("loading")) };
let loads = 0;
""" + page_function("loading") + """
const wait = ms => new Promise(r => setTimeout(r, ms));
const state = () => ({ spinning: all.filter(b => b.classList.has("loading")).map(b => b.name),
  busy: !!attrs["aria-busy"] });
(async () => {
  const out = {};
  await loading(today, () => wait(10), 50);
  out.quick = state();
  const slow = loading(queue, () => wait(150), 50);
  await wait(90);
  out.slow = state();
  await slow;
  out.slowDone = state();
  const first = loading(queue, () => wait(120), 30);
  await wait(60);
  const second = loading(applied, () => wait(200), 30);
  await first;
  await wait(40);
  out.firstDone = state();
  await second;
  out.secondDone = state();
  console.log(JSON.stringify(out));
})();
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {
        "quick": {"spinning": [], "busy": False},
        "slow": {"spinning": ["queue"], "busy": True},
        "slowDone": {"spinning": [], "busy": False},
        "firstDone": {"spinning": ["applied"], "busy": True},  # the tab clicked second is still loading
        "secondDone": {"spinning": [], "busy": False},
    }


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_a_found_story_reads_without_its_block_and_saves_from_the_card(tmp_path):
    js = tmp_path / "story.js"
    js.write_text(page_function("storyShown") + page_function("storyFromForm") + """
const reply = "Here it is:\\n\\n```story\\n{\\"id\\": \\"x\\"}\\n```\\n\\nCheck it.";
console.log(JSON.stringify({
  shown: storyShown(reply), streaming: storyShown("Here it is:\\n```story\\n{\\"id\\": "),
  form: storyFromForm({ id: " x ", title: "T", did: "D", hard: "H", result: "R", skills: "Python, , on-call ",
    avoid: "Bind\\n\\n the old provider " }) }));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got["shown"] == "Here it is:\n\n\n\nCheck it." and got["streaming"] == "Here it is:"
    assert got["form"] == {"id": "x", "title": "T", "did": "D", "hard": "H", "result": "R",
                           "skills": ["Python", "on-call"], "avoid": ["Bind", "the old provider"]}


def test_an_applications_note_is_clamped_on_the_card():
    """A note that grows a dated entry at every step would push the card's buttons off screen; Details has it all."""
    page = resources.files("jobwatch").joinpath("static/index.html").read_text(encoding="utf-8")
    rule = re.search(r"^\.app \.note \{([^}]*)\}", page, re.M)
    assert rule and "-webkit-line-clamp: 3" in rule.group(1) and "overflow: hidden" in rule.group(1)
    assert 'h("div", { class: "note", title: "Details shows the whole note" }, a.note)' in page_function("appCard")


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_a_note_reads_as_its_dated_lines_newest_first(tmp_path):
    """The same split as prep.note_entries, for Details and the prep dialog."""
    note = "Spotted on a board (2031-03-02): hybrid. 2031-03-09: Recruiter is Priya Sol.\n2031-03-20:  Booked the call."
    js = tmp_path / "note.js"
    js.write_text(page_function("noteEntries") + f"\nconsole.log(JSON.stringify([noteEntries({json.dumps(note)}),"
                  " noteEntries(''), noteEntries(null)]));", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [[["2031-03-20", "Booked the call."], ["2031-03-09", "Recruiter is Priya Sol."],
                                     ["", "Spotted on a board (2031-03-02): hybrid."]], [], []]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_links_keep_the_pages_own_paths_and_fragments_but_not_script_schemes(tmp_path):
    """A prep sheet's link is a path on this page's own server and a jump link is a #fragment: both must survive
    safeUrl; javascript: and data: stay blocked, and a posting's https link is unchanged."""
    js = tmp_path / "links.js"
    js.write_text("const location = new URL('http://127.0.0.1:8765/');\n" + page_function("safeUrl") + """
const urls = ["/prep/s3cret/acme-onsite.html", "#settings", "#", "https://boards.example.com/jobs/1?a=b",
  "javascript:alert(1)", "data:text/html,hi", "ftp://example.com/x", "blob:http://127.0.0.1:8765/abc",
  "blob:http://evil.example/abc", "//evil.example/x"];
console.log(JSON.stringify(urls.map(safeUrl)));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [
        "http://127.0.0.1:8765/prep/s3cret/acme-onsite.html", "#settings", "#", "https://boards.example.com/jobs/1?a=b",
        "#", "#", "#", "blob:http://127.0.0.1:8765/abc", "#", "http://evil.example/x"]


def page_const(name: str) -> str:
    """One top-level const's source from the page's script (to the first line ending in ';' at its depth)."""
    page = resources.files("jobwatch").joinpath("static/index.html").read_text(encoding="utf-8")
    m = re.search(rf"^const {name} = .*?;$", page, re.S | re.M)
    assert m, f"no const {name} in the page"
    return m.group(0)


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_what_matters_most_sets_the_comps_weights(tmp_path):
    """Onboarding's "What matters most to you in a company?": the order picked becomes comps.weights, the parts left
    out share what's left, "I don't mind" keeps the defaults, and saved weights read back as the same order."""
    js = tmp_path / "matters.js"
    js.write_text("\n".join([page_const("MATTERS"), page_const("MATTER_SHARE"), page_function("mattersWeights"),
                             page_function("mattersOrder")]) + """
console.log(JSON.stringify({
  all: mattersWeights(["career", "health", "pay", "fit"]),
  two: mattersWeights(["career", "pay"]),
  any: mattersWeights(["any"]), none: mattersWeights([]),
  back: mattersOrder({comps: {weights: mattersWeights(["career", "health", "pay", "fit"])}}),
  dflt: mattersOrder({}),
}));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got["all"] == {"progress": 10, "career": 35, "health": 25, "pay": 20, "fit": 10}
    assert got["two"] == {"progress": 10, "career": 35, "pay": 25, "health": 15, "fit": 15}  # 20 + 10 shared
    assert got["any"] is None and got["none"] is None
    assert got["back"] == ["career", "health", "pay", "fit"] and got["dflt"] == []


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_how_you_want_to_work_reads_and_writes_the_places(tmp_path):
    """Onboarding's "How do you want to work?": remote only, hybrid or on-site near the places named, or either,
    read from filters.locations and written back; hybrid or on-site with no place is refused (no places would let
    every place through)."""
    js = tmp_path / "work.js"
    js.write_text("\n".join([page_function("workStyle"), page_function("workLocations")]) + """
let refused = "";
try { workLocations("near", []); } catch (e) { refused = e.message; }
console.log(JSON.stringify({
  read: [["remote"], ["Denver"], ["Denver", "remote"], []].map(workStyle),
  write: ["remote", "near", "either"].map(how => workLocations(how, ["Denver"])),
  refused,
}));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got["read"] == ["remote", "near", "either", "either"]
    assert got["write"] == [["remote"], ["Denver"], ["Denver", "remote"]]
    assert got["refused"] == "Name a city or state for hybrid or on-site jobs."


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_list_boxes_split_on_commas_but_not_a_patterns_own(tmp_path):
    """Settings' titles and "not in text" boxes take one per line or a comma list; a regex's own commas
    (`{0,40}`, `[,;]`, `\\,`) stay in it, or saving writes a broken pattern and the watchlist refuses it."""
    js = tmp_path / "unlines.js"
    js.write_text(page_function("unlines") + r"""
console.log(JSON.stringify([
  "Staff engineer, Principal engineer\n\nSecurity engineer ",
  "citizen\\b(?![^.\\n]{0,40}\\bgreen card)\n[,;] list\nsplit\\, not",
  "a), b",
].map(unlines)));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [
        ["Staff engineer", "Principal engineer", "Security engineer"],
        [r"citizen\b(?![^.\n]{0,40}\bgreen card)", "[,;] list", r"split\, not"],
        ["a)", "b"],  # a stray closer doesn't swallow later commas
    ]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_saving_settings_gives_back_every_list_as_it_was(tmp_path):
    """Each filter box shows its list one per line and saving reads it back: every list in the guide's example
    watchlist, and patterns with commas of their own, come back unchanged (a place keeps its ", CO")."""
    import yaml
    readme = (Path(__file__).resolve().parent.parent / "docs" / "guide" / "watchlist.md").read_text(encoding="utf-8")
    keys = {"titles": "unlines", "exclude_titles": "unlines", "exclude_text": "unlines",
            "exclude_departments": "unlines", "locations": "placeLines"}
    cases = [{"key": k, "list": yaml.safe_load(v)}
             for k, v in re.findall(rf"^\s+({'|'.join(keys)}): (\[.*?\])\s*(?:#.*)?$", readme, re.M)]
    assert {c["key"] for c in cases} >= {"exclude_text", "locations"}, "the guide's example watchlist moved"
    cases += [{"key": "exclude_text", "list": [r"citizen\b(?![^.\n]{0,40}\bgreen card)", r"\b0\s*[-–]\s*2 years\b"]},
              {"key": "locations", "list": ["remote", "Boulder, CO", "Austin, TX"]}]
    js = tmp_path / "roundtrip.js"
    js.write_text("\n".join([page_function("lines"), page_function("unlines"), page_function("placeLines")]) + f"""
const split = {{ unlines, placeLines }}, keys = {json.dumps(keys)};
console.log(JSON.stringify({json.dumps(cases)}.map(c => split[keys[c.key]](lines(c.list)))));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [c["list"] for c in cases]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_settings_sub_tabs_follow_the_url_hash_and_old_anchors(tmp_path):
    js = tmp_path / "tabs.js"
    js.write_text(page_const("SET_GROUPS") + "\n" + page_function("settingsGroupOf") + "\n"
                  + page_function("pageOfHash") + """
const TABS = ["today", "settings"];
const out = {
  groups: SET_GROUPS.map(g => g.id),
  cards: SET_GROUPS.flatMap(g => g.cards).sort(),
  hash: pageOfHash("#settings/ai", TABS), bare: pageOfHash("#settings", TABS), bad: pageOfHash("#settings/nope", TABS),
  today: pageOfHash("#today", TABS), anchor: pageOfHash("#set-pay", TABS), none: pageOfHash("#whatever", TABS),
  byCard: settingsGroupOf("prompts"),
};
console.log(JSON.stringify(out));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    # every settings card is in exactly one tab, so hiding the others never loses a field
    assert out["cards"] == sorted(["goals", "companies", "filters", "keywords", "today", "display", "resume", "prompts",
                                   "chat", "people", "pay", "alerts", "suggestions", "skills"])
    assert out["hash"] == {"tab": "settings", "sub": "ai"}
    assert out["bare"] == {"tab": "settings", "sub": None} and out["bad"] == {"tab": "settings", "sub": None}
    assert out["today"] == {"tab": "today", "sub": None}
    assert out["anchor"] == {"tab": "settings", "sub": "people", "card": "set-pay"}
    assert out["none"] is None and out["byCard"] == "ai"
