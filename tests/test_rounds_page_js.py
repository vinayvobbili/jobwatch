"""The rounds timeline's page script, run in node with a stand-in for the DOM helpers: how a round's time and day read,
the chip on the lists, and the markup of the timeline (done, next and later nodes, the empty state)."""

import json
import shutil
import subprocess

import pytest

from .test_page_js import page_function

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="needs node")

PRELUDE = """
const h = (tag, attrs, ...kids) => ({ tag, attrs: attrs || {},
  kids: kids.flat(Infinity).filter(k => k != null && k !== false) });
const icon = name => ({ tag: "svg", name });
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const fmtDay = (day, today) => { const [y, m, d] = day.split("-").map(Number); return `${MONTHS[m - 1]} ${d}`; };
const relDay = (day, today) => { const n = Math.round((Date.parse(day) - Date.parse(today)) / 86400000);
  return n === 0 ? "today" : n === 1 ? "tomorrow" : n > 0 ? `in ${n} days` : `${-n} days ago`; };
const text = n => typeof n === "string" ? n : [n.attrs?.class || "", ...(n.kids || []).map(text)].join(" ");
"""


def run_js(tmp_path, body):
    fns = "".join(page_function(n) for n in ("hhmm12", "roundTimes", "roundDayName", "roundWhen", "roundDots",
                                              "roundsChip", "roundNode", "roundsList", "roundsEmpty"))
    consts = "const ROUND_LOOK = {panel: ['users', '#5a5cf2'], '': ['chat', '#64748b']};" \
             "const roundLook = k => ROUND_LOOK[k] || ROUND_LOOK[''];" \
             "const roundClass = s => s === 'next' ? 'upnext' : s;" \
             "const roundWord = r => ({done: 'Done', held: 'Held', next: 'Next'}[r.state] || 'Later');"
    js = tmp_path / "rounds.js"
    js.write_text(PRELUDE + consts + fns + body, encoding="utf-8")
    r = subprocess.run(["node", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_times_and_days_read_plainly(tmp_path):
    got = run_js(tmp_path, """
console.log(JSON.stringify([hhmm12("00:00"), hhmm12("12:00"), hhmm12("14:30"), hhmm12(""),
  roundTimes({ time: "12:00", length: 60 }), roundTimes({ time: "23:30", length: 60 }), roundTimes({ time: "09:15" }),
  roundTimes({}), roundWhen({ day: "2026-11-30", time: "12:00", length: 60 }, "2026-11-27"),
  roundWhen({ day: "2026-11-18", time: "" }, "2026-11-27", false), roundWhen({ day: null }, "2026-11-27")]));
""")
    assert got == ["12 AM", "12 PM", "2:30 PM", "", "12 PM–1 PM", "11:30 PM–12:30 AM", "9:15 AM", "",
                   "Mon Nov 30 · 12 PM–1 PM · in 3 days", "Wed Nov 18", "Date not set yet"]


def test_the_chip_and_the_dots(tmp_path):
    got = run_js(tmp_path, """
const chip = roundsChip({ chip: "Round 3 of ? · next: Panel Mon Nov 30", dots: ["done", "done", "next"] });
console.log(JSON.stringify({ none: roundsChip(null), blank: roundsChip({ chip: null }), title: chip.attrs.title,
  dots: chip.kids[0].kids.map(k => k.attrs.class), words: text(chip).includes("Round 3 of ?") }));
""")
    assert got["none"] is None and got["blank"] is None and got["words"] is True
    assert got["dots"] == ["rd done", "rd done", "rd upnext", "rd later"]  # the dashed one is always last
    assert "aren't scheduled yet" in got["title"]


def test_the_timeline_has_done_next_and_the_later_node(tmp_path):
    got = run_js(tmp_path, """
const rs = { kinds: [{ id: "panel", help: "Several interviews in a row" }], typical: 4, items: [
  { id: 1, number: 1, kind: "panel", label: "Panel", state: "done", day: "2026-11-18", time: "", who: "Dana Lee",
    outcome: "Went well", inferred: true },
  { id: 2, number: 2, kind: "panel", label: "Panel", state: "next", day: "2026-11-30", time: "12:00", length: 60,
    text: "Bring a laptop" }] };
const ol = roundsList(rs, { today: "2026-11-27", j: {}, open: () => {} });
const lis = ol.kids;
console.log(JSON.stringify({ tag: ol.tag, label: ol.attrs["aria-label"], classes: lis.map(l => l.attrs.class),
  current: lis.map(l => l.attrs["aria-current"] || null), inferred: text(lis[0]).includes("inferred from your notes"),
  hint: text(lis[2]).includes("Typical, not confirmed: the posting says about 4 rounds"),
  later: text(lis[2]).includes("Later rounds: not scheduled yet"), nextText: text(lis[1]).includes("Bring a laptop"),
  empty: text(roundsEmpty()) }));
""")
    assert got["tag"] == "ol" and got["classes"] == ["rnode done", "rnode upnext", "rnode later"]
    assert got["current"] == [None, "step", None]  # the next one is the current step
    assert got["inferred"] and got["hint"] and got["later"] and got["nextText"]
    assert "Add the first round when you have an interview, or set a next step." in got["empty"]
