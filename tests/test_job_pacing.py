# ruff: noqa: E501  (JavaScript cases as one-liners)
"""Import this list pages like a person (job-lists.js PACING) and passive mode keeps each seen job once
(chrome-extension/passive.js), both run with node against made-up data."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

EXT = Path(__file__).resolve().parent.parent / "chrome-extension"
needs_node = pytest.mark.skipif(not shutil.which("node"), reason="needs node")


def run_js(tmp_path, body: str):
    js = tmp_path / "case.js"
    js.write_text(f"const L = require({json.dumps(str(EXT / 'job-lists.js'))});\n"
                  f"const P = require({json.dumps(str(EXT / 'passive.js'))});\n{body}", encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


FAKE_PAGE = """
// A results box already at its end, and (when `next` is given) a Next button that does nothing.
const box = { scrollTop: 0, clientHeight: 100, scrollHeight: 100 };
const calls = [];
const sleeps = [];
const fakeNext = { disabled: false, getAttribute: () => null, click: () => calls.push(['click', sleeps.length]) };
const doc = (next) => ({
  scrollingElement: box, documentElement: box, body: {},
  querySelectorAll: () => [],
  querySelector: (sel) => (next && sel === '[data-testid="pagination-page-next"]' ? fakeNext : null),
});
const opts = (extra) => ({ source: 'linkedin', sleep: async (ms) => { sleeps.push(ms); }, random: () => 0.5, ...extra });
"""


@needs_node
def test_defaults_are_a_slow_human_and_four_pages(tmp_path):
    out = run_js(tmp_path, "console.log(JSON.stringify({ p: L.PACING, n: L.DEFAULT_MAX_PAGES }));")
    assert out["n"] == 4
    assert out["p"]["scrollMs"] == [1500, 4000] and out["p"]["nextMs"] == [4000, 9000]


@needs_node
def test_scroll_steps_pause_a_random_1_5_to_4_seconds(tmp_path):
    out = run_js(tmp_path, FAKE_PAGE + """
(async () => {
  const lo = []; const hi = [];
  await L.readPage({ ...opts(), doc: doc(false), random: () => 0 }).then(() => {});
  lo.push(...sleeps.splice(0));
  await L.readPage({ ...opts(), doc: doc(false), random: () => 1 });
  hi.push(...sleeps.splice(0));
  console.log(JSON.stringify({ lo, hi }));
})();""")
    assert out["lo"] and set(out["lo"]) == {1500}
    assert out["hi"] and set(out["hi"]) == {4000}


@needs_node
def test_next_waits_4_to_9_seconds_before_it_is_pressed(tmp_path):
    out = run_js(tmp_path, FAKE_PAGE + """
(async () => {
  const moved = await L.next({ ...opts(), doc: doc(true) });
  console.log(JSON.stringify({ moved, first: sleeps[0], calls }));
})();""")
    assert out["first"] == 6500  # the midpoint of 4000..9000
    assert out["calls"] == [["click", 1]]  # one pause was already spent when Next was pressed
    assert out["moved"] is False  # no new cards ever came


@needs_node
def test_pacing_can_be_overridden_per_call_and_max_pages_is_an_option(tmp_path):
    out = run_js(tmp_path, FAKE_PAGE + """
(async () => {
  await L.readAll({ ...opts({ pacing: { scrollMs: [10, 10] } }), doc: doc(false), maxPages: 2 });
  console.log(JSON.stringify({ sleeps, pages: L.lastRun.pages }));
})();""")
    assert set(out["sleeps"]) == {10} and out["pages"] == 1  # no Next button: it stops at one page


@needs_node
def test_a_page_cap_stops_before_the_next_press(tmp_path):
    out = run_js(tmp_path, FAKE_PAGE + """
(async () => {
  await L.readAll({ ...opts(), doc: doc(true), maxPages: 1 });
  console.log(JSON.stringify({ calls, pages: L.lastRun.pages }));
})();""")
    assert out["calls"] == [] and out["pages"] == 1


@needs_node
def test_passive_store_keeps_each_job_once_and_the_latest_read(tmp_path):
    out = run_js(tmp_path, """
const a = { source: 'linkedin', id: '4100000001', title: 'Platform Engineer', company: 'Initech', location: '', pay: '', posted: '' };
const b = { source: 'indeed', id: '4100000001', title: 'Platform Engineer', company: 'Globex', location: '', pay: '', posted: '' };
const a2 = { ...a, pay: '$120K/yr' };
const first = P.merge({}, [a, b, a, { source: 'linkedin', id: '' }, null], 1000);
const second = P.merge(first.store, [a2, { ...b, id: '77' }], 2000);
console.log(JSON.stringify({ first, second, recs: P.records(second.store), input: first.store }));""")
    assert out["first"]["added"] == 2 and sorted(out["first"]["store"]) == ["indeed:4100000001", "linkedin:4100000001"]
    assert out["second"]["added"] == 1  # a2 is a job already kept
    assert out["second"]["store"]["linkedin:4100000001"]["pay"] == "$120K/yr"
    assert out["second"]["store"]["linkedin:4100000001"]["seenAt"] == 1000  # first sight is kept
    assert len(out["input"]) == 2  # merge does not change the store it was given
    recs = out["recs"]
    assert len(recs) == 3 and all("seenAt" not in r for r in recs)  # as import-list takes them


@needs_node
def test_passive_store_drops_the_oldest_past_its_cap(tmp_path):
    out = run_js(tmp_path, """
const recs = Array.from({ length: P.MAX_KEPT + 5 }, (_, i) => ({ source: 'linkedin', id: String(i + 1), title: 't', company: 'Initech' }));
const { store } = P.merge({}, recs, 1);
const keys = Object.keys(store);
console.log(JSON.stringify({ n: keys.length, first: keys[0], max: P.MAX_KEPT }));""")
    assert out["n"] == out["max"] and out["first"] == "linkedin:6"
