"""Filters of a board's own: a watchlist entry's filters: replace the watchlist's settings for that board's jobs
(a college's adjunct openings: other titles, hourly pay), everywhere a job is judged. Every other job keeps the
watchlist's. No network: the boards are made up."""

import pytest

from jobwatch import config, sources, watch
from jobwatch.filters import Filters
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.web import App

WATCHLIST = """\
teaching: &teaching
  titles: [adjunct, instructor]
  min_salary: 0
companies:
  - greenhouse:acme
  - {board: 'greenhouse:oakmerecc', filters: *teaching}
  - {source: workday, board: tarn.wd1/Careers, name: Tarn County, filters: *teaching}
filters:
  titles: [engineer]
  exclude_titles: [contract]
  min_salary: 178000
state: state.db
"""


@pytest.fixture
def path(tmp_path):
    p = tmp_path / "jobwatch.yaml"
    p.write_text(WATCHLIST)
    return p


def job(board: str, pid: str, title: str, low: int, high: int) -> Job:
    return Job(source="greenhouse", company=board, id=pid, title=title, url=f"https://example.com/{board}/{pid}",
               salary_min=low, salary_max=high, currency="USD", locations=["Fernhollow, OR"])


def test_a_boards_filters_replace_the_watchlists_one_by_one(path):
    cfg = config.load(path)
    own = cfg.filters_for(job("oakmerecc", "1", "Adjunct Instructor", 72_800, 72_800))
    assert own.titles == ["adjunct", "instructor"] and own.min_salary == 0
    assert own.exclude_titles == ["contract"]  # not set on the board: the watchlist's
    assert cfg.filters_for(job("acme", "1", "Engineer", 1, 1)) is cfg.filters
    assert cfg.filters_for(job("globex", "1", "Engineer", 1, 1)) is cfg.filters  # not watched: the watchlist's
    county = next(b for b in cfg.boards if b.board == "tarn.wd1/Careers")
    assert cfg.filters_of(county) == own  # one YAML anchor shared by two boards
    assert cfg.filters_of(cfg.boards[0]) is cfg.filters


@pytest.mark.parametrize("entry, error", [
    ("{board: 'greenhouse:oakmerecc', filters: {title: [adjunct]}}", r"greenhouse:oakmerecc: unknown filter setting"),
    ("{board: 'greenhouse:oakmerecc', filters: [adjunct]}", r"greenhouse:oakmerecc: filters are settings"),
    ("{board: 'greenhouse:oakmerecc', filters: {titles: ['c(']}}", r"greenhouse:oakmerecc: filters.titles: 'c\('"),
    ("{board: 'greenhouse:oakmerecc', filters: {min_fit: 200}}", r"greenhouse:oakmerecc: filters.min_fit"),
])
def test_a_boards_filters_are_checked_like_the_watchlists(path, entry, error):
    path.write_text(f"companies:\n  - {entry}\nstate: state.db\n")
    with pytest.raises(config.ConfigError, match=error):
        config.load(path)


def test_its_jobs_are_judged_by_them_and_the_rest_by_the_watchlists(path):
    cfg = config.load(path)
    store = Store(cfg.state)
    store.sync("greenhouse", "oakmerecc", [job("oakmerecc", "1", "Adjunct Instructor, Cybersecurity", 72_800, 72_800),
                                            job("oakmerecc", "2", "Dispatcher", 41_600, 41_600)])
    store.sync("greenhouse", "acme", [job("acme", "1", "Adjunct Instructor", 72_800, 72_800),
                                      job("acme", "2", "Staff Engineer", 200_000, 240_000)])
    shown = {e.job.key for e in watch.build_digest(cfg, store).entries}
    assert shown == {"greenhouse:oakmerecc:1", "greenhouse:acme:2"}
    hidden = watch.hidden(cfg, store)["by"]
    assert hidden == {"title": 2}  # the dispatcher at the college, the adjunct role at acme
    store.close()


