"""What Prepare has saved for a job, read back for the Queue and Company payloads: the kept resume, the last ATS check
(kept by ats.check, since it was only ever shown) and the newest cover letter version. All of it is read from files,
so none of these tests fakes a model."""

import json

import pytest

from jobwatch import ats, config, cover, prepare
from jobwatch.store import Store
from jobwatch.web import App

from .test_ats import POSTING, RESUME

LETTER = "Hello Initech team,\n\nI ran platform work at Globex. Thank you for your time.\n"


@pytest.fixture
def ctx(tmp_path):
    (tmp_path / "resume.txt").write_text(RESUME)
    path = tmp_path / "jobwatch.yaml"
    path.write_text("companies: []\nresume: resume.txt\nstate: state.db\n")
    cfg = config.load(path)
    store = Store(cfg.state)
    job = store.add("Initech", "Senior Platform Engineer", status="queued", description=POSTING)
    yield cfg, store, job, path
    store.close()


def card(path, key):
    return next(c for c in App(path).get_queue({}) if c["key"] == key)


def test_a_job_with_nothing_prepared_has_an_empty_prepare_field(ctx):
    _, _, job, path = ctx
    assert card(path, job.key)["prepare"] == {}


def test_an_ats_check_is_kept_and_comes_back_with_the_queue(ctx):
    cfg, store, job, path = ctx
    got = ats.check(cfg, store, job.key)
    saved = card(path, job.key)["prepare"]
    assert set(saved) == {"ats"}  # no resume kept for the job, no letter yet
    keep = saved["ats"]
    assert keep["score"] == got["score"] and keep["found"] == got["found"] and keep["missing"] == got["missing"]
    assert keep["file"] == "resume.txt" and keep["tailored"] is False and keep["read_with"] == "text"
    assert keep["checks"] == [] and keep["older"] is False
    assert len(keep["at"]) == 25 and keep["at"][4] == "-"  # an ISO timestamp with its offset
    assert not {"posting", "resume"} & set(keep)  # the fingerprints stay on disk


def test_the_ats_file_sits_beside_the_cover_versions(ctx):
    cfg, store, job, _ = ctx
    ats.check(cfg, store, job.key)
    cover.save(store, job.key, LETTER, "direct", "", "m")
    folder = cover.folder(store, job.key)
    assert sorted(p.name for p in folder.iterdir()) == ["ats.json", "v1.json", "v1.md"]
    assert [v["version"] for v in cover.versions(store, job.key)] == [1]  # the ATS file isn't a letter version


def test_a_check_of_some_other_file_is_not_kept(ctx, tmp_path):
    cfg, store, job, path = ctx
    other = tmp_path / "other.txt"
    other.write_text(RESUME)
    ats.check(cfg, store, job.key, resume=other)
    assert card(path, job.key)["prepare"] == {}


def test_a_failed_check_keeps_nothing(ctx):
    cfg, store, job, path = ctx
    cfg.resume = None
    with pytest.raises(ValueError):
        ats.check(cfg, store, job.key)
    assert card(path, job.key)["prepare"] == {}


def test_the_newest_letter_version_and_the_kept_resume_come_with_the_queue(ctx):
    _, store, job, path = ctx
    store.package(job.key).attach("Jordan_Rivera_Resume_Initech.pdf", b"%PDF-1 fake", "resume")
    cover.save(store, job.key, LETTER, "direct", "", "m")
    cover.save(store, job.key, LETTER + "Plain words fill it out.\n", "warm", "", "m")
    saved = card(path, job.key)["prepare"]
    assert saved["resume"] == {"state": "ok", "label": "Resume", "name": "Jordan_Rivera_Resume_Initech.pdf"}
    day = saved["cover"].pop("at")
    assert saved["cover"] == {"version": 2, "tone": "warm", "words": len(LETTER.split()) + 5}
    assert day[:2] == "20"  # the day it was drafted
    assert "ats" not in saved


def test_a_letter_without_its_json_still_counts(ctx):
    _, store, job, path = ctx
    cover.save(store, job.key, LETTER, "direct", "", "m")
    cover.folder(store, job.key).joinpath("v1.json").unlink()
    assert card(path, job.key)["prepare"]["cover"]["version"] == 1


def test_the_check_is_older_when_the_posting_text_changed_after_it(ctx):
    cfg, store, job, path = ctx
    ats.check(cfg, store, job.key)
    store.set_description(job.key, POSTING + "\n- Also: Scala\n")
    assert card(path, job.key)["prepare"]["ats"]["older"] is True


def test_the_check_is_older_when_the_resume_was_rebuilt_after_it(ctx):
    cfg, store, job, path = ctx
    ats.check(cfg, store, job.key)
    assert card(path, job.key)["prepare"]["ats"]["older"] is False
    store.package(job.key).attach("Resume_Initech.pdf", b"%PDF-1 a newer build", "resume")
    assert card(path, job.key)["prepare"]["ats"]["older"] is True  # now another file is the job's resume


def test_an_unreadable_ats_file_is_ignored(ctx):
    cfg, store, job, path = ctx
    ats.check(cfg, store, job.key)
    (cover.folder(store, job.key) / prepare.ATS_FILE).write_text("{not json")
    assert card(path, job.key)["prepare"] == {}
    (cover.folder(store, job.key) / prepare.ATS_FILE).write_text(json.dumps({"score": 5}))
    assert card(path, job.key)["prepare"] == {}


def test_the_company_page_has_the_field_too(ctx):
    cfg, store, job, path = ctx
    ats.check(cfg, store, job.key)
    jobs = App(path).get_company({"q": ["Initech"]})["jobs"]
    assert jobs[0]["prepare"]["ats"]["score"] is not None
