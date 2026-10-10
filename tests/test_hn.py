"""Hacker News' "Ask HN: Who is hiring?" thread: one job per company's post, read from HN's search API."""

import copy

import pytest

from jobwatch import config, sources, watch
from jobwatch.models import Job
from jobwatch.store import Store

from .conftest import NOW, FakeWeb

STORIES = f"{sources.HN_API}/search_by_date?tags=story,author_whoishiring&hitsPerPage=8"
OCT, SEP = 9000100, 9000000
DAY = 86400
T = int(NOW.timestamp())


def link(url: str) -> str:
    """A link as HN writes it in a post's HTML."""
    escaped = url.replace("/", "&#x2F;")
    return f'<a href="{escaped}" rel="nofollow">{escaped}</a>'


def post(id_: int, text: str, days_ago: int = 1) -> dict:
    return {"type": "comment", "id": id_, "author": f"user{id_}", "text": text, "created_at_i": T - days_ago * DAY,
            "parent_id": OCT, "children": [{"type": "comment", "id": id_ + 50, "author": "other",
                                            "text": "Is this role open to contractors?", "children": []}]}


ACME = post(9000101, "Acme | Senior Platform Engineer, ML Engineer | Remote (US) | $180k-$220k | "
                     f"{link('https://job-boards.greenhouse.io/acme/jobs/4001')}<p>We build rockets with Python "
                     "and LLMs.")
INITECH = post(9000102, "Initech — Backend Engineer — Austin, TX (ONSITE)<p>We make TPS reports fast. Go and "
                        f"Postgres.<p>Apply: {link('https://initech.example/careers')}", days_ago=2)
UMBRELLA = post(9000103, "Umbrella Corp | Berlin, Germany | Full-time | €80k–€100k<p>Open roles:<p>- Senior "
                         "Backend Engineer<p>- Product Designer<p>"
                         f"{link('https://www.linkedin.com/company/umbrella-example')} "
                         f"{link('https://jobs.lever.co/umbrella')}")
GLOBEX = post(9000104, "Globex is hiring engineers to build our billing platform, REMOTE in the US.<p>Email "
                       "jobs@globex.example and say you saw this on HN.")
REMARK = post(9000105, "Great thread, thanks for posting it every month.")
SEEKER = post(9000106, "Location: Denver<p>Remote: Yes<p>Willing to relocate: No<p>Technologies: Python")
DELETED = {"type": "comment", "id": 9000107, "author": None, "text": None, "children": []}
HOOLI = post(9000001, "Hooli | Staff Engineer | Remote | $200k-$250k", days_ago=31)


def thread(id_: int, title: str, posts: list[dict]) -> dict:
    return {"type": "story", "id": id_, "author": "whoishiring", "title": title, "text": "Please state the location.",
            "children": posts}


def hn_web(posts=None) -> dict:
    # The account posts three threads a month; the newest comes first.
    stories = {"hits": [
        {"objectID": str(OCT + 1), "title": "Ask HN: Who wants to be hired? (October 2026)"},
        {"objectID": str(OCT), "title": "Ask HN: Who is hiring? (October 2026)"},
        {"objectID": str(OCT + 2), "title": "Ask HN: Freelancer? Seeking freelancer? (October 2026)"},
        {"objectID": str(SEP), "title": "Ask HN: Who is hiring? (September 2026)"},
    ]}
    return {
        STORIES: stories,
        STORIES.replace("=8", "=12"): stories,
        f"{sources.HN_API}/items/{OCT}": thread(OCT, "Ask HN: Who is hiring? (October 2026)",
                                                posts or [ACME, INITECH, UMBRELLA, GLOBEX, REMARK, SEEKER, DELETED]),
        f"{sources.HN_API}/items/{SEP}": thread(SEP, "Ask HN: Who is hiring? (September 2026)", [HOOLI]),
    }


