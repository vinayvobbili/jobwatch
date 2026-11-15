"""The demo the videos are recorded on (scripts/demo/seed.py): made-up companies, jobs and records in its own folder."""

import importlib.util
from pathlib import Path

import pytest

from jobwatch import config
from jobwatch.store import Store

DEMO = Path(__file__).resolve().parents[1] / "scripts" / "demo"


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"demo_{name}", DEMO / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def out(tmp_path):
    out = tmp_path / "out"
    load("seed").seed(out / "demo")
    return out


def test_seed_keeps_made_up_jobs_in_its_own_folder(out):
    cfg = config.load(out / "demo" / "jobwatch.yaml")
    assert cfg.state.resolve() == (out / "demo" / "state" / "state.db").resolve()
    store = Store(cfg.state)
    try:
        rows = store.jobs(include_closed=True)
        assert {j.display_company for j, _ in rows} == {"Acme", "Globex", "Initech", "Umbrella", "Hooli"}
        assert len(rows) == 13
        assert {rec["status"] for _, rec in store.applications()} == {"applied", "screening", "interviewing",
                                                                      "rejected"}
        assert len(store.jobs(("queued",))) == 2
        assert [j for j, _ in rows if j.salary_min is None and j.salary_max is None]  # a job with no pay clue
    finally:
        store.close()


def test_today_opens_on_the_fit_and_pay_chips(out):
    cfg = config.load(out / "demo" / "jobwatch.yaml")
    assert (cfg.today_fit, cfg.today_pay) == (80, 175000)


def test_seed_more_adds_the_tutorials_records_and_leaves_the_plain_demo_alone(tmp_path):
    seed = load("seed").seed
    seed(tmp_path / "plain")
    cfg = config.load(seed(tmp_path / "more", more=True))
    assert cfg.connections and cfg.connections.is_file() and cfg.stories.is_file() and cfg.prep.sheets.is_dir()
    assert config.load(tmp_path / "plain" / "jobwatch.yaml").connections is None
    store = Store(cfg.state)
    try:
        assert {rec["status"] for _, rec in store.applications()} >= {"offer", "interviewing", "screening"}
        assert store.comps() and store.healths() and store.contact_feedback()
        assert all(rec["first_seen"][:10] < rec["applied_at"] for _, rec in store.applications())
        assert cfg.fetch_every is None and store.last_fetch()["errors"] == {}  # checked earlier; no board is asked
        initech = store.package("ashby:initech:c0")
        assert len(initech.data()["files"]) == 2 and initech.practised()
        assert {u["name"]: u["entry"] for u in store.unwatched()} == {  # boards given: none is looked up on the web
            "Pied Piper": "greenhouse:piedpiper", "Cyberdyne": "greenhouse:cyberdyne",
            "Soylent": "greenhouse:soylent", "Vandelay Industries": "greenhouse:vandelayindustries"}
        assert all(store.logo(k) for k in ("acme", "initech", "soylent"))  # no logo is looked up on the web
    finally:
        store.close()
    plain = Store(tmp_path / "plain" / "state" / "state.db")
    try:
        assert not plain.comps() and len(plain.jobs(include_closed=True)) == 13
    finally:
        plain.close()


def test_seeding_again_only_replaces_a_demo_folder(tmp_path):
    seed = load("seed").seed
    seed(tmp_path / "demo")
    seed(tmp_path / "demo")
    mine = tmp_path / "mine"
    mine.mkdir()
    (mine / "state.db").write_text("someone's history")
    with pytest.raises(SystemExit, match="isn't a jobwatch demo"):
        seed(mine)
    assert (mine / "state.db").read_text() == "someone's history"
