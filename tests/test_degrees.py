"""A degree requirement your education meets isn't a gap: it leaves the gaps and counts as met (degrees.py)."""

from datetime import UTC, datetime, timedelta

import pytest
import yaml

from jobwatch import advice, cli, config, report
from jobwatch.degrees import SEPARATOR, load, meets, parse_degree, profile_file, reconcile, required_level
from jobwatch.models import Job
from jobwatch.score import resume_id
from jobwatch.store import Store
from jobwatch.watch import Entry
from jobwatch.web import App

BACHELOR = "Bachelor of Science degree in Computer Science or a related technical/analytical discipline"
DISTRIBUTED = "Strong distributed-systems background, including retries, idempotency, and recovery"

MASTERS = parse_degree("MS in Computer Science, Security concentration")
BACHELORS_CS = parse_degree("B.S. in Computer Science")
BACHELORS_CIVIL = parse_degree("Bachelor of Technology, Civil Engineering")
ASSIGNED = (MASTERS, BACHELORS_CIVIL)


def fit(gaps, met=5, total=10, **more):
    return {"score": 65.4, "must_haves_met": met, "must_haves_total": total, "gaps": list(gaps),
            "summary": "ok", "flags": [], **more}


# -- the profile

def write_profile(tmp_path, education):
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump({"name": "Jane Doe", "education": education} if education is not None
                                   else {"name": "Jane Doe"}))
    return path


def test_the_profile_s_education_is_read(tmp_path):
    path = write_profile(tmp_path, [
        {"school": "Initech State University", "degree": "MS in Computer Science, Security concentration"},
        {"school": "Globex Polytechnic", "degree": "Bachelor of Technology, Civil Engineering"}])
    degrees = load(path)
    assert [(d.level, d.technical) for d in degrees] == [(2, True), (1, True)]
    assert degrees[0].text == "MS in Computer Science, Security concentration"


@pytest.mark.parametrize("education", [None, [], [{"school": "Initech State University"}],
                                       [{"degree": "Certificate in Welding"}]])
def test_a_profile_with_no_degrees_reads_as_none(tmp_path, education):
    assert load(write_profile(tmp_path, education)) == ()


def test_no_profile_file_or_a_broken_one_reads_as_none(tmp_path):
    assert load(None) == () and load(tmp_path / "missing.yaml") == ()
    broken = tmp_path / "profile.yaml"
    broken.write_text("education: [unclosed")
    assert load(broken) == ()


def test_the_profile_is_found_next_to_the_watchlist_else_in_resume_kits_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("RESUME_KIT_CONTENT", str(tmp_path / "content"))
    watchlist = tmp_path / "list" / "jobwatch.yaml"
    watchlist.parent.mkdir()
    assert profile_file(watchlist) is None
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "profile.yaml").write_text("education: []")
    assert profile_file(watchlist) == tmp_path / "content" / "profile.yaml"
    (watchlist.parent / "profile.yaml").write_text("education: []")
    assert profile_file(watchlist) == watchlist.parent / "profile.yaml"


# -- what a requirement asks for

@pytest.mark.parametrize("text, level", [
    (BACHELOR, 1),
    ("Master's degree in Computer Science", 2),
    ("BS in Computer Science or MS in Physics", 1),
    ("A degree in a technical field", 1),
    ("Bachelor's degree or equivalent experience", 1),
    ("PhD in Computer Science", None),
    ("Master's degree; a PhD is a plus", None),
    ("7+ years of relevant software development experience with a BS", None),
    ("Bachelor's degree and AWS certification", None),
    ("Proficiency in MS Office", None),
    (DISTRIBUTED, None),
])
def test_what_level_a_requirement_asks_for(text, level):
    assert required_level(text) == level


# -- when your education meets it

def test_a_bachelors_requirement_is_met_by_a_masters_in_the_same_field():
    assert meets(BACHELOR, (MASTERS,)) is MASTERS


def test_a_bachelors_requirement_is_met_by_a_bachelors():
    assert meets("Bachelor's degree in Computer Science", (BACHELORS_CS,)) is BACHELORS_CS


def test_or_a_related_discipline_takes_a_related_degree():
    assert meets(BACHELOR, (BACHELORS_CIVIL,)) is BACHELORS_CIVIL
    assert meets("BS in Computer Science or a related field", (BACHELORS_CIVIL,)) is BACHELORS_CIVIL


def test_a_field_the_profile_lacks_is_not_met():
    assert meets("Bachelor's degree in Computer Science", (BACHELORS_CIVIL,)) is None
    assert meets("Bachelor's degree in Nursing or a related field", (MASTERS,)) is None
    assert meets("Bachelor's degree in Nursing", (MASTERS,)) is None


def test_a_masters_requirement_is_not_met_by_a_bachelors():
    assert meets("Master's degree in Computer Science", (BACHELORS_CS,)) is None
    assert meets("Master's degree in Computer Science", (MASTERS,)) is MASTERS


def test_a_degree_with_no_field_is_met_by_any_degree():
    assert meets("Bachelor's degree", (BACHELORS_CIVIL,)) is BACHELORS_CIVIL


def test_a_phd_requirement_is_never_met():
    assert meets("PhD in Computer Science", (MASTERS,)) is None


def test_no_education_meets_nothing():
    assert meets(BACHELOR, ()) is None


# -- the fit

def test_a_met_degree_leaves_the_gaps_and_counts_as_met():
    out = reconcile(fit([BACHELOR, DISTRIBUTED]), ASSIGNED)
    assert out["gaps"] == [DISTRIBUTED]
    assert (out["must_haves_met"], out["must_haves_total"]) == (6, 10)
    assert out["score"] == 65.4  # never made again
    assert len(out["reconciled"]) == 1 and out["reconciled"][0].startswith(BACHELOR)
    assert "MS in Computer Science" in out["reconciled"][0]