@pytest.fixture
def hn(monkeypatch):
    fake = FakeWeb(hn_web())
    monkeypatch.setattr(sources, "get_json", fake)
    monkeypatch.setattr(sources, "get_text", FakeWeb({}))  # no robots.txt: reading is allowed
    return fake


def by_company(jobs) -> dict[str, Job]:
    return {j.company_name: j for j in jobs}


def test_each_companys_post_is_one_job(hn):
    jobs = by_company(sources.fetch("hn", "whoishiring"))
    assert sorted(jobs) == ["Acme", "Globex", "Initech", "Umbrella Corp"]  # not the remark, seeker or deleted post
    acme = jobs["Acme"]
    assert acme.key == "hn:whoishiring:9000101" and acme.title == "Senior Platform Engineer, ML Engineer"
    assert acme.locations == ["Remote (US)"] and acme.remote
    assert (acme.salary_min, acme.salary_max, acme.currency) == (180000, 220000, "USD")
    # the job's own page on a board jobwatch reads, the HN post kept beside it; the board noted, not read
    assert acme.url == "https://job-boards.greenhouse.io/acme/jobs/4001"
    assert acme.posting_url == "https://news.ycombinator.com/item?id=9000101"
    assert acme.boards == ["greenhouse:acme"]
    assert "We build rockets" in acme.description and "<p>" not in acme.description
    assert acme.description.endswith("Posted in Ask HN: Who is hiring? (October 2026): "
                                     "https://news.ycombinator.com/item?id=9000101")
    assert acme.age_days() == 1
    # one request finds the thread, one reads it whole: no request per post, none to the job's own page
    assert hn.calls == [STORIES, f"{sources.HN_API}/items/{OCT}"]


def test_a_first_line_split_by_dashes(hn):
    initech = by_company(sources.fetch("hn", "whoishiring"))["Initech"]
    assert initech.title == "Backend Engineer" and initech.locations == ["Austin, TX (ONSITE)"]
    assert initech.remote is None and initech.salary_min is None
    assert initech.url == "https://initech.example/careers" and initech.boards == []


def test_roles_listed_further_on_and_pay_in_another_currency(hn):
    umbrella = by_company(sources.fetch("hn", "whoishiring"))["Umbrella Corp"]
    assert umbrella.title == "Senior Backend Engineer; Product Designer"
    assert umbrella.locations == ["Berlin, Germany"] and not umbrella.remote
    assert umbrella.salary_min is None  # €80k isn't a range in dollars
    assert umbrella.url == "https://jobs.lever.co/umbrella" and umbrella.boards == ["lever:umbrella"]  # not LinkedIn


def test_a_post_in_sentences(hn):
    globex = by_company(sources.fetch("hn", "whoishiring"))["Globex"]
    assert globex.title == "Open roles (see the post)" and globex.remote
    assert globex.url == "https://news.ycombinator.com/item?id=9000104" and globex.posting_url == ""


def test_a_post_read_before_is_kept_and_an_edited_one_read_again(hn):
    first = by_company(sources.fetch("hn", "whoishiring"))
    known = {j.key: j for j in first.values()}
    known["hn:whoishiring:9000101"].title = "As read before"
    known["hn:whoishiring:9000102"].description = "An older version of the post"
    again = by_company(sources.fetch("hn", "whoishiring", known=known))
    assert again["Acme"].title == "As read before" and again["Initech"].title == "Backend Engineer"


def test_the_last_months_threads(hn):
    jobs = sources.fetch("hn", "whoishiring/2")
    assert {j.company_name for j in jobs} == {"Acme", "Initech", "Umbrella Corp", "Globex", "Hooli"}
    assert {j.key for j in jobs} >= {"hn:whoishiring/2:9000001"}  # its own board: whoishiring/2's keys
    assert hn.calls[0].endswith("hitsPerPage=12") and f"{sources.HN_API}/items/{OCT + 1}" not in hn.calls
    assert len(sources.fetch("hn", "whoishiring", cap=2)) == 2


