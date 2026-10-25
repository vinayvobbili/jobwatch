"""The demo video's scripts (scripts/demo): the seeded demo, and the slides and reel built from it. They run
without a browser or slidecast: the screenshots are stand-ins."""

import importlib.util
from pathlib import Path

import pytest
import yaml

from jobwatch import config
from jobwatch.store import Store

DEMO = Path(__file__).resolve().parents[1] / "scripts" / "demo"
SHOTS = ("settings", "today", "chat", "queue", "applied", "prep", "prep-questions", "skills")
SLIDES = ("01-title", "02-watch", "03-digest", "04-fit", "04b-chat", "05-queue", "06-track", "07-prep",
          "07b-skills", "08-mcp", "09-never")


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"demo_{name}", DEMO / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def out(tmp_path):
    """A demo's output folder: the seeded demo, and stand-in screenshots (build.py only inlines their bytes)."""
    out = tmp_path / "out"
    load("seed").seed(out / "demo")
    (out / "shots").mkdir()
    for name in SHOTS:
        (out / "shots" / f"{name}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return out


def test_seed_keeps_made_up_jobs_in_its_own_folder(out):
    cfg = config.load(out / "demo" / "jobwatch.yaml")
    assert cfg.state.resolve() == (out / "demo" / "state" / "state.db").resolve()
    store = Store(cfg.state)
    try:
        rows = store.jobs(include_closed=True)
        assert {j.display_company for j, _ in rows} == {"Acme", "Globex", "Initech", "Umbrella", "Hooli"}
        assert len(rows) == 12
        assert {rec["status"] for _, rec in store.applications()} == {"applied", "screening", "interviewing",
                                                                      "rejected"}
        assert len(store.jobs(("queued",))) == 2
    finally:
        store.close()


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
        assert not plain.comps() and len(plain.jobs(include_closed=True)) == 12
    finally:
        plain.close()


def test_the_guide_tutorials_are_built_from_seeded_screenshots(tmp_path):
    out = tmp_path / "out"
    tutorials = Path(__file__).resolve().parents[1] / "scripts" / "tutorials"
    spec = importlib.util.spec_from_file_location("tutorials_build", tutorials / "build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    shots = out / "tut-shots"
    shots.mkdir(parents=True)
    for name in ("first-run", "jobs", "companies", "ai", "ai-settings", "queue", "queue-add", "suggest", "applied",
                 "applied-table", "applied-quiet", "interviews", "company", "sent", "prep", "prep-practised",
                 "comps", "comps-table", "referrals"):
        (shots / f"{name}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (out / "shots").mkdir()
    for name in ("today", "details", "queue", "applied", "prep"):
        (out / "shots" / f"{name}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    reels = build.tutorials(shots, out / "shots")
    guide = {name: slides for name, slides in reels.items() if name[:2] in ("04", "05", "06", "07")}
    assert list(guide) == ["04-applying", "05-tracking", "06-interview-prep", "07-comps-and-contacts"]
    for slides in guide.values():
        assert 6 <= len(slides) <= 9 and all(narration for _, _, narration in slides)
        assert "localhost" not in "".join(html for _, html, _ in slides)


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


def test_build_writes_every_slide_and_the_reel(out):
    spec = load("build").build(out)
    assert [s["html_file"] for s in spec["slides"]] == [f"slides/{name}.html" for name in SLIDES]
    assert all((out / s["html_file"]).is_file() and s["narration"] for s in spec["slides"])
    assert spec["tts"] == {"provider": "mlx", "voice": "af_heart",
                           "phonetic": {r"\bjobwatch\b": "job watch", r"\bMCP\b": "M C P", r"\bAPI\b": "A P I"}}
    assert "music" not in spec and "intro" not in spec  # no music files: the voice only
    assert yaml.safe_load((out / "reel.yaml").read_text()) == spec
    digest = (out / "slides" / "03-digest.html").read_text()
    assert "6 matching job(s)." in digest and "Staff Data Engineer" in digest and "Fit 86/100" in digest


def test_build_takes_the_music_from_a_folder_or_its_own(out, tmp_path):
    build = load("build").build
    music = tmp_path / "music"
    music.mkdir()
    (music / "music_bed.wav").write_bytes(b"")
    with pytest.raises(SystemExit, match=r"no intro_sting.wav, outro_sting.wav: `slidecast compose -o"):
        build(out, music)
    for name in ("intro_sting.wav", "outro_sting.wav"):
        (music / name).write_bytes(b"")
    spec = build(out, music)
    assert spec["music"]["file"] == str((music / "music_bed.wav").resolve()) and spec["music"]["duck"] is True
    assert spec["outro"] == {"file": str((music / "outro_sting.wav").resolve()), "volume": 0.7}
    for name in ("music_bed.wav", "intro_sting.wav", "outro_sting.wav"):  # next to reel.yaml: named as they are
        (out / name).write_bytes(b"")
    assert build(out)["intro"] == {"file": "intro_sting.wav", "volume": 0.75}