def test_only_the_degree_part_of_a_joined_gap_goes():
    joined = f"{BACHELOR}{SEPARATOR}{DISTRIBUTED}"
    out = reconcile(fit([joined]), ASSIGNED)
    assert out["gaps"] == [DISTRIBUTED]
    assert out["must_haves_met"] == 6


def test_a_gap_that_is_only_degrees_is_dropped_whole():
    out = reconcile(fit([f"{BACHELOR}{SEPARATOR}Bachelor's degree in Computer Science"]), ASSIGNED)
    assert out["gaps"] == [] and out["must_haves_met"] == 7


def test_met_never_passes_total():
    assert reconcile(fit([BACHELOR], met=10, total=10), ASSIGNED)["must_haves_met"] == 10


@pytest.mark.parametrize("gaps", [["PhD in Computer Science"], [DISTRIBUTED], ["Bachelor's degree in Nursing"], []])
def test_other_gaps_are_left_as_they_were(gaps):
    original = fit(gaps)
    assert reconcile(original, ASSIGNED) is original


def test_no_education_changes_nothing():
    original = fit([BACHELOR])
    assert reconcile(original, ()) is original
    assert reconcile(None, ASSIGNED) is None


def test_the_requirement_rows_of_a_met_degree_turn_met():
    rows = [{"requirement": BACHELOR, "kind": "must_have", "verdict": "partial", "evidence": []},
            {"requirement": DISTRIBUTED, "kind": "must_have", "verdict": "partial", "evidence": []},
            {"requirement": BACHELOR, "kind": "nice_to_have", "verdict": "partial", "evidence": []}]
    out = reconcile(fit([BACHELOR, DISTRIBUTED], requirements=rows), ASSIGNED)["requirements"]
    assert out[0]["verdict"] == "met" and "MS in Computer Science" in out[0]["reconciled"]
    assert out[1] == rows[1] and out[2] == rows[2]
    assert rows[0]["verdict"] == "partial"  # the stored one is not touched


def test_a_met_degree_changes_what_the_advice_says(watchlist):
    """7 of 10 must-haves is a stretch; with the degree met it's 8 of 10, which isn't."""
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    j = Job("lever", "globex", "1", "Staff Engineer", "https://example.com/1", company_name="Globex",
            salary_min=190000, salary_max=260000, posted=datetime.now(UTC) - timedelta(days=10))

    def call(f):
        e = Entry(j, {"status": "new"}, 0, [], fit=f)
        h = advice.History(store)
        return advice.verdict(e, h, advice.advise(cfg, e, h))["call"]

    original = {**fit([BACHELOR], met=7, total=10), "score": 84.0}
    assert call(original) == "stretch"
    assert call(reconcile(original, ASSIGNED)) == "apply"


def test_fit_lines_say_it_was_reconciled():
    lines = report.fit_lines(reconcile(fit([BACHELOR]), ASSIGNED))
    assert lines[0] == "Fit 65/100, must-haves 6/10"
    assert lines[1].startswith("Reconciled with your profile (the score was not made again): ")


# -- through the store and the page's API

def _job_scored(web, watchlist, gaps, met=1, total=2):
    cli.main(["-c", str(watchlist), "fetch"])
    cv = watchlist.parent / "cv.md"
    cv.write_text("# Jane Doe")
    config.save(watchlist, {"resume": str(cv)})
    cfg = config.load(watchlist)
    rid = resume_id(cfg.resume)
    store = Store(cfg.state)
    store.save_score("lever:globex:aaaa-1111", rid, {**fit(gaps, met, total), "score": 81.0})
    store.close()
    return cfg, rid


def test_the_store_reads_scores_reconciled_when_it_has_the_education(web, watchlist):
    cfg, rid = _job_scored(web, watchlist, [BACHELOR])
    plain = Store(cfg.state)
    assert plain.score("lever:globex:aaaa-1111", rid)["gaps"] == [BACHELOR]
    plain.close()
    store = Store(cfg.state, education=ASSIGNED)
    got = store.score("lever:globex:aaaa-1111", rid)
    assert got["gaps"] == [] and got["must_haves_met"] == 2
    assert store.scores(rid)["lever:globex:aaaa-1111"]["must_haves_met"] == 2
    store.close()


def test_today_shows_the_reconciled_fit(web, watchlist):
    _job_scored(web, watchlist, [BACHELOR])
    jobs = {j["key"]: j for j in App(watchlist).get_digest({})["jobs"]}
    assert jobs["lever:globex:aaaa-1111"]["fit"]["gaps"] == [BACHELOR]  # no profile yet
    write_profile(watchlist.parent, [{"school": "Initech State University",
                                      "degree": "MS in Computer Science, Security concentration"}])
    fitted = {j["key"]: j for j in App(watchlist).get_digest({})["jobs"]}["lever:globex:aaaa-1111"]["fit"]
    assert fitted["gaps"] == [] and fitted["must_haves_met"] == 2
    assert fitted["reconciled"] and "MS in Computer Science" in fitted["reconciled"][0]


def test_show_prints_the_reconciliation(web, watchlist, capsys):
    _job_scored(web, watchlist, [BACHELOR])
    write_profile(watchlist.parent, [{"degree": "Bachelor of Science in Computer Science"}])
    capsys.readouterr()
    cli.main(["-c", str(watchlist), "show", "aaaa-1111"])
    out = capsys.readouterr().out
    assert "Fit 81/100, must-haves 2/2" in out and "Reconciled with your profile" in out