def test_a_searched_board_is_searched_for_its_own_titles(path, monkeypatch):
    cfg = config.load(path)
    asked = {}

    def fetch(source, board, get=None, search=(), wanted=None, known=None, cap=0):
        asked[board] = (list(search), wanted("Adjunct Instructor"), wanted("Staff Engineer"))
        return []
    monkeypatch.setattr(sources, "fetch", fetch)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    assert asked["tarn.wd1/Careers"] == (["adjunct", "instructor"], True, False)
    assert asked["acme"] == (["engineer"], False, True)
    store.close()


def test_a_track_judges_its_kind_of_job_from_any_board(path):
    path.write_text(WATCHLIST + "tracks:\n  - name: teaching\n    titles: ['\\b(adjunct|instructor)\\b']\n"
                    "    filters: {titles: [cyber], min_salary: 0}\n")
    cfg = config.load(path)
    adjunct = job("globex", "1", "Adjunct Instructor, Cybersecurity", 72_800, 72_800)  # an alert's, not watched
    assert cfg.filters_for(adjunct).titles == ["cyber"] and cfg.filters_for(adjunct).exclude_titles == ["contract"]
    assert cfg.filters_for(job("globex", "2", "Staff Engineer", 1, 1)) is cfg.filters
    assert cfg.filters_for(job("oakmerecc", "1", "Adjunct Instructor", 1, 1)).titles == ["adjunct", "instructor"]
    store = Store(cfg.state)
    store.sync("greenhouse", "globex", [adjunct, job("globex", "3", "Adjunct Instructor, Biology", 72_800, 72_800)])
    assert {e.job.key for e in watch.build_digest(cfg, store).entries} == {"greenhouse:globex:1"}
    store.close()


def test_a_digest_for_one_company_lists_only_its_jobs(path):
    cfg = config.load(path)
    store = Store(cfg.state)
    store.sync("greenhouse", "acme", [job("acme", "1", "Staff Engineer", 200_000, 250_000)])
    store.sync("greenhouse", "globex", [job("globex", "2", "Staff Engineer", 200_000, 250_000)])
    assert {e.job.key for e in watch.build_digest(cfg, store, company="Acme, Inc.").entries} == {"greenhouse:acme:1"}
    assert len(watch.build_digest(cfg, store).entries) == 2  # no company: every one
    assert watch.build_digest(cfg, store, company="Initech").entries == []
    store.close()


@pytest.mark.parametrize("track, error", [
    ("[adjunct]", r"tracks entry 1 looks like"),
    ("{titles: ['c(']}", r"tracks entry 1: 'c\(' isn't a regex"),
    ("{titles: [adjunct], filters: {title: [x]}}", r"tracks entry 1: filters .* unknown: title"),
    ("{titles: [adjunct], filters: {min_fit: 200}}", r"tracks entry 1: filters.min_fit"),
])
def test_a_track_is_checked(path, track, error):
    path.write_text(f"tracks:\n  - {track}\nstate: state.db\n")
    with pytest.raises(config.ConfigError, match=error):
        config.load(path)


def test_rewriting_the_watchlist_keeps_a_boards_filters(path):
    teaching = {"titles": ["adjunct", "instructor"], "min_salary": 0}
    own = lambda cfg: {b.entry: b.filters for b in cfg.boards}  # noqa: E731
    assert own(config.add_board(path, "lever:globex"))["greenhouse:oakmerecc"] == teaching
    assert own(config.add_board(path, "greenhouse:oakmerecc", "Oakmere CC"))["greenhouse:oakmerecc"] == teaching
    # The page's Settings: it shows them, and a board it sends back without them keeps the file's.
    app = App(path)
    s = app.get_settings({})
    assert {"source": "greenhouse", "board": "oakmerecc", "name": "Oakmere CC", "filters": teaching} in s["companies"]
    app.post_settings({"companies": [{k: v for k, v in c.items() if k != "filters"} for c in s["companies"]]})
    cfg = config.load(path)
    assert own(cfg)["greenhouse:oakmerecc"] == teaching and own(cfg)["workday:tarn.wd1/Careers"] == teaching
    assert cfg.filters_of(cfg.boards[1]) == Filters.from_dict({"titles": ["adjunct", "instructor"], "min_salary": 0,
                                                               "exclude_titles": ["contract"]})
