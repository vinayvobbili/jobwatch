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
    assert "6 matching job(s)." in digest and "Staff AI Engineer" in digest and "Fit 86/100" in digest


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
