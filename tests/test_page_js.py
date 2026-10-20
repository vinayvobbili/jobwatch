import json
import re
import shutil
import subprocess
from importlib import resources

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
    """One top-level function's source from the page's script (it ends at the first closing brace in column 0)."""
    page = resources.files("jobwatch").joinpath("static/index.html").read_text(encoding="utf-8")
    m = re.search(rf"^(?:async )?function {name}\(.*?^}}$", page, re.S | re.M)
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
                  + page_function("greeting") + """
const stages = ["screening", "interviewing", "offer", "rejected", "withdrawn", "applied", "someday"];
console.log(JSON.stringify({ words: Object.fromEntries(stages.map(s => [s, stageWords("Acme", s)])),
  hello: [3, 9, 14, 20].map(greeting) }));
""", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got["words"]["rejected"] == "🌱 Acme passed. Their loss. Onward."
    assert got["words"]["withdrawn"] == "Withdrawn from Acme. Good call: your time is worth protecting."
    assert got["words"]["offer"].startswith("🥂")
    assert got["words"]["someday"] == "Acme: marked someday."  # a stage with no words of its own still says something
    assert got["hello"] == ["Burning the midnight oil 🌙", "Good morning ☀️", "Good afternoon 🌤️", "Good evening 🌆"]


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
