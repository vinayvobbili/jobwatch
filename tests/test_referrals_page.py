# ruff: noqa: F811, E501  (a test's `page` argument is the fixture imported from test_browser; the node scripts keep the page's long lines)
"""The Referrals tab's company cards, search and dialog (static/index.html). The pure pieces (what counts as a good fit, the
companies the people group into, who comes first, the card's counts and words, the best five, the search, sorts and filters,
the dialog's tabs) run in node with a stub of the page's h(); the cards, dialog and search box run in a real browser
(Playwright, skipped where it isn't installed), and the card edge's contrast against the page is computed from the page's
colour tokens. All people, companies and jobs are made up."""

import colorsys
import json
import re
import shutil
import subprocess

import pytest

from jobwatch import config
from jobwatch.score import resume_id
from jobwatch.store import Store

from .test_browser import FILTERS, browser, page, sync_api, watchlist  # noqa: F401 (fixtures)
from .test_close_chip import PAGE, contrast, rgba
from .test_page_js import page_const, page_function

node = pytest.mark.skipif(not shutil.which("node"), reason="needs node")

PIECES = [page_const(n) for n in ("REF_LIVE", "REF_TOP", "REF_CAP", "REF_FURTHEST", "REF_SORTS", "REF_TABS", "REF_TAB_NAMES", "byFit",
                                  "refGood", "refLast", "refFirstTab", "refAccent", "refWhy", "MONTHS", "refHays", "refFolds", "refNoOpenings", "refHidden")] \
    + [page_function(n) for n in ("foldChar", "foldText", "searchTokens", "personMatches", "markRanges", "marked", "plural",
                                  "refLabels", "refSummary", "refEntries", "refPeopleOrder", "refCompanies", "refVisible", "refCount",
                                  "refPeopleWords", "refListJobs")]

STUBS = """
const h = (tag, attrs, ...kids) => ({ tag, attrs: attrs || {}, kids: kids.flat(Infinity).filter(k => k != null && k !== false) });
const text = n => typeof n === "object" ? n.kids.map(text).join("") : String(n);
const J = (key, title, status, fit, seen, more = {}) => ({ key, title, company: "Initech", status, fit, stale: false, off: false, place: "Remote", pay: "", seen, ...more });
// the fit minimum is 70 in these: good fits are d b g a j (by their scores), the queued f and the applied i; e scores 95 but its title is off-target
const jobs = [
  J("a", "Platform Engineer", "new", 72, "2030-01-05"), J("b", "Data Engineer", "new", 91, "2030-01-02"),
  J("c", "Security Analyst", "new", null, "2030-01-09"), J("d", "SRE", "new", 91, "2030-01-08"),
  J("e", "Support Engineer", "new", 95, "2030-01-10", { off: true }), J("f", "ML Engineer", "queued", 55, "2030-01-01"),
  J("g", "Backend Engineer", "new", 88, "2030-01-03"), J("h", "Intern", "new", null, "2030-01-04"),
  J("i", "Staff Engineer", "applied", null, "2030-01-06"), J("j", "QA Engineer", "new", 70, "2030-01-07"),
];
const person = (key, name, company, position, more = {}) => ({ key, name, company, position, verdict: "", note: "", why: "", url: "", from_file: false, strength: 0, jobs: [], ...more });
"""