@pytest.mark.parametrize("board", ["acme", "whoishiring/0", "whoishiring/13", "whoishiring/x"])
def test_board_names(hn, board):
    with pytest.raises(sources.SourceError, match="whoishiring/N"):
        sources.fetch("hn", board)


def test_no_thread_found(hn):
    hn.responses[STORIES] = {"hits": []}
    with pytest.raises(sources.SourceError, match="thread found"):
        sources.fetch("hn", "whoishiring")


def test_robots_txt_is_obeyed(hn, monkeypatch):
    monkeypatch.setattr(sources, "get_text", FakeWeb({"https://hn.algolia.com/robots.txt":
                                                      "User-agent: *\nDisallow: /api/"}))
    with pytest.raises(sources.SourceError, match="doesn't allow"):
        sources.fetch("hn", "whoishiring")
    assert hn.calls == []


def test_finding_the_board(hn):
    assert sources.detect("https://news.ycombinator.com/submitted?id=whoishiring") == ("hn", "whoishiring")
    assert sources.detect("https://news.ycombinator.com/user?id=whoishiring") == ("hn", "whoishiring")
    assert sources.detect("https://news.ycombinator.com/item?id=9000101") is None  # one post: not a board
    hits = sources.probe("Hacker News")
    assert [(s, b) for s, b, _ in hits] == [("hn", "whoishiring")] and len(hits[0][2]) == 4


@pytest.fixture
def watched(tmp_path, hn):
    path = tmp_path / "jobwatch.yaml"
    path.write_text("companies:\n  - {source: hn, board: whoishiring, name: HN Who is hiring}\n"
                    "filters:\n  locations: [remote]\n  max_age_days: 30\n"
                    "keywords:\n  Python: 2\n  LLM: 3\n"
                    "state: state.db\ncache: cache\n")
    cfg = config.load(path)
    store = Store(cfg.state)
    yield cfg, store
    store.close()


def test_watching_the_thread(watched, hn):
    cfg, store = watched
    assert [(b.source, b.board) for b in cfg.boards] == [("hn", "whoishiring")]
    r = watch.fetch_all(cfg, store)
    assert (r.boards, r.jobs, len(r.new), r.errors) == (1, 4, 4, {})
    names = {j.key: j.display_company for j, _ in store.jobs()}
    assert names["hn:whoishiring:9000101"] == "Acme"  # each post's own company, not the watchlist's name
    # remote jobs pass the filters: Acme (the keywords rank it first) and Globex
    assert [e.job.company_name for e in watch.build_digest(cfg, store).entries] == ["Acme", "Globex"]
    # a post deleted (or flagged) is gone from the thread: its job closes
    web = hn_web([ACME, UMBRELLA, GLOBEX])
    hn.responses = web
    r = watch.fetch_all(cfg, store)
    assert r.new == [] and r.jobs == 3
    open_keys = {j.key for j, _ in store.jobs()}
    assert "hn:whoishiring:9000102" not in open_keys and "hn:whoishiring:9000101" in open_keys
    known = store.board_jobs("hn", "whoishiring")
    boards: dict = {}  # checking queued jobs reads the thread once
    hn.calls.clear()
    assert watch.still_open(known["hn:whoishiring:9000101"], boards=boards)
    assert not watch.still_open(known["hn:whoishiring:9000102"], boards=boards)
    assert hn.calls.count(f"{sources.HN_API}/items/{OCT}") == 1
    # a post edited is read again
    edited = copy.deepcopy(ACME)
    edited["text"] = edited["text"].replace("ML Engineer", "Research Engineer")
    hn.responses = hn_web([edited, UMBRELLA, GLOBEX])
    watch.fetch_all(cfg, store)
    assert store.board_jobs("hn", "whoishiring")["hn:whoishiring:9000101"].title == \
        "Senior Platform Engineer, Research Engineer"
