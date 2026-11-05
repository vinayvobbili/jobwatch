"""`jobwatch backup`: a dated copy of what can't be fetched again, restored from in the last test."""

import sqlite3
import tarfile
from datetime import date

import pytest

from jobwatch import backup, config
from jobwatch.store import Store


@pytest.fixture
def cfg(watchlist):
    c = config.load(watchlist)
    s = Store(c.state)
    s.add("Globex", "Staff Engineer", status="applied", note="Referred by Dana")
    s.package(s.find("Globex")[0].key).attach("resume.txt", b"my resume")
    s.close()
    (c.state.parent / "extension-token").write_text("not-a-real-token")
    (c.state.parent / "lca.db").write_bytes(b"big download")
    return c


def names(archive):
    with tarfile.open(archive) as tar:
        return tar.getnames()


def test_an_archive_holds_the_database_packages_and_watchlist_but_no_secret(cfg, tmp_path):
    archive, dropped = backup.backup(cfg, tmp_path / "out", day=date(2030, 1, 15))
    assert archive.name == "jobwatch-2030-01-15.tar.gz" and dropped == []
    held = names(archive)
    assert "state.db" in held and "packages" in held and f"config/{cfg.path.name}" in held
    assert any(n.endswith("resume.txt") for n in held)
    assert not any("extension-token" in n or "lca.db" in n for n in held)


def test_only_the_newest_are_kept_and_nothing_else_in_the_folder_is_touched(cfg, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    mine = out / "notes.txt"
    mine.write_text("keep me")
    for d in (1, 2, 3):
        _, dropped = backup.backup(cfg, out, keep=2, day=date(2030, 1, d))
    assert [p.name for p in dropped] == ["jobwatch-2030-01-01.tar.gz"]
    assert [p.name for p in backup.archives(out)] == ["jobwatch-2030-01-03.tar.gz", "jobwatch-2030-01-02.tar.gz"]
    assert mine.read_text() == "keep me"


def test_a_second_run_the_same_day_replaces_that_days_archive(cfg, tmp_path):
    for _ in range(2):
        backup.backup(cfg, tmp_path, day=date(2030, 1, 15))
    assert [p.name for p in backup.archives(tmp_path)] == ["jobwatch-2030-01-15.tar.gz"]


def test_a_failed_run_leaves_the_last_good_archive_and_no_partial_file(cfg, tmp_path, monkeypatch):
    out = tmp_path / "out"
    good, _ = backup.backup(cfg, out, day=date(2030, 1, 15))
    before = good.read_bytes()

    def broken(source, to):
        raise backup.BackupError("failed its check")
    monkeypatch.setattr(backup, "_copy_db", broken)
    with pytest.raises(backup.BackupError):
        backup.backup(cfg, out, day=date(2030, 1, 15))
    assert good.read_bytes() == before
    assert [p.name for p in out.iterdir()] == [good.name]


def test_a_bad_copy_of_the_database_is_refused(tmp_path):
    source = tmp_path / "bad.db"
    source.write_bytes(b"this is not a database at all, not even close" * 100)
    with pytest.raises((backup.BackupError, sqlite3.DatabaseError)):
        backup._copy_db(source, tmp_path / "copy.db")


def test_keeping_none_is_refused(cfg, tmp_path):
    with pytest.raises(backup.BackupError, match="at least one"):
        backup.backup(cfg, tmp_path, keep=0)


def test_no_database_says_so(cfg, tmp_path):
    cfg.state.unlink()
    with pytest.raises(backup.BackupError, match="nothing to back up"):
        backup.backup(cfg, tmp_path)


def test_the_folder_is_a_synced_drive_when_there_is_one(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(backup.socket, "gethostname", lambda: "studio.local")
    assert backup.default_dest() == tmp_path / "jobwatch-backups"
    (tmp_path / "Google Drive" / "My Drive").mkdir(parents=True)
    assert backup.default_dest() == tmp_path / "Google Drive" / "My Drive" / "Backups" / "jobwatch" / "studio"


def test_the_daily_job_runs_this_jobwatch_with_the_same_folder(tmp_path):
    job = backup.definition(tmp_path / "w.yaml", tmp_path / "out", 12)
    assert job["StartCalendarInterval"] == {"Hour": backup.HOUR, "Minute": backup.MINUTE}
    args = job["ProgramArguments"]
    assert args[args.index("--dest") + 1] == str(tmp_path / "out") and args[args.index("--keep") + 1] == "12"
    assert "backup" in args and str(tmp_path / "w.yaml") in args


def test_a_restored_archive_has_every_job_and_package(cfg, tmp_path):
    archive, _ = backup.backup(cfg, tmp_path / "out")
    home = tmp_path / "restored"
    with tarfile.open(archive) as tar:
        tar.extractall(home, filter="data")
    s = Store(home / "state.db")
    job, rec = s.find("Globex")
    assert (job.title, rec["note"]) == ("Staff Engineer", "Referred by Dana")
    assert any(p.name == "resume.txt" for p in s.package(job.key).dir.rglob("*"))
    s.close()


def test_the_command_says_where_it_wrote(watchlist, cfg, tmp_path, capsys):
    from jobwatch.cli import main
    assert main(["-c", str(watchlist), "backup", "--dest", str(tmp_path / "out")]) in (0, None)
    out = capsys.readouterr().out
    assert "jobwatch-" in out and str(tmp_path / "out") in out
    assert main(["-c", str(watchlist), "backup", "--list"]) in (0, None)
    assert "state.db" in capsys.readouterr().out