def run(body: str):
    r = subprocess.run(["node", "-e", "\n".join(PIECES) + STUBS + body], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@node
def test_a_good_fit_is_a_job_in_hand_or_a_fit_at_the_minimum_never_an_unscored_or_off_target_one():
    out = run("""
const s = refSummary(jobs, 70);
console.log(JSON.stringify({ top: s.top.map(j => j.key), total: s.total, good: s.good, more: s.more, unscored: s.unscored, best: s.best,
  good70: jobs.filter(j => refGood(j, 70)).map(j => j.key).join(""), good0: jobs.filter(j => refGood(j, 0)).map(j => j.key).join("") }));""")
    # d (91, the newer), b (91), g (88) are the three best, a card showing three; a (72), j (70), f (queued) and i (applied) are good
    # fits too, a job you are working needing no score; e (95) is off-target and c, h have no score: none of those three counts
    assert out["top"] == ["d", "b", "g"]
    assert out["good70"] == "abdfgij" and out["good0"] == "abdfgij"  # no minimum doesn't make an unscored job one
    assert out == {**out, "total": 10, "good": 7, "more": 4, "unscored": 3, "best": 91}


@node
def test_a_job_you_are_working_is_a_good_fit_below_the_minimum_and_sorts_by_fit_then_unscored():
    out = run("""
const few = jobs.filter(j => ["e", "f", "i", "h", "c"].includes(j.key));
const s = refSummary(few, 70);
console.log(JSON.stringify({ top: s.top.map(j => j.key), more: s.more, unscored: s.unscored, best: s.best }));""")
    # f (queued, 55) before i (applied, unscored); e is off-target and c, h have no score
    assert out == {"top": ["f", "i"], "more": 0, "unscored": 3, "best": 55}


@node
def test_a_person_with_no_jobs_or_no_good_fit_has_an_empty_summary():
    out = run("""
const none = refSummary(jobs.filter(j => ["c", "h", "e"].includes(j.key)), 70);
console.log(JSON.stringify({ empty: refSummary([], 70), none: { good: none.good, best: none.best, stage: none.stage, unscored: none.unscored } }));""")
    assert out["empty"] == {"total": 0, "open": 0, "good": 0, "top": [], "more": 0, "unscored": 0, "best": -1, "stage": None}
    assert out["none"] == {"good": 0, "best": -1, "stage": None, "unscored": 2}


@node
def test_each_jobs_fit_place_pay_day_and_title_check_come_from_the_details_by_key():
    out = run("""
const d = { min_fit: 80, people: [person("p1", "Ana Li", "Initech", "Staff Engineer", { jobs: [
  { key: "k1", title: "Platform Engineer", company: "Initech", status: "new" }, { key: "k2", title: "SRE", company: "Initech", status: "queued" }] })],
  details: { k1: { fit: 85, stale: false, place: "Austin", pay: "$150K", seen: "2030-02-01", off: false } } };
const c = refCompanies(d)[0];
console.log(JSON.stringify({ k1: c.jobs[0], k2: c.jobs[1], top: c.sum.top.map(j => j.key), cut: c.cut, dflt: refCompanies({ ...d, min_fit: 0 })[0].cut }));""")
    assert out["k1"] == {"fit": 85, "stale": False, "place": "Austin", "pay": "$150K", "seen": "2030-02-01", "off": False,
                         "closed": False, "key": "k1", "title": "Platform Engineer", "company": "Initech", "status": "new"}
    assert out["k2"]["fit"] is None and out["k2"]["place"] == "" and out["k2"]["off"] is False and out["top"] == ["k1", "k2"]
    assert out["cut"] == 80 and out["dflt"] == 60  # an older server sends none


# Four companies from eleven people. Initech has six (Cy was chosen to ask first, Ana and Ed messaged you, Bo endorsed you; Di and
# Fay left no trace) and one of them lists the employer as "Initech Inc". Amazon's two say "Amazon" and "Amazon Web Services (AWS)".
# Globex has two and no good fit (60 is under the 70 minimum); Umbrella's only job is queued, unscored.
PEOPLE = """
const jk = (key, title, company, status = "new") => ({ key, title, company, status });
const IN = [jk("a1", "Platform Engineer", "Initech"), jk("a2", "Data Engineer", "Initech"), jk("a3", "SRE", "Initech")];
const AM = [jk("z1", "ML Engineer", "Amazon")], GL = [jk("g1", "Support Engineer", "Globex")], UM = [jk("u1", "QA Engineer", "Umbrella", "queued")];
const D = { min_fit: 70, details: { a1: { fit: 90, seen: "2030-01-05" }, a2: { fit: 75, seen: "2030-01-04" }, a3: {}, z1: { fit: 95, seen: "2030-01-06" },
  g1: { fit: 60, seen: "2030-01-03" }, u1: {} }, people: [
  person("p1", "Ana Li", "Initech", "Staff Engineer", { why: "messaged 9×, last 2026-06-23", strength: 9, jobs: IN }),
  person("p2", "Bo Chen", "Initech", "Recruiter", { why: "endorsed you 1×", strength: 1, jobs: IN }),
  person("p3", "Cy Diaz", "Initech Inc", "Platform Engineer", { verdict: "use", jobs: IN }),
  person("p4", "Di Evans", "Initech", "Analyst", { jobs: IN }),
  person("p5", "Ed Fox", "Initech", "Designer", { why: "messaged 2×, last 2026-01-02", strength: 2, jobs: IN }),
  person("p6", "Fay Gale", "Initech", "Copy Editor", { jobs: IN }),
  person("p7", "Pat Quinn", "Amazon", "Manager", { jobs: AM }),
  person("p8", "Rae Shaw", "Amazon Web Services (AWS)", "Architect", { jobs: AM }),
  person("p9", "José Núñez", "Globex Corporation", "Engineering Manager", { why: "messaged 3×, last 2026-05-01", strength: 3, jobs: GL }),
  person("p10", "Kay Lin", "Globex Corporation", "Recruiter", { jobs: GL }),
  person("p11", "Gus Hill", "Umbrella Labs", "Analyst", { jobs: UM }),
] };
const cos = refCompanies(D);
const names = list => list.map(c => c.name);
const find = (q, extra = {}) => refVisible(cos, { q, sort: "fit", ...extra });
const who = c => c.shown.map(p => p.name);
"""


@node
def test_people_who_share_a_tracked_job_are_one_company_whatever_their_employer_says():
    out = run(PEOPLE + """
const bridge = refCompanies({ min_fit: 70, details: {}, people: [
  person("x", "Xi", "One", "", { jobs: [jk("k1", "SRE", "One")] }), person("y", "Yo", "Two", "", { jobs: [jk("k2", "SRE", "Two")] }),
  person("z", "Zed", "One Two", "", { jobs: [jk("k1", "SRE", "One"), jk("k2", "SRE", "Two")] })] });
const none = refCompanies({ min_fit: 70, details: {}, people: [person("n", "Nan", "Hooli", ""), person("o", "Oz", "HOOLI", "")] });
console.log(JSON.stringify({ names: names(cos), people: cos.map(c => c.people.length), jobs: cos.map(c => c.jobs.length),
  amazon: cos.find(c => c.name === "Amazon").people.map(p => p.company), bridge: [bridge.length, bridge[0].people.length, bridge[0].jobs.length],
  none: none.map(c => [c.name, c.people.length]) }));""")
    assert out["names"] == ["Initech", "Amazon", "Globex", "Umbrella"]  # the name its jobs carry, not "Globex Corporation"
    assert out["people"] == [6, 2, 2, 1] and out["jobs"] == [3, 1, 1, 1]
    assert out["amazon"] == ["Amazon", "Amazon Web Services (AWS)"]
    assert out["bridge"] == [1, 3, 2]  # someone at both joins them
    assert out["none"] == [["Hooli", 2]]  # with no jobs at all, the employer's name groups them


@node
def test_the_people_at_a_company_come_closest_first_and_only_three_show_with_the_rest_counted():
    out = run(PEOPLE + """
const ini = cos[0], tooMany = { ...ini, shown: ini.people }, five = { ...ini, shown: ini.people.slice(0, 5) };
console.log(JSON.stringify({ order: ini.people.map(p => p.name), words: [refPeopleWords(tooMany), refPeopleWords(five), refPeopleWords({ ...ini, shown: ini.people.slice(0, 3) }),
  refPeopleWords({ ...cos[3], shown: cos[3].people })], cap: REF_CAP }));""")
    # asked first, then those who messaged or endorsed you (the latest first, an endorsement with no day after the dated ones), then A-Z
    assert out["order"] == ["Cy Diaz", "Ana Li", "Ed Fox", "Bo Chen", "Di Evans", "Fay Gale"]
    assert out["cap"] == 3
    assert out["words"] == [{"known": "6 people you know", "more": "+ 3 more people", "all": "See the 6 people"},
                            {"known": "6 people you know", "more": "+ 2 more people", "all": "See the 6 people"},
                            {"known": "6 people you know", "more": None, "all": "See the 6 people"},
                            {"known": "1 person you know", "more": None, "all": "See the person"}]


@node
def test_a_company_with_no_open_posting_is_hidden_on_request_unless_an_application_is_in_flight_and_the_count_says_so():
    out = run(PEOPLE + """
const closed = { fit: 80, closed: true };
const qs = refCompanies({ min_fit: 70, details: { c1: closed, c2: closed, c3: closed, c4: { fit: 80 } }, people: [
  person("a", "Ann", "Hooli", "", { jobs: [jk("c1", "SRE", "Hooli")] }),             // its one posting is closed: no openings
  person("b", "Bob", "Stark", "", { jobs: [jk("c2", "SRE", "Stark", "applied")] }),  // applied, then the posting closed: stays
  person("c", "Cat", "Wayne", "", { jobs: [jk("c3", "SRE", "Wayne", "queued")] }),   // queued, then closed: stays
  person("d", "Dan", "Pied Piper", "", { jobs: [jk("c4", "SRE", "Pied Piper")] }),   // open
  person("e", "Eve", "Gone", "")] });                                                // no job tracked at all: no openings
const base = { q: "", sort: "name" };
console.log(JSON.stringify({ quiet: qs.filter(refNoOpenings).map(c => c.name), all: names(refVisible(qs, base)),
  hidden_on: names(refVisible(qs, { ...base, noOpen: true })), hidden: names(refHidden(qs, { ...base, noOpen: true })),
  searched: names(refHidden(qs, { ...base, q: "hooli", noOpen: true })), other: names(refHidden(qs, { ...base, q: "wayne", noOpen: true })),
  line: [refCount([], 5), refCount(refVisible(qs, base), 5, 2), refCount([], 1, 1)],
  open: qs.map(c => c.sum.open) }));""")
    assert sorted(out["quiet"]) == ["Gone", "Hooli"]
    assert out["all"] == ["Gone", "Hooli", "Pied Piper", "Stark", "Wayne"]  # off: nothing is hidden
    assert out["hidden_on"] == ["Pied Piper", "Stark", "Wayne"]  # on: the in-flight companies stay, closed postings or not
    assert out["hidden"] == ["Gone", "Hooli"]
    assert out["searched"] == ["Hooli"] and out["other"] == []  # what a search matches that the filter hides; a kept company is not
    assert out["line"] == ["0 of 5 companies · 0 people", "5 of 5 companies · 5 people (2 hidden: no openings)", "0 of 1 company · 0 people (1 hidden: no openings)"]


@node
def test_the_search_matches_name_company_and_title_in_any_order_ignoring_case_and_accents_and_keeps_the_card():
    out = run(PEOPLE + """
console.log(JSON.stringify({ name: find("nunez").map(who), accents: find("JOSÉ núñez").map(who), order: find("li ana").map(who),
  company: find("initech").map(c => [c.name, c.shown.length]), twoWords: find("platform initech").map(who), title: find("recruiter").map(c => [c.name, who(c)]),
  none: find("xyz").length, empty: find("   ").length, several: find("engineer").map(c => c.name),
  both: find("amazon").map(who), aws: find("aws").map(who), nameOnly: find("globex").map(who) }));""")
    assert out["name"] == out["accents"] == [["José Núñez"]]  # the card stays, with only the person who matched
    assert out["order"] == [["Ana Li"]]
    assert out["company"] == [["Initech", 6]]
    assert out["twoWords"] == [["Cy Diaz"]]  # the company and the title, together
    assert out["title"] == [["Initech", ["Bo Chen"]], ["Globex", ["Kay Lin"]]]
    assert out["none"] == 0 and out["empty"] == 4
    assert out["several"] == ["Initech", "Globex"]  # Cy's Platform Engineer, and José's Engineering Manager
    assert out["both"] == [["Pat Quinn", "Rae Shaw"]]  # the card's own name counts for both, though one's employer is "Amazon Web Services (AWS)"
    assert out["aws"] == [["Rae Shaw"]]
    assert out["nameOnly"] == [["José Núñez", "Kay Lin"]]


@node
def test_the_search_marks_what_it_matched_in_the_original_text():
    out = run("""
const parts = marked("José Núñez at Globex", searchTokens("nunez glo"));
console.log(JSON.stringify({ marks: parts.filter(p => typeof p === "object").map(text), all: parts.map(text).join(""),
  ranges: markRanges("Initech Initech", ["init"]), merged: markRanges("Ana Li", ["an", "na"]), none: marked("Ana", []).map(text) }));""")
    assert out["marks"] == ["Núñez", "Glo"] and out["all"] == "José Núñez at Globex"
    assert out["ranges"] == [[0, 4], [8, 12]] and out["merged"] == [[0, 3]] and out["none"] == ["Ana"]


@node
def test_the_companies_sort_by_fit_good_fits_people_or_last_message_and_the_filters_and_counts_are_as_named():
    out = run(PEOPLE + """
const by = sort => names(find("", { sort }));
console.log(JSON.stringify({ sorts: Object.entries(REF_SORTS), fit: by("fit"), count: by("count"), people: by("people"), recent: by("recent"),
  name: by("name"), ask: find("", { ask: true }).map(who), working: names(find("", { working: true })),
  both: find("initech", { working: true, ask: true }).length, noMatch: cos.filter(c => !c.sum.good).map(c => c.name),
  counts: [refCount(find(""), 4), refCount(find("", { ask: true }), 4), refCount(find("nunez"), 4), refCount(find("xyz"), 4),
    refCount(find("", { sort: "fit" }).slice(0, 1), 1), refCount(find("", { working: true }), 4)] }));""")
    assert out["sorts"] == [["fit", "Best fit first"], ["count", "Most good fits"], ["people", "Most people you know"],
                            ["recent", "Last messaged"], ["name", "A-Z"]]  # Best fit first is the default
    assert out["fit"] == ["Amazon", "Initech", "Umbrella", "Globex"]  # the best good job: 95, 90, a queued job with no score, none at all
    assert out["count"] == ["Initech", "Amazon", "Umbrella", "Globex"]  # 2, 1 and 1 (the better fit first), 0
    assert out["people"] == ["Initech", "Amazon", "Globex", "Umbrella"]  # 6, 2, 2 (the better fit first), 1
    assert out["recent"] == ["Initech", "Globex", "Amazon", "Umbrella"]  # Jun 2026, May 2026, then never
    assert out["name"] == ["Amazon", "Globex", "Initech", "Umbrella"]
    assert out["ask"] == [["Cy Diaz"]] and out["working"] == ["Umbrella"] and out["both"] == 0
    assert out["noMatch"] == ["Globex"]
    assert out["counts"] == ["4 of 4 companies · 11 people", "1 of 4 companies · 1 person", "1 of 4 companies · 1 person",
                             "0 of 4 companies · 0 people", "1 of 1 company · 2 people", "1 of 4 companies · 1 person"]


@node
def test_the_dialogs_tabs_search_and_sort():
    out = run("""
const keys = o => refListJobs(jobs, { cut: 70, ...o }).map(j => j.key).join("");
console.log(JSON.stringify({ good: keys({ tab: "good", sort: "fit" }), dflt: keys({ sort: "fit" }), working: keys({ tab: "working", sort: "fit" }),
  unscored: keys({ tab: "unscored", sort: "fit" }), all: keys({ tab: "all", sort: "fit" }), newest: keys({ tab: "all", sort: "new" }),
  title: keys({ tab: "all", sort: "title" }), search: keys({ tab: "good", sort: "fit", q: "ENGINEER eng" }),
  stage: keys({ tab: "all", sort: "fit", q: "queued" }), none: keys({ tab: "all", sort: "fit", q: "zzz" }),
  first: [refFirstTab(jobs, 70), refFirstTab(jobs.filter(j => ["c", "h"].includes(j.key)), 70), refFirstTab(jobs.filter(j => ["e", "c"].includes(j.key)), 70),
    refFirstTab(jobs.filter(j => j.key === "e"), 70), refFirstTab([], 70), refFirstTab(jobs.filter(j => j.key === "i"), 70)],
  names: Object.values(REF_TAB_NAMES) }));""")
    assert out["good"] == out["dflt"] == "dbgajfi"  # 91 (the newer d first) 91 88 72 70, then the queued f and the applied i
    assert out["working"] == "fi" and out["unscored"] == "cih"  # no score yet, the newest first
    assert out["all"] == "edbgajfcih"  # off-target e (95) is in All, among the rest
    assert out["newest"] == "ecdjiahgbf"
    assert out["title"] == "gbhfajcdie"  # Backend Data Intern ML Platform QA Security SRE Staff Support
    assert out["search"] == "bgajfi"  # both words anywhere in the title, place, pay or stage
    assert out["stage"] == "f" and out["none"] == ""
    # a person opens on Good fits; with none, on the first tab that holds a job
    assert out["first"] == ["good", "unscored", "unscored", "all", "good", "good"]
    assert out["names"] == ["Good fits", "Applied and queued", "Not scored", "All"]


@node
def test_counts_read_as_one_or_many_never_1_jobs():
    out = run("""
const sum = (total, good, unscored = 0, more = 0) => ({ total, good, unscored, more });
console.log(JSON.stringify({ plural: [plural(0, "job"), plural(1, "job"), plural(2, "job"), plural(1, "person", "people"), plural(3, "person", "people")],
  one: refLabels(sum(1, 1)), two: refLabels(sum(2, 2)), many: refLabels(sum(313, 12, 262, 7)), none: refLabels(sum(313, 0, 262)),
  noneOne: refLabels(sum(1, 0, 1)) }));""")
    assert out["plural"] == ["0 jobs", "1 job", "2 jobs", "1 person", "3 people"]
    assert out["one"] == {"good": "1 good fit", "unscored": None, "of": None, "more": None, "button": "See the good fit"}
    assert out["two"] == {"good": "2 good fits", "unscored": None, "of": None, "more": None, "button": "See the 2 good fits"}
    assert out["many"] == {"good": "12 good fits", "unscored": "262 not scored yet", "of": "of 313 open", "more": "+ 7 more", "button": "See the 12 good fits"}
    assert out["none"] == {"good": "No good fit yet", "unscored": "262 not scored yet", "of": "of 313 open", "more": None, "button": "See all 313 jobs"}
    assert out["noneOne"]["button"] == "See the job" and out["noneOne"]["unscored"] == "1 not scored yet"


@node
def test_a_card_takes_the_accent_of_the_furthest_job_you_are_working():
    out = run("""
const stage = statuses => refSummary(statuses.map((s, i) => J("k" + i, "Engineer", s, null, "2030-01-01")), 70).stage;
console.log(JSON.stringify({ none: stage(["new", "shown"]), queued: stage(["new", "queued"]), applied: stage(["queued", "applied", "new"]),
  furthest: stage(["applied", "interviewing", "screening"]), offer: stage(["interviewing", "offer"]), empty: stage([]),
  classes: ["queued", "applied", "interviewing", "offer", null].map(refAccent) }));""")
    assert out["none"] is None and out["queued"] == "queued" and out["applied"] == "applied"
    assert out["furthest"] == "interviewing" and out["offer"] == "offer" and out["empty"] is None
    assert out["classes"] == ["live live-queued", "live live-working", "live live-working", "live live-working", ""]


@node
def test_a_date_in_why_is_a_month_and_a_year():
    out = run("console.log(JSON.stringify([refWhy('messaged 9×, last 2026-06-23'), refWhy('')]));")
    assert out == ["messaged 9×, last Jun 2026", "no messages or endorsements in your data"]


def all_tokens(selector: str) -> dict[str, str]:
    """The --name: value pairs of every CSS rule for this selector, later ones winning."""
    found: dict[str, str] = {}
    for block in re.finditer(rf"^{re.escape(selector)}\s*\{{(.*?)\}}", PAGE, re.S | re.M):
        found.update(re.findall(r"(--[\w-]+):\s*([^;]+);", block.group(1)))
    return found


def hsl_rgba(hue: float, sat: float, light: float) -> tuple:
    r, g, b = colorsys.hls_to_rgb(hue / 360, light, sat)
    return (r * 255, g * 255, b * 255, 1.0)


def referrals_rules():
    """[(selector, body)] of every rule of the page's CSS whose selector is a Referrals one (.ref-*, .pp-*, .card.ref)."""
    css = re.search(r"<style>(.*?)</style>", PAGE, re.S).group(1)
    return [(sel.strip(), body) for sel, body in re.findall(r"(?:^|[};])\s*([^{};@]+)\{([^{}]*)\}", css, re.M)
            if re.search(r"\.ref-|\.pp-|\.card\.ref", sel)]


def test_every_referrals_scroller_keeps_the_pages_themed_scrollbar():
    css = re.search(r"<style>(.*?)</style>", PAGE, re.S).group(1)
    # the page's rule: a thick gradient thumb on the page, on the dialogs' panes and on tables (the gloss layer)
    assert re.search(r"::-webkit-scrollbar-thumb \{ background: var\(--sb-sheen\), var\(--sb-thumb\)", css)
    assert ".dialog *::-webkit-scrollbar" in css and "scrollbar-color: var(--sb-solid-thumb)" in css
    rules = referrals_rules()
    assert rules
    scrollers = [sel for sel, body in rules if re.search(r"overflow(-[xy])?:\s*(auto|scroll)", body)]
    assert any(".ref-list" in s for s in scrollers)  # the dialogs' lists scroll, inside .dialog, where the 14px thumb applies
    for sel, body in rules:
        # nothing here switches the themed scrollbar off or restyles it: no scrollbar-width, no scrollbar-color, no own pseudo rule
        assert "scrollbar-width" not in body and "scrollbar-color" not in body, sel
        assert "::-webkit-scrollbar" not in sel, sel
    assert not any("scrollbar" in sel for sel, _ in rules)
    # a scroller outside a dialog would take the page's 18px thumb; here every one is the dialog's own (list and note)
    page_scrollers = [s for s in scrollers if not re.search(r"\.ref-(list|dialog|left|over|note)|\.rank-dialog", s)]
    assert page_scrollers == [], page_scrollers


def test_the_referrals_page_and_its_dialogs_show_the_thick_coloured_thumb(referrals_page):
    page = referrals_page
    thumb = lambda sel, pseudo: page.evaluate(  # noqa: E731
        "([s, p]) => { const st = getComputedStyle(document.querySelector(s), p); return [st.width, st.backgroundImage.includes('gradient')] }", [sel, pseudo])
    assert thumb("html", "::-webkit-scrollbar") == ["18px", False]
    assert thumb("html", "::-webkit-scrollbar-thumb")[1]
    card(page, "Initech").get_by_role("button", name="See the 6 good fits", exact=True).click()
    sync_api.expect(page.locator(".ref-dialog .ref-list")).to_be_visible()
    assert thumb(".ref-dialog .ref-list", "::-webkit-scrollbar")[0] == "14px"
    assert thumb(".ref-dialog .ref-list", "::-webkit-scrollbar-thumb")[1]
    assert page.evaluate("getComputedStyle(document.querySelector('.ref-dialog .ref-list')).scrollbarWidth") == "auto"
    page.keyboard.press("Escape")
    page.evaluate("document.documentElement.dataset.theme = 'light'")
    assert thumb("html", "::-webkit-scrollbar-thumb")[1]


@pytest.mark.parametrize("theme, selector", [("light", ":root"), ("dark", ':root[data-theme="dark"]')])
def test_a_cards_edge_stands_off_the_page_in_every_hue_at_3_to_1(theme, selector):
    """The card's 1px edge is hsl(hue, --ref-edge-s, --ref-edge-l): whatever the company's colour, it is at least 3:1
    against the page's own background, and the card (white, or the dark panel) is lighter or darker than the page."""
    t = {**all_tokens(":root"), **all_tokens(selector)}  # the dark block overrides the light tokens it names
    page_bg = rgba(t["--ref-page"])
    sat, light = (float(t[k].rstrip("%")) / 100 for k in ("--ref-edge-s", "--ref-edge-l"))
    worst = min((contrast(hsl_rgba(h, sat, light), page_bg), h) for h in range(0, 360, 5))
    assert worst[0] >= 3, f"{theme}: the edge at hue {worst[1]} is {worst[0]:.2f}:1 against the page"
    assert contrast(rgba(t["--panel-solid"]), page_bg) >= 1.1, f"{theme}: the card is not told from the page"
    assert re.search(r"\.card\.ref \{[^}]*border: 1px solid var\(--edge\)", PAGE)


# -- the page, in a browser --------------------------------------------------------------------------------------------

sync_api = pytest.importorskip("playwright.sync_api")

CONNECTIONS = """First Name,Last Name,URL,Email Address,Company,Position,Connected On
Ana,Li,https://www.linkedin.com/in/example-ana,,Initech,Staff Engineer,01 Jan 2024
Bo,Chen,https://www.linkedin.com/in/example-bo,,Initech,Recruiter,02 Jan 2024
Cy,Diaz,https://www.linkedin.com/in/example-cy,,Initech Inc,Platform Lead,05 Jan 2024
Di,Evans,https://www.linkedin.com/in/example-di,,Initech,Analyst,06 Jan 2024
Ed,Fox,https://www.linkedin.com/in/example-ed,,Initech,Designer,07 Jan 2024
Dee,Park,https://www.linkedin.com/in/example-dee,,Umbrella,Analyst,04 Jan 2024
José,Núñez,https://www.linkedin.com/in/example-jose,,Globex Corporation,Engineering Manager,03 Jan 2024
"""
# title, fit (None: no score yet), stage
INITECH = [("Platform Engineer", 90, "new"), ("Data Engineer", 85, "new"), ("Backend Engineer", 80, "new"),
           ("Cloud Engineer", 75, "applied"), ("Staff Engineer", 70, "new"), ("Support Engineer", 60, "new"),
           ("Release Engineer", None, "queued"), ("Intern Engineer", None, "new")]
UMBRELLA = [("Test Engineer", 30, "new"), ("Field Engineer", None, "new")]


def open_referrals(page, watchlist, connections=CONNECTIONS, companies=(("Initech", INITECH), ("Umbrella", UMBRELLA)),
                   globex=True, min_fit=70, wait_for_cards=True):
    """Referrals open on made-up data: the connections (None: none imported), the companies with their jobs, each a list of
    (title, fit, stage), and the fit minimum (None: not set)."""
    settings = {"resume": str(watchlist.parent / "cv.md"), "filters": {**FILTERS, **({"min_fit": min_fit} if min_fit else {})}}
    (watchlist.parent / "cv.md").write_text("# Jane Doe")
    if connections is not None:
        (watchlist.parent / "Connections.csv").write_text(connections, encoding="utf-8")
        settings["connections"] = "Connections.csv"
    config.save(watchlist, settings)
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    for company, jobs in companies:
        for title, fit, stage in jobs:
            job = store.add(company, title, status=stage, location="Remote")
            if fit:
                store.save_score(job.key, resume_id(cfg.resume, cfg.prompts), {
                    "score": fit, "must_haves_met": 1, "must_haves_total": 1, "gaps": [], "summary": "", "flags": []})
    if globex:
        store.add("Globex Corporation", "Support Engineer", status="queued", location="Remote")
    store.close()
    page.evaluate("localStorage.clear()")
    page.goto(page.url.split("#")[0] + "#referrals")
    page.reload()
    page.wait_for_load_state("networkidle")
    if wait_for_cards:
        sync_api.expect(page.locator(".card.ref").first).to_be_visible()
    return page


@pytest.fixture
def referrals_page(page, watchlist):
    """Seven people with tracked jobs at three made-up companies (Initech: five people, eight jobs scored, queued, applied
    or open; Umbrella: one person and two jobs with no good fit; Globex: one person, one queued job), the fit minimum 70,
    and the Referrals tab open."""
    return open_referrals(page, watchlist)


def card(page, name):
    return page.locator(".card.ref", has_text=name)


def row(page, name):
    return page.locator(".card.ref .ref-p", has_text=name)


def company_names(page):
    return [n.inner_text() for n in page.locator(".card.ref .ref-name").all()]


def test_a_card_is_a_company_with_its_good_fits_once_and_the_people_you_know_there(referrals_page):
    page = referrals_page
    initech = card(page, "Initech")
    sync_api.expect(initech.locator(".ref-know")).to_have_text("5 people you know")  # Cy's "Initech Inc" is the same company
    sync_api.expect(initech.locator(".ref-n")).to_have_text("6 good fits")  # 90 85 80 70, the applied 75 and the queued job
    sync_api.expect(initech.locator(".ref-job")).to_have_count(3)  # the best three, the rest "+ 3 more"
    assert [p.inner_text() for p in initech.locator(".ref-job .fitpill").all()] == ["90", "85", "80"]
    assert [t.inner_text() for t in initech.locator(".ref-job .t").all()][:2] == ["Platform Engineer", "Data Engineer"]
    sync_api.expect(initech.locator(".ref-jhead")).to_contain_text("2 not scored yet")
    sync_api.expect(initech.locator(".ref-of")).to_have_text("of 8 open")  # the total is small grey text, with a tooltip
    assert "8 open jobs at Initech" in initech.locator(".ref-of").get_attribute("title")
    sync_api.expect(initech.locator(".ref-jobs .ref-soft")).to_have_text("+ 3 more")
    sync_api.expect(initech.get_by_role("button", name="See the 6 good fits", exact=True)).to_be_visible()
    # the first three of five people, alphabetical since none has messages; the others are "+ 2 more people"
    assert [n.inner_text() for n in initech.locator(".ref-p .pp-name").all()] == ["Ana Li", "Bo Chen", "Cy Diaz"]
    sync_api.expect(initech.get_by_role("button", name="+ 2 more people", exact=True)).to_be_visible()
    assert initech.locator(".ref-p .pp-sub").first.get_attribute("title") == "Staff Engineer"  # the whole title on hover
    globex = card(page, "Globex")
    sync_api.expect(globex.locator(".ref-job")).to_have_count(1)
    sync_api.expect(globex.locator(".ref-know")).to_have_text("1 person you know")  # one reads as one
    sync_api.expect(globex.locator(".ref-n")).to_have_text("1 good fit")
    sync_api.expect(globex.locator(".ref-of")).to_have_count(0)  # nothing else open there
    sync_api.expect(globex.get_by_role("button", name="See the good fit", exact=True)).to_be_visible()
    sync_api.expect(globex.locator(".ref-p")).to_have_count(1)
    sync_api.expect(globex.get_by_role("button", name="See the person", exact=True)).to_be_visible()
    # no room is kept for what a company does not have, and no sentence says so
    sync_api.expect(globex.locator(".ref-soft")).to_have_count(0)
    sync_api.expect(page.get_by_text("Nothing to list yet")).to_have_count(0)
    sync_api.expect(page.get_by_text("No other people yet")).to_have_count(0)
    umbrella = card(page, "Umbrella")
    sync_api.expect(umbrella.locator(".ref-n.none")).to_have_text("No good fit yet")
    sync_api.expect(umbrella.locator(".ref-job")).to_have_count(0)  # the jobs with no score or a low one are not shown as matches
    sync_api.expect(umbrella.locator(".ref-jobs")).not_to_contain_text("Nothing to list")  # the header strip is all there is
    assert umbrella.locator(".ref-n.none").get_attribute("title").count("a click away") == 1  # what it would say is on the chip
    sync_api.expect(umbrella.locator(".ref-jhead")).to_contain_text("1 not scored yet")
    sync_api.expect(umbrella.get_by_role("button", name="See all 2 jobs", exact=True)).to_be_visible()
    # best fit first is the default: the company with no good fit comes last, and the count reads companies then people
    assert [n.split()[0] for n in company_names(page)] == ["Initech", "Globex", "Umbrella"]
    sync_api.expect(page.locator(".ref-sort")).to_have_value("fit")
    sync_api.expect(page.locator(".ref-bar .ref-total")).to_have_text("3 of 3 companies · 7 people")
    assert page.errors == []


def test_the_sort_control_orders_the_companies(referrals_page):
    page = referrals_page
    page.get_by_label("Sort people").select_option("name")
    assert [n.split()[0] for n in company_names(page)] == ["Globex", "Initech", "Umbrella"]
    page.get_by_label("Sort people").select_option("people")
    assert company_names(page)[0].startswith("Initech")
    page.get_by_label("Sort people").select_option("count")
    assert [n.split()[0] for n in company_names(page)] == ["Initech", "Globex", "Umbrella"]  # 6, 1 (queued) and none
    assert [o.inner_text() for o in page.locator(".ref-bar .ref-sort option").all()] == [
        "Best fit first", "Most good fits", "Most people you know", "Last messaged", "A-Z"]
    page.reload()  # the choice is kept in this browser
    sync_api.expect(page.locator(".ref-bar .ref-sort")).to_have_value("count")


def test_a_card_with_a_job_in_progress_or_queued_takes_an_amber_or_green_accent_and_a_ribbon(referrals_page):
    initech, globex, umbrella = (card(referrals_page, n) for n in ("Initech", "Globex", "Umbrella"))
    sync_api.expect(initech).to_have_class(re.compile(r"\blive-working\b"))  # Cloud Engineer is applied
    sync_api.expect(initech.locator(".ref-ribbon")).to_have_text("Applied")
    sync_api.expect(globex).to_have_class(re.compile(r"\blive-queued\b"))
    sync_api.expect(globex.locator(".ref-ribbon")).to_have_text("Queued")
    sync_api.expect(umbrella.locator(".ref-ribbon")).to_have_count(0)
    # the edge is a visible border, and each company has a colour of its own
    edge = referrals_page.evaluate(
        "(() => { const c = getComputedStyle(document.querySelector('.card.ref')); return [c.borderTopWidth, c.borderTopStyle] })()")
    assert edge == ["1px", "solid"]
    hues = referrals_page.evaluate("[...document.querySelectorAll('.card.ref')].map(c => c.style.getPropertyValue('--h'))")
    assert len(set(hues)) == 3


def test_use_stays_on_the_persons_row_and_the_note_is_in_their_dialog(referrals_page):
    page = referrals_page
    bo = row(page, "Bo Chen")
    assert page.locator(".ref-note").count() == 0  # there is no note box on a card: the note is written in the person's dialog
    bo.get_by_role("button", name="Use", exact=True).click()
    sync_api.expect(row(page, "Bo Chen").locator(".chip.hit")).to_have_text("ask first")
    sync_api.expect(page.locator(".ref-dialog")).to_have_count(0)  # Use works in place, no dialog
    assert company_names(page)[0].startswith("Initech")
    # a person you asked first comes first in their company
    assert card(page, "Initech").locator(".ref-p .pp-name").first.inner_text().startswith("Bo Chen")
    row(page, "Bo Chen").get_by_role("button", name="Open the details and note for Bo Chen").click()
    dialog = page.locator(".ref-dialog")
    sync_api.expect(dialog).to_be_visible()
    note = dialog.get_by_label("Note about Bo Chen")
    note.fill("reach on WhatsApp")
    dialog.get_by_role("button", name="Save note").click()
    page.keyboard.press("Escape")
    sync_api.expect(dialog).to_have_count(0)
    sync_api.expect(row(page, "Bo Chen").locator(".pp-notetxt")).to_have_text("reach on WhatsApp")  # one cut line on the card
    page.reload()
    sync_api.expect(row(page, "Bo Chen").locator(".pp-notetxt")).to_have_text("reach on WhatsApp")
    row(page, "Bo Chen").get_by_role("button", name="Clear the choice for Bo Chen").click()
    sync_api.expect(row(page, "Bo Chen").locator(".chip.hit")).to_have_count(0)
    assert page.errors == []


def test_a_name_an_avatar_or_the_note_button_opens_the_person_in_a_big_dialog_with_the_jobs_and_a_referral_draft(referrals_page):
    page = referrals_page
    dialog = page.locator(".ref-dialog")
    for target in (row(page, "Ana Li").get_by_role("button", name="Ana Li: details and a note"),
                   row(page, "Ana Li").locator(".ref-avbtn"), row(page, "Ana Li").locator(".pp-sub2")):
        target.dispatch_event("click")
        sync_api.expect(dialog).to_be_visible()
        sync_api.expect(dialog.locator("h2")).to_have_text("Ana Li")
        page.keyboard.press("Escape")
        sync_api.expect(dialog).to_have_count(0)
    row(page, "Ana Li").get_by_role("button", name="Ana Li: details and a note").click()
    box, view = dialog.bounding_box(), page.viewport_size
    assert box["width"] >= view["width"] * 0.8 and box["height"] >= view["height"] * 0.8
    sync_api.expect(dialog.locator(".rk-count")).to_have_text("1 of 5")
    sync_api.expect(dialog).to_contain_text("Staff Engineer")  # their title, and the jobs there
    sync_api.expect(dialog.get_by_role("button", name="Use", exact=True)).to_be_visible()
    sync_api.expect(dialog.get_by_role("link", name=re.compile("LinkedIn"))).to_have_attribute("target", "_blank")
    sync_api.expect(dialog.get_by_role("link", name=re.compile("LinkedIn"))).to_have_attribute("rel", "noopener noreferrer")
    sync_api.expect(dialog.locator(".ref-sec h3", has_text="Draft a referral request")).to_be_visible()
    sync_api.expect(dialog.locator(".who-host")).to_be_visible()
    page.keyboard.press("ArrowRight")  # the arrows step between the people there
    sync_api.expect(dialog.locator(".rk-count")).to_have_text("2 of 5")
    page.keyboard.press("Escape")
    sync_api.expect(dialog).to_have_count(0)
    assert page.evaluate("document.activeElement.textContent") == "Ana Li"  # focus is back on the name
    assert page.errors == []


def test_the_name_and_logo_go_to_the_company_tab_as_a_company_on_today_does_and_open_no_dialog(referrals_page):
    page = referrals_page
    initech = card(page, "Initech")
    name, logo = initech.locator("a.ref-name"), initech.locator("a.ref-logo")
    sync_api.expect(name).to_have_attribute("aria-label", "Initech: everything tracked there")
    assert name.get_attribute("href") == "#company/Initech" == logo.get_attribute("href")
    # Today's company link calls openCompany(name): this lands in the same place
    page.evaluate("openCompany('Initech')")
    sync_api.expect(page.locator(".pagehead h1")).to_have_text("Initech")
    there = page.url.split("#")[1]
    page.goto(page.url.split("#")[0] + "#referrals")
    sync_api.expect(page.locator(".card.ref").first).to_be_visible()
    for target in ("a.ref-name", "a.ref-logo"):
        card(page, "Initech").locator(target).click()
        sync_api.expect(page.locator(".pagehead h1")).to_have_text("Initech")
        assert page.url.split("#")[1] == there
        sync_api.expect(page.locator(".ref-dialog")).to_have_count(0)  # not a dialog
        page.go_back()
        page.goto(page.url.split("#")[0] + "#referrals")
        sync_api.expect(page.locator(".card.ref").first).to_be_visible()
    card(page, "Initech").locator("a.ref-name").focus()  # a real link: the keyboard does it too
    page.keyboard.press("Enter")
    sync_api.expect(page.locator(".pagehead h1")).to_have_text("Initech")
    assert page.errors == []


def test_the_careers_link_is_on_the_company_tab_and_not_on_the_referrals_cards(referrals_page):
    page = referrals_page
    sync_api.expect(page.locator(".card.ref a[target=_blank]")).to_have_count(0)  # a card's header is the logo, the name and the pill
    assert page.locator(".card.ref").first.get_by_text("Careers").count() == 0
    sync_api.expect(page.locator(".co-careers, .ref-careers")).to_have_count(0)
    assert "careers" not in page.evaluate("fetch('/api/referrals').then(r => r.json()).then(d => Object.keys(d))")
    card(page, "Initech").locator("a.ref-name").click()
    chip = page.locator(".pagehead a.co-careers")
    sync_api.expect(chip).to_have_count(1)
    sync_api.expect(chip).to_have_attribute("target", "_blank")
    sync_api.expect(chip).to_have_attribute("rel", "noopener noreferrer")
    assert re.match(r"https://", chip.get_attribute("href"))
    shown = page.locator(".pagehead h1").inner_text()
    assert chip.get_attribute("title") in (f"Open {shown} careers in a new tab",
                                           f"Search careers: look for {shown}'s careers page on the web, in a new tab")
    assert chip.get_attribute("aria-label") == chip.get_attribute("title")
    assert chip.inner_text().strip() in ("Careers ↗", "Search careers ↗")
    assert page.errors == []


EXTRA = "".join(f"{p},Lee,https://www.linkedin.com/in/example-{c.lower()},,{c},Engineer,01 Jan 2024\n"
                 for p, c in (("Gus", "Hooli"), ("Hal", "Stark"), ("Ivy", "Wayne")))


def rows_of_cards(page):
    """The cards as rows of the grid: [(top, [heights])], by where each starts."""
    got = page.evaluate("[...document.querySelectorAll('.card.ref')].map(c => { const r = c.getBoundingClientRect(); return [Math.round(r.top + scrollY), Math.round(r.height)] })")
    rows = {}
    for top, height in got:
        rows.setdefault(top, []).append(height)
    return sorted(rows.items())


def test_cards_in_a_row_are_equal_in_height_and_the_row_is_only_as_tall_as_its_tallest_card(page, watchlist):
    sparse = tuple((name, [("Platform Engineer", 85, "new")]) for name in ("Hooli", "Stark", "Wayne"))
    open_referrals(page, watchlist, connections=CONNECTIONS + EXTRA, companies=(("Initech", INITECH), *sparse), globex=False)
    page.set_viewport_size({"width": 1400, "height": 900})
    rows = rows_of_cards(page)
    assert len(rows) == 2 and [len(h) for _, h in rows] == [3, 1], rows  # Initech, Hooli and Stark; Wayne (all in best-fit order)
    for _, heights in rows:
        assert len(set(heights)) == 1, rows  # equal inside a row
    full, sparse_row = rows[0][1][0], rows[1][1][0]
    assert sparse_row < full - 80, rows  # no room is reserved for five jobs and four people: the sparse row is shorter
    # a card never holds more than three jobs or three people
    assert page.evaluate("[...document.querySelectorAll('.card.ref')].every(c => c.querySelectorAll('.ref-job').length <= 3 && c.querySelectorAll('.ref-p').length <= 3)")
    # the footer buttons sit at the bottom of every card, tall or short
    assert page.evaluate("[...document.querySelectorAll('.card.ref')].every(c => { const f = c.querySelector('.ref-foot').getBoundingClientRect(), r = c.getBoundingClientRect(); return r.bottom - f.bottom < 16 })")
    for width in ("standard", "wide", "full"):
        page.evaluate(f"document.documentElement.dataset.width = '{width}'")
        for _, heights in rows_of_cards(page):
            assert len(set(heights)) == 1, (width, heights)
    assert page.errors == []


def test_a_card_with_no_good_fit_is_a_header_strip_and_its_people(referrals_page):
    page = referrals_page
    page.set_viewport_size({"width": 1400, "height": 900})
    page.evaluate("document.querySelector('.ref-grid').style.alignItems = 'start'")  # each card at its own height
    heights = {n: card(page, n).bounding_box()["height"] for n in ("Initech", "Globex", "Umbrella")}
    assert heights["Initech"] > heights["Globex"] > 0
    umbrella = card(page, "Umbrella")
    assert umbrella.locator(".ref-jobs").bounding_box()["height"] < 45  # the pill and the counts: one line, no blank block
    assert umbrella.locator(".ref-people").bounding_box()["height"] < 110  # one person's row, no room for four
    page.evaluate("document.querySelector('.ref-grid').style.alignItems = ''")


def test_narrow_cards_stack_in_one_column_without_spilling_sideways(referrals_page):
    page = referrals_page
    page.set_viewport_size({"width": 390, "height": 800})
    got = page.evaluate("[...document.querySelectorAll('.card.ref')].map(c => c.getBoundingClientRect().width)")
    assert got and all(w <= 390 for w in got)
    # nothing spills out of a card sideways, and no name or title wraps onto a second line
    assert page.evaluate("[...document.querySelectorAll('.card.ref')].every(c => c.scrollWidth <= c.clientWidth + 1)")
    assert page.evaluate("[...document.querySelectorAll('.card.ref .ref-name, .card.ref .pp-namebtn, .card.ref .pp-sub')].every(e => e.getBoundingClientRect().height < 30)")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.errors == []


def test_the_dialog_opens_on_good_fits_with_the_rest_a_tab_away_and_steps_between_companies(referrals_page):
    page = referrals_page
    button = card(page, "Initech").get_by_role("button", name="See the 6 good fits", exact=True)
    button.click()
    dialog = page.locator(".ref-dialog")  # its name changes as the arrows step to another company
    sync_api.expect(dialog).to_be_visible()
    sync_api.expect(dialog).to_have_attribute("aria-label", "Jobs at Initech, 1 of 3")
    assert dialog.get_attribute("aria-modal") == "true"
    size = dialog.bounding_box()
    view = page.viewport_size
    assert size["width"] >= view["width"] * 0.8 and size["height"] >= view["height"] * 0.8
    tab = lambda name: dialog.get_by_role("tab", name=name)  # noqa: E731
    # it opens on Good fits (never on the wall), each tab says how many
    sync_api.expect(dialog.locator(".ref-tab.on")).to_have_text("Good fits (6)")
    assert [t.inner_text() for t in dialog.locator(".ref-tab").all()] == [
        "Overview", "Good fits (6)", "Applied and queued (2)", "Not scored (2)", "All (8)", "People (5)"]
    sync_api.expect(dialog.locator(".ref-row")).to_have_count(6)
    sync_api.expect(dialog.locator(".ref-total")).to_have_text("6 jobs")
    assert [p.inner_text() for p in dialog.locator(".ref-row .fitpill").all()][:3] == ["90", "85", "80"]
    tab("Applied and queued").click()
    sync_api.expect(dialog.locator(".ref-row")).to_have_count(2)
    tab("Not scored").click()  # their titles, with the hint that the scorer reaches them in time or Read posting scores one
    sync_api.expect(dialog.locator(".ref-row")).to_have_count(2)
    sync_api.expect(dialog.locator(".ref-hint")).to_contain_text("Read posting")
    assert {p.inner_text() for p in dialog.locator(".ref-row .fitpill").all()} == {"–"}
    tab("All").click()
    sync_api.expect(dialog.locator(".ref-row")).to_have_count(8)
    sync_api.expect(dialog.locator(".ref-total")).to_have_text("8 jobs")
    dialog.get_by_label("Search these jobs").fill("zzz")
    sync_api.expect(dialog.locator(".empty")).to_contain_text("No jobs match 'zzz'")
    dialog.get_by_label("Search these jobs").fill("data ENG")
    sync_api.expect(dialog.locator(".ref-row")).to_have_count(1)
    sync_api.expect(dialog.locator(".ref-row mark").first).to_have_text("Data")
    dialog.get_by_label("Search these jobs").fill("")
    dialog.get_by_label("Sort these jobs").select_option("title")
    assert dialog.locator(".ref-row .t").first.inner_text() == "Backend Engineer"
    # arrows step to the next company's list, opening on theirs (not while typing in the search box)
    count = dialog.locator(".rk-count")
    first = count.inner_text()
    assert first.startswith("1 of 3")
    dialog.get_by_label("Search these jobs").focus()
    page.keyboard.press("ArrowRight")
    assert count.inner_text() == first
    dialog.focus()
    page.keyboard.press("ArrowRight")
    assert count.inner_text().startswith("2 of 3") and "Globex" in dialog.locator("h2").inner_text()
    sync_api.expect(dialog.locator(".ref-tab.on")).to_have_text("Good fits (1)")
    page.keyboard.press("ArrowRight")  # Umbrella has no good fit: its list opens on Not scored
    assert count.inner_text().startswith("3 of 3") and "Umbrella" in dialog.locator("h2").inner_text()
    sync_api.expect(dialog.locator(".ref-tab.on")).to_have_text("Not scored (1)")
    tab("Good fits").click()
    sync_api.expect(dialog.locator(".empty")).to_contain_text("No good fit yet")
    for _ in range(2):
        page.keyboard.press("ArrowLeft")
    assert count.inner_text().startswith("1 of 3")
    # Esc closes it and focus returns to the company's button; so does a click on the backdrop
    page.keyboard.press("Escape")
    sync_api.expect(dialog).to_have_count(0)
    assert page.evaluate("document.activeElement.textContent") == "See the 6 good fits"
    button.click()
    sync_api.expect(dialog).to_be_visible()
    page.mouse.click(4, 4)
    sync_api.expect(dialog).to_have_count(0)
    assert page.errors == []


def test_the_pill_opens_the_overview_and_the_see_button_the_good_fits(referrals_page):
    page = referrals_page
    dialog = page.locator(".ref-dialog")
    card(page, "Initech").get_by_role("button", name=re.compile("5 people you know")).click()
    sync_api.expect(dialog.locator(".ref-tab.on")).to_have_text("Overview")
    sync_api.expect(dialog.locator(".ref-tile").first).to_contain_text("5")
    sync_api.expect(dialog.locator(".ref-sec h3", has_text="Company health")).to_be_visible()
    page.keyboard.press("Escape")
    assert page.evaluate("document.activeElement.className").startswith("ref-know")
    card(page, "Initech").get_by_role("button", name="See the 6 good fits", exact=True).click()
    sync_api.expect(dialog.locator(".ref-tab.on")).to_have_text("Good fits (6)")
    assert page.errors == []


def open_list(page, name="Initech"):
    card(page, name).get_by_role("button", name=re.compile("See the .*good fit|See all .* jobs")).click()
    dialog = page.locator(".ref-dialog")
    sync_api.expect(dialog).to_be_visible()
    return dialog


def z(page, selector):
    return page.evaluate(f"+getComputedStyle(document.querySelector({selector!r})).zIndex || 0")


def details_in_front(page):
    """Whether what is at the middle of the job's details is the details, not a dialog behind it."""
    return page.evaluate("(() => { const r = document.querySelector('#dialog').getBoundingClientRect();"
                         " return !!document.elementFromPoint(r.x + r.width / 2, r.y + Math.min(60, r.height / 2)).closest('#dialog') })()")


def test_a_job_opened_from_the_list_shows_its_details_in_front_and_esc_peels_them_off_one_at_a_time(referrals_page):
    page = referrals_page
    dialog = open_list(page)
    dialog.locator(".ref-row").first.click()
    details = page.locator("#dialog")
    sync_api.expect(details).to_contain_text("Platform Engineer")
    sync_api.expect(dialog).to_be_visible()  # the list stays, behind
    assert z(page, "#overlay") > z(page, ".ref-shade")
    # what is at the middle of the details is the details, not the list behind it
    assert details_in_front(page)
    page.keyboard.press("Escape")  # the details first
    sync_api.expect(page.locator("#overlay")).to_be_hidden()
    sync_api.expect(dialog).to_be_visible()
    page.keyboard.press("Escape")  # then the list
    sync_api.expect(dialog).to_have_count(0)
    assert page.errors == []


@pytest.mark.parametrize("where", ["card job", "people tab job", "overview job"])
def test_a_job_opened_from_a_card_the_overview_or_another_tab_is_in_front(referrals_page, where):
    page = referrals_page
    if where == "card job":
        card(page, "Initech").locator(".ref-job").first.click()
        sync_api.expect(page.locator("#overlay")).to_be_visible()
        assert details_in_front(page)
        page.keyboard.press("Escape")
        sync_api.expect(page.locator("#overlay")).to_be_hidden()
        return
    dialog = open_list(page)
    if where == "overview job":
        dialog.get_by_role("tab", name="Overview").click()
    else:
        dialog.get_by_role("tab", name="People").click()
        dialog.locator(".ref-p").first.get_by_role("button", name=re.compile("details and a note")).first.click()  # a person over the company
        person = page.locator(".ref-dialog").nth(1)
        sync_api.expect(person).to_be_visible()
        assert page.evaluate("document.querySelectorAll('.ref-shade').length") == 2
        top = page.evaluate("[...document.querySelectorAll('.ref-shade')].map(e => +getComputedStyle(e).zIndex)")
        assert top[1] > top[0]
        page.keyboard.press("ArrowRight")  # the person on top takes the keys, not the company beneath it
        sync_api.expect(person.locator(".rk-count")).to_have_text("2 of 5")
        sync_api.expect(dialog.locator(".rk-count").first).to_have_text("1 of 3")
        person.locator(".ref-row").first.click()  # a job from the person: its details over both
        sync_api.expect(page.locator("#overlay")).to_be_visible()
        assert z(page, "#overlay") > max(top)
        assert details_in_front(page)
        page.keyboard.press("Escape")
        sync_api.expect(page.locator("#overlay")).to_be_hidden()
        sync_api.expect(person).to_be_visible()
        page.keyboard.press("Escape")
        sync_api.expect(page.locator(".ref-dialog")).to_have_count(1)
        page.keyboard.press("Escape")
        sync_api.expect(page.locator(".ref-dialog")).to_have_count(0)
        return
    dialog.locator(".ref-sec .ref-row").first.click()
    sync_api.expect(page.locator("#dialog")).to_contain_text("Engineer")
    assert z(page, "#overlay") > z(page, ".ref-shade")
    assert details_in_front(page)
    page.keyboard.press("Escape")
    sync_api.expect(dialog).to_be_visible()
    assert page.errors == []


def test_more_people_opens_the_dialog_on_everyone_you_know_there_with_the_same_controls(referrals_page):
    page = referrals_page
    button = card(page, "Initech").get_by_role("button", name="+ 2 more people", exact=True)
    button.click()
    dialog = page.locator(".ref-dialog")
    sync_api.expect(dialog).to_be_visible()
    sync_api.expect(dialog.locator(".ref-tab.on")).to_have_text("People (5)")
    sync_api.expect(dialog.locator(".ref-p")).to_have_count(5)  # everyone, the fifth too
    sync_api.expect(dialog.locator(".ref-total")).to_have_text("5 people")
    assert dialog.get_by_label("Search these people").is_visible() and not dialog.get_by_label("Search these jobs").is_visible()
    dialog.get_by_label("Search these people").fill("ed fox")
    sync_api.expect(dialog.locator(".ref-p")).to_have_count(1)
    sync_api.expect(dialog.locator(".ref-p mark").first).to_have_text("Ed")
    dialog.get_by_label("Search these people").fill("zzz")
    sync_api.expect(dialog.locator(".empty")).to_have_text("No one matches 'zzz'")
    dialog.get_by_label("Search these people").fill("")
    # Use works in the dialog, and the list keeps up; the name opens their details, where the note is written
    ed = dialog.locator(".ref-p", has_text="Ed Fox")
    ed.get_by_role("button", name="Use", exact=True).click()
    sync_api.expect(dialog.locator(".ref-p", has_text="Ed Fox").locator(".chip.hit")).to_have_text("ask first")
    dialog.locator(".ref-p", has_text="Ed Fox").get_by_role("button", name="Ed Fox: details and a note").click()
    person = page.locator(".ref-dialog >> nth=1")
    sync_api.expect(person.locator("h2")).to_have_text("Ed Fox")
    person.get_by_label("Note about Ed Fox").fill("former teammate")
    person.get_by_role("button", name="Save note").click()
    page.keyboard.press("Escape")
    sync_api.expect(page.locator(".ref-dialog")).to_have_count(1)  # the company's dialog is back in front
    sync_api.expect(dialog.locator(".ref-p", has_text="Ed Fox").locator(".pp-notetxt")).to_have_text("former teammate")
    page.reload()
    sync_api.expect(row(page, "Ed Fox").locator(".pp-notetxt")).to_have_text("former teammate")  # asked first: now on the card
    assert page.errors == []


def test_the_people_dialog_steps_between_companies_and_returns_focus(referrals_page):
    page = referrals_page
    card(page, "Initech").get_by_role("button", name="+ 2 more people", exact=True).click()
    dialog = page.locator(".ref-dialog")
    dialog.focus()
    page.keyboard.press("ArrowRight")
    sync_api.expect(dialog.locator(".ref-tab.on")).to_have_text("People (1)")
    assert "Globex" in dialog.locator("h2").inner_text()
    sync_api.expect(dialog.locator(".ref-p")).to_have_count(1)
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("Escape")
    sync_api.expect(dialog).to_have_count(0)
    assert page.evaluate("document.activeElement.textContent") == "+ 2 more people"


def test_tab_stays_inside_the_dialog(referrals_page):
    page = referrals_page
    card(page, "Initech").get_by_role("button", name="See the 6 good fits", exact=True).click()
    for _ in range(40):
        page.keyboard.press("Tab")
        assert page.evaluate("!!document.activeElement.closest('.ref-dialog')")


def test_the_search_finds_a_person_by_name_company_or_title_keeps_the_card_and_says_when_no_one_matches(referrals_page):
    page = referrals_page
    box = page.get_by_label("Search people by name, company or title")
    total = page.locator(".ref-bar .ref-total")
    sync_api.expect(total).to_have_text("3 of 3 companies · 7 people")
    box.fill("nunez")  # accents ignored: José Núñez
    sync_api.expect(page.locator(".card.ref")).to_have_count(1)
    sync_api.expect(total).to_have_text("1 of 3 companies · 1 person")
    sync_api.expect(page.locator(".card.ref mark").first).to_have_text("Núñez")
    box.fill("INITECH staff")  # company and title, any case: the company's card stays, with the one person who matched
    sync_api.expect(page.locator(".card.ref")).to_have_count(1)
    sync_api.expect(card(page, "Initech").locator(".ref-p")).to_have_count(1)
    sync_api.expect(row(page, "Ana Li")).to_be_visible()
    sync_api.expect(card(page, "Initech").locator(".ref-know")).to_have_text("5 people you know")  # the company's own count stands
    sync_api.expect(card(page, "Initech").get_by_role("button", name="See the 5 people", exact=True)).to_be_visible()  # no "+ more": the one shows
    sync_api.expect(total).to_have_text("1 of 3 companies · 1 person")
    box.fill("recruiter")
    sync_api.expect(row(page, "Bo Chen")).to_be_visible()
    box.fill("initech")  # the company's name matches everyone there
    sync_api.expect(card(page, "Initech").locator(".ref-p")).to_have_count(3)  # a card shows three
    sync_api.expect(card(page, "Initech").locator(".ref-name mark")).to_have_text("Initech")
    box.fill("xyz")
    sync_api.expect(page.locator(".ref-grid .empty")).to_have_text("No one matches 'xyz'")
    sync_api.expect(total).to_have_text("0 of 3 companies · 0 people")
    page.reload()  # what was typed is kept in this browser
    sync_api.expect(box).to_have_value("xyz")
    page.get_by_role("button", name="Clear the search").click()
    sync_api.expect(box).to_have_value("")
    sync_api.expect(total).to_have_text("3 of 3 companies · 7 people")
    assert page.evaluate("localStorage.getItem('jobwatch.referrals.q')") == ""
    assert page.errors == []


def test_slash_focuses_the_search_and_esc_clears_it(referrals_page):
    page = referrals_page
    box = page.get_by_label("Search people by name, company or title")
    page.locator("main").click(position={"x": 5, "y": 5})
    page.keyboard.press("/")
    sync_api.expect(box).to_be_focused()
    assert page.url.endswith("#referrals")  # not the Company tab's box
    page.keyboard.type("globex")
    sync_api.expect(page.locator(".card.ref")).to_have_count(1)
    page.keyboard.press("Escape")
    sync_api.expect(box).to_have_value("")
    sync_api.expect(page.locator(".card.ref")).to_have_count(3)
    page.keyboard.press("Escape")  # a second Esc leaves the box
    sync_api.expect(box).not_to_be_focused()


# -- a first-time person: nothing set up, one of everything, hundreds ---------------------------------------------------

HEADER = "First Name,Last Name,URL,Email Address,Company,Position,Connected On\n"


def test_with_no_linkedin_data_the_tab_explains_what_it_is_how_to_get_people_here_and_links_to_the_upload(page, watchlist):
    open_referrals(page, watchlist, connections=None, wait_for_cards=False)
    first = page.locator(".ref-first")
    sync_api.expect(first).to_be_visible()
    sync_api.expect(first.locator("h2")).to_have_text("See who you know at the companies you're tracking")
    for words in ("referral", "Get a copy of your data", ".zip", "read on this computer only", "by hand"):
        sync_api.expect(first).to_contain_text(words)
    sync_api.expect(page.locator(".ref-bar")).to_have_count(0)  # no search or sorts over nothing
    sync_api.expect(page.locator(".card.ref")).to_have_count(0)
    first.get_by_role("link", name="Settings → People & pay").click()
    sync_api.expect(page.get_by_role("heading", name="People you know")).to_be_visible()
    assert page.url.endswith("#settings/people")
    assert page.errors == []


def test_with_connections_but_nobody_at_a_tracked_company_it_says_so_and_where_to_add_companies(page, watchlist):
    open_referrals(page, watchlist, connections=HEADER + "Ana,Li,https://www.linkedin.com/in/example-ana,,Hooli,Engineer,01 Jan 2024\n",
                   wait_for_cards=False)
    empty = page.locator(".ref-first")
    sync_api.expect(empty).to_contain_text("None of the people you know works at a company with a job you are tracking yet")
    sync_api.expect(empty.get_by_role("link", name="Settings → Your search")).to_have_attribute("href", "#settings/search")
    sync_api.expect(page.locator(".card.ref")).to_have_count(0)


def test_with_no_fit_minimum_the_default_is_used_and_said_with_where_to_change_it(page, watchlist):
    open_referrals(page, watchlist, min_fit=None)
    hint = page.locator(".ref-nofit")
    sync_api.expect(hint).to_contain_text("You have not set a Fit minimum")
    sync_api.expect(hint).to_contain_text("score of 60")
    sync_api.expect(hint.get_by_role("link", name="Settings → Your search")).to_have_attribute("href", "#settings/search")
    pill = card(page, "Initech").locator(".ref-n")
    assert "the default" in pill.get_attribute("title") and "60 or more" in pill.get_attribute("title")
    sync_api.expect(pill).to_have_text("7 good fits")  # 90 85 80 75 70 and 60, and the queued job
    assert page.errors == []


def test_with_a_fit_minimum_set_there_is_no_hint_and_the_tooltips_name_it(referrals_page):
    sync_api.expect(referrals_page.locator(".ref-nofit")).to_have_count(0)
    assert "your Fit minimum" in card(referrals_page, "Initech").locator(".ref-n").get_attribute("title")


def test_ask_first_is_explained_where_it_shows(referrals_page):
    page = referrals_page
    sync_api.expect(page.locator(".pagehead .sub")).to_contain_text("Use puts someone first")
    row(page, "Bo Chen").get_by_role("button", name="Use", exact=True).click()
    assert "come first" in row(page, "Bo Chen").locator(".chip.hit").get_attribute("title")
    assert "referral" in row(page, "Bo Chen").get_by_role("button", name="Use", exact=True).get_attribute("title")
    sync_api.expect(page.get_by_role("button", name="Ask first", exact=True)).to_have_attribute("title", re.compile("marked Use"))


def test_one_person_at_one_company_reads_as_one_and_the_dialog_has_nowhere_to_step(page, watchlist):
    open_referrals(page, watchlist, connections=HEADER + "Ana,Li,https://www.linkedin.com/in/example-ana,,Initech,Engineer,01 Jan 2024\n",
                   companies=(("Initech", [("Platform Engineer", 90, "new")]),), globex=False)
    sync_api.expect(page.locator(".ref-total")).to_have_text("1 of 1 company · 1 person")
    sync_api.expect(page.locator(".card.ref")).to_have_count(1)
    sync_api.expect(page.locator(".ref-morehost")).to_be_empty()
    card(page, "Initech").get_by_role("button", name="See the good fit", exact=True).click()
    dialog = page.locator(".ref-dialog")
    sync_api.expect(dialog.locator(".rk-count")).to_have_text("1 of 1")
    sync_api.expect(dialog.get_by_role("button", name="Next company")).to_be_disabled()
    sync_api.expect(dialog.get_by_role("button", name="Previous company")).to_be_disabled()
    assert page.errors == []


def test_hundreds_of_companies_show_a_page_of_cards_at_a_time_and_the_search_stays_quick(page, watchlist):
    n = 500
    people = "".join(f"Pat{i:03d},Lee{i:03d},https://www.linkedin.com/in/example-{i},,Company {i:03d},Engineer,01 Jan 2024\n" for i in range(n))
    open_referrals(page, watchlist, connections=HEADER + people, globex=False,
                   companies=tuple((f"Company {i:03d}", [("Platform Engineer", 60 + i % 40, "new")]) for i in range(n)))
    sync_api.expect(page.locator(".ref-total")).to_have_text("500 of 500 companies · 500 people")
    sync_api.expect(page.locator(".card.ref")).to_have_count(24)  # a page, not 500 cards
    more = page.get_by_role("button", name=re.compile("Show 24 more companies"))
    sync_api.expect(more).to_have_text("Show 24 more companies (476 not shown)")
    more.click()
    sync_api.expect(page.locator(".card.ref")).to_have_count(48)
    box = page.get_by_label("Search people by name, company or title")
    box.fill("lee1")  # a new search starts at the top again: a hundred match, a page of them show
    sync_api.expect(page.locator(".ref-total")).to_have_text("100 of 500 companies · 100 people")
    sync_api.expect(page.locator(".card.ref")).to_have_count(24)
    # a search runs on every key over 500 companies: the whole run of typing is quick
    took = page.evaluate("""() => { const box = document.querySelector('.ref-q'); const t = performance.now();
      for (const v of ['p', 'pa', 'pat', 'pat1', 'pat12', 'pat123', 'pat1234']) { box.value = v; box.dispatchEvent(new Event('input')); }
      return performance.now() - t }""")
    assert took < 1500, took
    sync_api.expect(page.locator(".ref-total")).to_have_text("0 of 500 companies · 0 people")
    box.fill("lee0")
    sync_api.expect(page.locator(".ref-total")).to_have_text("100 of 500 companies · 100 people")
    assert page.errors == []


def test_a_company_with_many_people_lists_them_a_hundred_at_a_time_in_its_dialog(page, watchlist):
    people = "".join(f"Pat{i:03d},Lee{i:03d},https://www.linkedin.com/in/example-{i},,Initech,Engineer,01 Jan 2024\n" for i in range(130))
    open_referrals(page, watchlist, connections=HEADER + people, globex=False, companies=(("Initech", INITECH),))
    card(page, "Initech").get_by_role("button", name="+ 127 more people").click()
    dialog = page.locator(".ref-dialog")
    sync_api.expect(dialog.locator(".ref-p")).to_have_count(100)
    dialog.get_by_role("button", name="Show 30 more (30 not shown)").click()
    sync_api.expect(dialog.locator(".ref-p")).to_have_count(130)
    sync_api.expect(dialog.locator(".ref-showmore")).to_have_count(0)
    dialog.get_by_label("Search these people").fill("lee129")
    sync_api.expect(dialog.locator(".ref-p")).to_have_count(1)
    assert page.errors == []


# -- Hide companies with no openings -----------------------------------------------------------------------------------

def closed_postings(page, companies):
    """Have /api/referrals say every posting at these companies is closed (the page is told by the server: the details'
    `closed`), so a company with no open posting can be on the page, and reload the tab."""
    def handler(route):
        response = route.fetch()
        data = response.json()
        names = {n.lower() for n in companies}
        for person in data["people"]:
            if any(n in person["company"].lower() for n in names):
                for job in person["jobs"]:
                    data["details"][job["key"]]["closed"] = True
        route.fulfill(response=response, json=data)
    page.route("**/api/referrals", handler)
    page.reload()
    page.wait_for_load_state("networkidle")
    sync_api.expect(page.locator(".card.ref").first).to_be_visible()


@pytest.fixture
def quiet_page(page, watchlist):
    """Six companies: Initech (an applied job, its postings closed), Globex (a queued one, closed) and Umbrella, Hooli and
    Stark (open jobs gone closed), and Wayne (open)."""
    sparse = tuple((name, [("Platform Engineer", 85, "new")]) for name in ("Hooli", "Stark", "Wayne"))
    open_referrals(page, watchlist, connections=CONNECTIONS + EXTRA, companies=(("Initech", INITECH), ("Umbrella", UMBRELLA), *sparse))
    closed_postings(page, ["Initech", "Globex", "Umbrella", "Hooli", "Stark"])
    return page


def test_a_prominent_chip_hides_companies_with_no_openings_but_never_one_with_an_application_in_flight(quiet_page):
    page = quiet_page
    chip = page.get_by_role("button", name="Hide companies with no openings")
    sync_api.expect(chip).to_have_attribute("aria-pressed", "false")  # off by default
    sync_api.expect(page.locator(".card.ref")).to_have_count(6)
    # many have none: the page offers to hide them in one line
    sync_api.expect(page.locator(".ref-quiet")).to_contain_text("3 companies have no openings: hide them?")
    chip.focus()
    page.keyboard.press("Space")  # keyboard operable
    sync_api.expect(chip).to_have_attribute("aria-pressed", "true")
    # Initech (applied) and Globex (queued) stay although every posting there closed; Wayne is open
    assert sorted(n.split()[0] for n in company_names(page)) == ["Globex", "Initech", "Wayne"]
    sync_api.expect(page.locator(".ref-total")).to_have_text("3 of 6 companies · 7 people (3 hidden: no openings)")
    sync_api.expect(page.locator(".ref-quiet")).to_have_count(0)
    assert chip.locator("svg").count() == 1  # the eye-off icon
    page.keyboard.press("Enter")
    sync_api.expect(page.locator(".card.ref")).to_have_count(6)
    sync_api.expect(page.locator(".ref-total")).to_have_text("6 of 6 companies · 10 people")
    assert page.errors == []


def test_the_choice_is_remembered_like_the_other_referrals_settings_and_the_hint_turns_it_on(quiet_page):
    page = quiet_page
    page.locator(".ref-quiet").get_by_role("button", name="Hide them").click()
    sync_api.expect(page.locator(".card.ref")).to_have_count(3)
    assert page.evaluate("localStorage.getItem('jobwatch.referrals.noopen')") == "1"
    page.reload()
    sync_api.expect(page.get_by_role("button", name="Hide companies with no openings")).to_have_attribute("aria-pressed", "true")
    sync_api.expect(page.locator(".card.ref")).to_have_count(3)
    page.get_by_role("button", name="Hide companies with no openings").click()
    assert page.evaluate("localStorage.getItem('jobwatch.referrals.noopen')") == ""
    sync_api.expect(page.locator(".card.ref")).to_have_count(6)


def test_a_search_that_matches_a_hidden_company_says_so_and_one_click_shows_it(quiet_page):
    page = quiet_page
    page.get_by_role("button", name="Hide companies with no openings").click()
    box = page.get_by_label("Search people by name, company or title")
    box.fill("hooli")
    sync_api.expect(page.locator(".card.ref")).to_have_count(0)
    sync_api.expect(page.locator(".ref-hidden")).to_contain_text("1 match hidden by 'no openings'")
    page.locator(".ref-hidden").get_by_role("button", name="Show it").click()
    sync_api.expect(page.locator(".card.ref")).to_have_count(1)
    sync_api.expect(page.get_by_role("button", name="Hide companies with no openings")).to_have_attribute("aria-pressed", "false")
    sync_api.expect(page.locator(".ref-hidden")).to_have_count(0)
    box.fill("wayne")  # a company the filter keeps is not hidden by it: no hint
    page.get_by_role("button", name="Hide companies with no openings").click()
    sync_api.expect(page.locator(".card.ref")).to_have_count(1)
    sync_api.expect(page.locator(".ref-hidden")).to_have_count(0)


def test_when_the_filter_hides_every_company_the_page_says_so_and_offers_them_back(page, watchlist):
    open_referrals(page, watchlist, connections=CONNECTIONS + EXTRA, globex=False,
                   companies=tuple((n, [("Platform Engineer", 85, "new")]) for n in ("Hooli", "Stark", "Wayne")))
    closed_postings(page, ["Hooli", "Stark", "Wayne"])
    page.get_by_role("button", name="Hide companies with no openings").click()
    sync_api.expect(page.locator(".ref-grid .empty")).to_contain_text("Every company here has no openings (3 hidden).")
    sync_api.expect(page.locator(".ref-total")).to_have_text("0 of 3 companies · 0 people (3 hidden: no openings)")
    page.locator(".ref-grid").get_by_role("button", name="Show them").click()
    sync_api.expect(page.locator(".card.ref")).to_have_count(3)


def test_the_filter_works_with_the_paging(page, watchlist):
    n = 60
    people = "".join(f"Pat{i:03d},Lee{i:03d},https://www.linkedin.com/in/example-{i},,Company {i:03d},Engineer,01 Jan 2024\n" for i in range(n))
    open_referrals(page, watchlist, connections=HEADER + people, globex=False,
                   companies=tuple((f"Company {i:03d}", [("Platform Engineer", 70, "new")]) for i in range(n)))
    closed_postings(page, [f"Company {i:03d}" for i in range(0, n, 2)])  # every other company has nothing open
    sync_api.expect(page.locator(".card.ref")).to_have_count(24)
    page.get_by_role("button", name="Hide companies with no openings").click()
    sync_api.expect(page.locator(".ref-total")).to_have_text("30 of 60 companies · 30 people (30 hidden: no openings)")
    sync_api.expect(page.locator(".card.ref")).to_have_count(24)  # a page of the thirty that are left
    page.get_by_role("button", name=re.compile("Show 6 more companies")).click()
    sync_api.expect(page.locator(".card.ref")).to_have_count(30)
    sync_api.expect(page.locator(".ref-morehost")).to_be_empty()
    assert page.errors == []
