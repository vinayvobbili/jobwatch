"""What the CLI reports about scoring and the page's work, read from the store: `scored` (the scores made from a
day on and who made each), `activity` (the page's Activity list) and `score --cost` (Settings' Fit scoring panel)."""

from datetime import date, datetime, timedelta, timezone

import pytest
import yaml

from jobwatch import cli, config
from jobwatch.models import Job
from jobwatch.score import resume_id
from jobwatch.store import Store, day, day_start

FIT = {"must_haves_met": 2, "must_haves_total": 3, "gaps": [], "summary": ""}


@pytest.fixture
def setup(tmp_path):
    (tmp_path / "cv.md").write_text("Python, LLMs, RAG")
    path = tmp_path / "jobwatch.yaml"
    path.write_text(yaml.safe_dump({"companies": ["greenhouse:initech"], "state": "state.db", "resume": "cv.md",
                                    "scoring": {"backend": "claude", "model": "claude-sonnet-5-5",
                                                "fallback": ["local"], "daily": 0}}))
    cfg = config.load(path)
    store = Store(cfg.state)
    store.sync("greenhouse", "initech", [Job(source="greenhouse", company="initech", id=str(i), title=title,
                                             url=f"https://example.com/{i}", company_name="Initech")
                                         for i, title in enumerate(["Staff Engineer", "AI Engineer", "Analyst"])])
    return cfg, store


def _score(store, cfg, i, score, by, at):
    with store.db:
        store.db.execute("INSERT INTO scores (key, resume, result, scored_at) VALUES (?, ?, ?, ?)",
                         (f"greenhouse:initech:{i}", resume_id(cfg.resume, cfg.prompts),
                          f'{{"score": {score}, "scored_by": "{by}"}}', at.astimezone(timezone.utc).isoformat()))


def test_scored_lists_the_days_scores_best_first_with_who_made_each(setup, capsys):
    cfg, store = setup
    now = datetime.now().astimezone()
    _score(store, cfg, 0, 91, "local:mlx-community/Qwen3.5-9B-MLX-4bit", now)
    _score(store, cfg, 1, 78, "claude:claude-sonnet-5-5", now)
    _score(store, cfg, 2, 95, "claude:claude-sonnet-5-5", now - timedelta(days=3))  # before today
    store.close()
    cli.main(["-c", str(cfg.path), "scored", "--min", "75"])
    out = capsys.readouterr().out
    assert out.index("Initech: Staff Engineer") < out.index("Initech: AI Engineer") and "Analyst" not in out
    assert "by Qwen3.5-9B-MLX-4bit (local)" in out
    assert "2 scores since" in out and "1 by claude-sonnet-5-5" in out and "1 by Qwen3.5-9B-MLX-4bit (local)" in out
    cli.main(["-c", str(cfg.path), "scored", "--since", "-7", "--by", "claude"])
    out = capsys.readouterr().out
    assert "Analyst" in out and "Staff Engineer" not in out
    cli.main(["-c", str(cfg.path), "scored", "--min", "99"])
    assert "No fit scores since" in capsys.readouterr().out


def test_activity_lists_the_oldest_first_with_failures_and_alerts_marked(setup, capsys):
    cfg, store = setup
    store.log("boards", "Checked 12 boards: nothing new for you", detail=["300 open jobs"], by="schedule")
    store.log("score", "Scored 40 jobs: 1 strong fit", by="background", notable=True)
    store.log("mail", "Couldn't read the mailbox\nlogin refused", ok=False, by="schedule")
    store.close()
    cli.main(["-c", str(cfg.path), "activity", "--details"])
    lines = capsys.readouterr().out.splitlines()
    assert [ln[13:].split()[0] for ln in lines if ln[:2].isdigit()] == ["boards", "score", "mail"]
    assert "* Scored 40 jobs" in lines[2] and "FAILED Couldn't read the mailbox  (schedule)" in lines[3]
    assert lines[1].strip() == "300 open jobs" and lines[4].strip() == "login refused"
    cli.main(["-c", str(cfg.path), "activity", "--notable"])
    out = capsys.readouterr().out
    assert "Scored 40 jobs" in out and "boards" not in out
    cli.main(["-c", str(cfg.path), "activity", "--kind", "mail,boards", "--since", "today"])
    assert "Scored" not in capsys.readouterr().out


def test_score_cost_prints_the_panel_and_each_recorded_run(setup, capsys):
    cfg, store = setup
    store.add_score_cost("claude", "claude-sonnet-5-5", True, 10, 1_000_000, 100_000)  # $3, half for a batch
    store.close()
    cli.main(["-c", str(cfg.path), "score", "--cost"])
    out = capsys.readouterr().out
    assert "Scoring with claude (claude-sonnet-5-5), then local" in out and "Daily cap: none" in out
    assert "$1.50 recorded for 10 scores" in out
    assert f"{date.today()}  claude-sonnet-5-5 (batch): 10 jobs, 1,000,000 in, 100,000 out" in out


def test_digest_role_lists_only_jobs_of_that_kind(setup, capsys):
    """`digest --role ai` is Today's Roles checkboxes from the command line, before the top-N cut."""
    import json
    cfg, store = setup
    store.close()
    cli.main(["-c", str(cfg.path), "digest", "--role", "ai", "--all", "--peek", "--format", "json"])
    assert [j["title"] for j in json.loads(capsys.readouterr().out)["jobs"]] == ["AI Engineer"]
    cli.main(["-c", str(cfg.path), "digest", "--role", "ai", "--role", "other", "--peek", "--limit", "5",
              "--format", "json"])
    assert sorted(j["title"] for j in json.loads(capsys.readouterr().out)["jobs"]) == ["AI Engineer", "Analyst"]


def test_day_reads_days_ago_and_a_days_start_is_local_midnight():
    today = date(2026, 9, 29)
    assert (day("-7", today), day("yesterday", today)) == ("2026-09-22", "2026-09-28")
    start = datetime.fromisoformat(day_start(today))
    assert start.tzinfo is not None and start.astimezone().replace(tzinfo=None) == datetime(2026, 9, 29)
