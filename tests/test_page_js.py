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
def test_today_words_a_stopped_backup(tmp_path):
    js = tmp_path / "late.js"
    js.write_text(page_function("backupLate") + """
console.log(JSON.stringify([backupLate(null), backupLate({ last: "2030-01-15" }), backupLate({ last: null })]));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [None, "Last backup 2030-01-15", "No backup found"]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_job_cards_show_their_rows_in_one_fixed_order(tmp_path):
    """Every job card has the same labeled rows in the same order: the five main ones always (a dash when empty, so
    each sits in the same place), Check and Note only when there is one. The place on the meta line is the first
    one with "+N more" and the whole list on hover."""
    js = tmp_path / "cards.js"
    js.write_text(page_const("CARD_ROWS") + page_const("hasKids") + page_const("none") + page_function("cardRows")
                  + page_function("placeSummary") + """
const h = (tag, attrs, ...kids) => ({ tag, kids: kids.flat(Infinity).filter(k => k != null && k !== false) });
const icon = name => ({ tag: "svg", name });
const labels = rows => rows.map(r => r.kids[0].kids[1]);
const empty = rows => rows.filter(r => r.kids[1].kids[0].kids?.[0] === "—").map(r => r.kids[0].kids[1]);
const some = cardRows({ people: "p", pay: ["$", null], gaps: null, note: [], why: false });
console.log(JSON.stringify({
  all: labels(cardRows({ note: "n", people: "p", skills: ["s"], gaps: "g", check: "c", why: "w", pay: "$" })),
  some: labels(some), dashed: empty(some), icon: some[0].kids[0].kids[0].name,
  none: labels(cardRows({})),
  one: placeSummary(["Boulder, CO"]), many: placeSummary(["Boulder, CO", "Austin, TX", "Remote"]), no: placeSummary([]),
}));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {
        "all": ["Pay", "Why", "Gaps", "Skills", "People", "Check", "Note"],
        "some": ["Pay", "Why", "Gaps", "Skills", "People"],
        "dashed": ["Why", "Gaps", "Skills"],
        "icon": "dollar",
        "none": ["Pay", "Why", "Gaps", "Skills", "People"],
        "one": {"first": "Boulder, CO", "more": 0, "full": "Boulder, CO"},
        "many": {"first": "Boulder, CO", "more": 2, "full": "Boulder, CO; Austin, TX; Remote"},
        "no": {"first": "", "more": 0, "full": ""},
    }


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_todays_quick_narrowing(tmp_path):
    jobs = {
        "remote": {"where": ["remote"], "fit": {"score": 82}, "salary_max": 260000, "age_days": 2},
        "city": {"where": ["onsite"], "fit": {"score": 65}, "salary_max": 180000, "age_days": 10},
        # not scored, no pay listed, no posting date
        "both": {"where": ["remote", "onsite"], "fit": None, "salary_max": None, "age_days": None},
        "nowhere": {"where": [], "fit": {"score": 50}, "salary_max": 300000, "age_days": 3},
    }
    views = {
        "off": {"where": "any", "fit": 0, "pay": 0, "posted": 0},
        "remote": {"where": "remote", "fit": 0, "pay": 0, "posted": 0},
        "onsite": {"where": "onsite", "fit": 0, "pay": 0, "posted": 0},
        "fit70": {"where": "any", "fit": 70, "pay": 0, "posted": 0},
        "pay250": {"where": "any", "fit": 0, "pay": 250000, "posted": 0},
        "week": {"where": "any", "fit": 0, "pay": 0, "posted": 3},
        "all": {"where": "remote", "fit": 80, "pay": 250000, "posted": 3},
    }
    js = tmp_path / "narrow.js"
    js.write_text(page_const("roleShown") + "\n" + page_function("quickNarrow") + f"""
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
        "fit70": ["remote"],                         # not scored yet is left out
        "pay250": ["remote", "both", "nowhere"],     # no listed pay still shows
        "week": ["remote", "both", "nowhere"],       # posted within 3 days; no date still shows
        "all": ["remote"],
    }


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_companies_can_be_filtered_and_ticked_or_unticked_all_at_once(tmp_path):
    """Today's Companies list has a search box, and All / None act on what it shows: every name, or the matches."""
    js = tmp_path / "facets.js"
    js.write_text(page_function("facetList") + """
const kept = kids => kids.flat(Infinity).filter(k => k != null && k !== false);
const h = (tag, attrs, ...kids) => ({ tag, ...(attrs || {}), kids: kept(kids) });
const fill = (el, ...kids) => { el.kids = kept(kids); };
const counts = { Initech: 3, Globex: 2, "Globex Labs": 1 }, calls = [];
const el = facetList(counts, () => "", () => {}, 12, { hidden: () => ({ Umbrella: 4, "Globex Retail": 1 }),
  onhide: () => {}, onshow: () => {},
  onhideall: n => calls.push(["hide", n]), onshowall: n => calls.push(["show", n]) });
const [tools, list] = el.kids, [search, all, none] = tools.kids;
const names = () => list.kids.filter(r => r.kids && r.kids.length === 3).map(r => r.kids[1].kids[0]);
const click = b => b.onclick({ currentTarget: b });
const shown = [names()];
search.value = "glob"; search.oninput();
shown.push(names());
click(none); click(all);
search.value = "zzz"; search.oninput();
const empty = list.kids.map(k => k.kids?.[0]).filter(t => typeof t === "string");
console.log(JSON.stringify({ shown, calls, empty }));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {
        "shown": [["Initech", "Globex", "Globex Labs", "Globex Retail", "Umbrella"],  # hidden ones last, A-Z
                  ["Globex", "Globex Labs", "Globex Retail"]],
        "calls": [["hide", ["Globex", "Globex Labs"]], ["show", ["Globex Retail"]]],
        "empty": ["No company matches"],
    }


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_an_old_open_role_isnt_called_new(tmp_path):
    """A company's roles all arrive as "new" when its board is first watched: one posted long ago says its age."""
    js = tmp_path / "status.js"
    js.write_text(page_const("STAGE_NAMES") + page_function("dayDiff") + page_function("companyStatus") + """
const t = "2026-10-31", word = (status, posted, max) => companyStatus({ status, posted }, t, max)[0];
console.log(JSON.stringify([word("new", "2026-10-20"), word("new", "2025-02-20"), word("shown", "2026-08-01"),
  word("new", null), word("rejected", "2025-02-20"), word("new", "2026-09-15", 60), word("new", "2026-09-15")]));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["New", "Posted 1y+ ago", "Posted 3mo ago", "New", "Rejected", "New",
                                    "Posted 2mo ago"]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_a_jobs_details_can_change_its_stage(tmp_path):
    """The job details open on a stage picker: any stage from queued to skipped (an application can be marked
    rejected right there), saved through /api/track, and the page behind redraws when the details close."""
    js = tmp_path / "facts.js"
    js.write_text(page_const("STAGE_NAMES") + page_const("DETAIL_STAGES") + page_function("detailsFacts") + """
const h = (tag, attrs, ...kids) => ({ tag, attrs, kids: kids.flat(Infinity).filter(k => k != null && k !== false) });
const calls = [], fmtDay = d => "day " + d, stageWords = (c, to) => `${c} ${to}`, TONES = {};
const api = async (path, body) => { calls.push([path, body]); return {}; };
const toast = () => {}, openDetails = key => calls.push(["open", key]), render = () => {};
let detailsDirty = false;
const job = { key: "k1", company: "Initech", status: "screening", applied_at: "2026-10-28T20:00:00", closed: null,
              first_seen: "2026-10-29T01:00:00" };
const strip = detailsFacts(job), sel = strip.kids[0].kids[1];
const options = sel.kids.map(o => o.attrs.value);
const tiles = strip.kids.slice(1).map(t => t.kids.map(k => k.kids[0]));
const fresh = detailsFacts({ ...job, status: "shown", applied_at: null }).kids[0].kids[1].kids[0];
sel.value = "rejected";
sel.onchange().then(() => console.log(JSON.stringify({ options, value: job.status, tiles, calls, detailsDirty,
  fresh: [fresh.attrs.value, fresh.kids[0]] })));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {
        "options": ["queued", "applied", "screening", "interviewing", "offer", "rejected", "withdrawn", "skipped",
                    "snoozed"],
        "value": "screening",
        "tiles": [["Applied", "day 2026-10-28"], ["First seen", "day 2026-10-29"]],
        "calls": [["/api/track", {"key": "k1", "status": "rejected"}], ["open", "k1"]],
        "detailsDirty": True,
        "fresh": ["shown", "Not acted on"],  # a job not acted on yet shows as that, then every stage to pick
    }


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_company_counts_follow_the_other_filters(tmp_path):
    """A company's count is what picking it shows: a fit filter that leaves its one job out takes it off the list,
    unless it's the company picked, which stays to be unpicked."""
    jobs = [
        {"company": "Initech", "title": "SRE", "keywords": ["python"], "fit": {"score": 85}, "where": []},
        {"company": "Initech", "title": "Data Engineer", "keywords": [], "fit": None, "where": []},
        {"company": "Globex", "title": "SRE", "keywords": ["python"], "fit": None, "where": []},
    ]
    base = {"q": "", "kws": [], "company": "", "where": "any", "fit": 0, "pay": 0, "posted": 0}
    views = {"off": base, "fit80": {**base, "fit": 80}, "picked": {**base, "fit": 80, "company": "Globex"},
             "search": {**base, "q": "data"}, "python": {**base, "kws": ["python"]}}
    js = tmp_path / "counts.js"
    js.write_text(page_const("roleShown") + "\n" + page_function("quickNarrow") + "\n" + page_function("companyCounts")
                  + f"""
const jobs = {json.dumps(jobs)}, views = {json.dumps(views)};
const out = {{}}, kept = {{Umbrella: 4}};
for (const [n, v] of Object.entries(views)) out[n] = companyCounts(jobs, {{...v, kws: new Set(v.kws)}});
out.kept = companyCounts(jobs, {{...views.fit80, kws: new Set()}}, kept);
console.log(JSON.stringify(out));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {
        "off": {"Initech": 2, "Globex": 1},
        "fit80": {"Initech": 1},
        "picked": {"Initech": 1, "Globex": 0},
        "search": {"Initech": 1},
        "python": {"Initech": 1, "Globex": 1},
        "kept": {"Initech": 1},  # refilled in place: old names go
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
def test_todays_picks_take_each_companys_best_job_before_a_second_one(tmp_path):
    js = tmp_path / "picks.js"
    js.write_text(page_function("spreadPicks") + r"""
const jobs = [["Globex", 1], ["Globex", 2], ["Globex", 3], ["Initech", 4], ["Umbrella", 5], ["Initech", 6]]
  .map(([company, id]) => ({ company, id }));
console.log(JSON.stringify([spreadPicks(jobs, 4).map(j => j.id), spreadPicks(jobs.slice(0, 3), 2).map(j => j.id)]));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [[1, 4, 5, 2], [1, 2]]  # one company only: its jobs in order


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_unticking_a_role_hides_only_the_jobs_that_are_only_that_kind(tmp_path):
    """Today's Roles: with software engineering unticked a security software engineer stays (security is still
    ticked), a plain software engineer goes, and a job from a server that sends no roles stays."""
    js = tmp_path / "roles.js"
    js.write_text(page_const("roleShown") + r"""
const jobs = [{ title: "Security Software Engineer", roles: ["security", "software"] },
              { title: "Staff Software Engineer", roles: ["software"] }, { title: "From an older server" }];
const shown = off => jobs.filter(j => roleShown(j, { rolesOff: new Set(off) })).map(j => j.title);
console.log(JSON.stringify([shown([]), shown(["software"]), shown(["software", "security"])]));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [
        ["Security Software Engineer", "Staff Software Engineer", "From an older server"],
        ["Security Software Engineer", "From an older server"],
        ["From an older server"],
    ]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_saving_settings_keeps_a_company_name_with_a_comma_whole(tmp_path):
    """Left-out companies and companies with an office near you are names, one per line: saving once split
    "Initech, Inc." into "Initech" and "Inc." (and the stray "Inc." matched nothing, or every Inc.)."""
    js = tmp_path / "companies.js"
    js.write_text("\n".join([page_function("unlines"), page_function("placeLines"), page_function("filterValues")])
                  + r"""
const box = value => ({ value }), names = "Initech, Inc.\nGlobex\nUmbrella, LLC";
const inp = { titles: box("engineer"), exclude: box(""), excludeText: box(""), excludeCompanies: box(names),
  locations: box("remote"), country: box(""), home: box(""), nearOffices: box(names), minPay: box(""),
  requirePay: { checked: false }, maxAge: box(""), minFit: box("") };
const f = filterValues(inp);
console.log(JSON.stringify([f.exclude_companies, f.nearby_offices]));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [["Initech, Inc.", "Globex", "Umbrella, LLC"]] * 2


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
    assert out["cards"] == sorted(["goals", "companies", "filters", "keywords", "today", "display", "resume", "usage",
                                   "prompts", "chat", "people", "pay", "alerts", "incoming", "suggestions", "skills",
                                   "applicant", "tailor", "extension"])
    assert out["hash"] == {"tab": "settings", "sub": "ai"}
    assert out["bare"] == {"tab": "settings", "sub": None} and out["bad"] == {"tab": "settings", "sub": None}
    assert out["today"] == {"tab": "today", "sub": None}
    assert out["anchor"] == {"tab": "settings", "sub": "people", "card": "set-pay"}
    assert out["none"] is None and out["byCard"] == "ai"


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_built_prep_sheet_opens_in_a_tab_opened_on_the_click(tmp_path):
    """The tab opens before the sheet is fetched (one opened after the wait would be blocked); when the fetch
    fails the tab closes again, and a blocked tab says so."""
    js = tmp_path / "prep_page.js"
    js.write_text(page_function("openPrepPage") + """
const log = [];
const toast = m => log.push(["toast", m]);
globalThis.URL.createObjectURL = () => "blob:sheet";
globalThis.URL.revokeObjectURL = () => {};
globalThis.setTimeout = () => {};
const tab = () => ({ document: {}, location: {}, close() { log.push(["closed"]); } });
globalThis.Blob = class { constructor(parts) { this.parts = parts; } };
(async () => {
  let opened;
  globalThis.window = { open: () => (opened = tab(), log.push(["open"]), opened) };
  globalThis.api = async url => { log.push(["api", url]); return { html: "<h1>Prep</h1>" }; };
  await openPrepPage("greenhouse:initech:1");
  log.push(["at", opened.location.href]);
  globalThis.api = async () => { throw new Error("no such job"); };
  await openPrepPage("greenhouse:initech:2");
  globalThis.window = { open: () => null };
  await openPrepPage("greenhouse:initech:3");
  console.log(JSON.stringify(log));
})();
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [
        ["open"], ["api", "/api/prep?key=greenhouse%3Ainitech%3A1"], ["at", "blob:sheet"],
        ["open"], ["closed"], ["toast", "no such job"],
        ["toast", "Couldn't open a new tab: your browser blocked it"]]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_tailor_result_line(tmp_path):
    js = tmp_path / "tailor.js"
    js.write_text(page_function("tailorResultLine") + """
console.log(JSON.stringify([
  tailorResultLine({ new: true, pages: 2, ok: true }), tailorResultLine({ new: false, pages: 1, ok: false }),
  tailorResultLine({ new: true, pages: null, ok: true })]));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["new · 2 pages · ok", "rebuilt · 1 page · needs a look", "new · ok"]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_a_jobs_pay_is_one_row_of_labelled_chips_and_empty_ones_say_why(tmp_path):
    """Posted, Levels, LCA, Recruiter, Glassdoor and Ask are one chip each, in that order; the LCA chip is short, an
    empty source is a dimmed chip showing its blank word with the reason on hover, and a job without sources (an
    older server) still gets the plain pay chip."""
    js = tmp_path / "pay.js"
    js.write_text(page_function("paySources") + """
const h = (tag, attrs, ...kids) =>
  ({ tag, attrs: attrs || {}, kids: kids.flat(Infinity).filter(k => k != null && k !== false) });
const chips = el => el.kids.map(c => [c.attrs.class, c.kids[0].kids[0], c.kids[1], c.attrs.title]);
const items = [
  { key: "posted", label: "Posted", value: "$150K–$196K", reason: null },
  { key: "levels", label: "Levels", value: null, blank: "TBD", reason: "refused today, asks again tomorrow" },
  { key: "lca", label: "LCA", value: "$165K median (14 filings)", short: "$165K med",
    detail: "H-1B filings: median $165K" },
  { key: "recruiter", label: "Recruiter", value: null, blank: "none", reason: "no recruiter figures kept" },
  { key: "ask", label: "Ask", value: "$180K" }];
const row = paySources({ key: "k", pay: "$150K–$196K", pay_sources: items });
console.log(JSON.stringify({ attrs: row.attrs, chips: chips(row), old: paySources({ pay: "$1K" }).kids,
  none: paySources({}) }));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got["attrs"] == {"class": "psrcs", "data-pay": "k"}
    assert got["chips"] == [
        ["psrc psrc-posted", "Posted", "$150K–$196K", "$150K–$196K"],
        ["psrc psrc-none", "Levels", "TBD", "refused today, asks again tomorrow"],
        ["psrc psrc-lca", "LCA", "$165K med", "H-1B filings: median $165K"],
        ["psrc psrc-none", "Recruiter", "none", "no recruiter figures kept"],
        ["psrc psrc-ask", "Ask", "$180K", "$180K"]]
    assert got["old"] == ["$1K"] and got["none"] is None


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_fit_scoring_cost_line_says_what_was_recorded_and_what_is_estimated(tmp_path):
    js = tmp_path / "usage.js"
    js.write_text(page_const("USD") + page_function("claudeCostText") + """
const none = { recorded_jobs: 0, estimated_jobs: 0, not_recorded_jobs: 0, unpriced: [] };
console.log(JSON.stringify({
  empty: claudeCostText(none),
  unknown: claudeCostText({ ...none, not_recorded_jobs: 1 }),
  recorded: claudeCostText({ ...none, recorded_jobs: 2, recorded_usd: 3, total_usd: 3 }),
  mixed: claudeCostText({ ...none, recorded_jobs: 1, recorded_usd: 1.5, estimated_jobs: 2, estimated_usd: 3,
    average_usd: 1.5, total_usd: 4.5, unpriced: ["claude-x"] }),
  tiny: claudeCostText({ ...none, recorded_jobs: 1, recorded_usd: 0.004, total_usd: 0.004 }).main,
}));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got["empty"] == {"main": "$0.00", "notes": []}
    assert got["unknown"] == {"main": "not recorded", "notes": [
        "1 score made before tokens were recorded: cost not recorded"]}
    assert got["recorded"] == {"main": "$3.00", "notes": ["$3.00 recorded for 2 scores"]}
    assert got["mixed"] == {"main": "$4.50 (partly estimated)", "notes": [
        "$1.50 recorded for 1 score", "$3.00 estimated for 2 earlier scores, at $1.50 each",
        "no price known for claude-x"]}
    assert got["tiny"] == "under $0.01"


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_work_wanted_most_leads_whichever_sort_is_picked(tmp_path):
    js = tmp_path / "focus.js"
    js.write_text(page_function("focusFirst") + """
const newest = [{ k: "a" }, { k: "b", focus: 1 }, { k: "c" }, { k: "d", focus: 1 }, { k: "e", focus: 2 }];
console.log(JSON.stringify(focusFirst(newest).map(j => j.k)));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["e", "b", "d", "a", "c"]  # more focus hits first; each part keeps the sort


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_a_notice_opens_activity_on_the_list_that_holds_it(tmp_path):
    """A strong fit is a scoring event: opening Activity from its notice shows the Scored list, not the Job Boards
    list picked last time, where every line reads "nothing new for you"."""
    js = tmp_path / "notices.js"
    js.write_text(page_const("ACT_KINDS") + page_function("actListFor") + """
console.log(JSON.stringify(["score", "pay", "mail", "boards", "something-else"].map(actListFor)));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ["score,pay,logos", "score,pay,logos", "mail", "boards", "boards"]
    page = resources.files("jobwatch").joinpath("static/index.html").read_text(encoding="utf-8")
    assert "notices.list = unseen.length ? actListFor(unseen[0].kind) : null;" in page
    assert "if (notices.list) { activityView.kind = notices.list; notices.list = null; }" in page
