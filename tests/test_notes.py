"""`mark --note` replaces the whole note: it keeps the one replaced, `notes --undo` brings it back, and a backup's
notes can be read and written back in front of the ones there now."""

from datetime import date

import pytest

from jobwatch import backup, cli, config
from jobwatch.store import Store

LONG = "2026-10-01: applied via referral from Dana. 2026-10-08: recruiter screen done. 2026-10-15: onsite set."


def run(capsys, *argv):
    cli.main(list(argv))
    return capsys.readouterr()


@pytest.fixture
def cfg(watchlist):
    c = config.load(watchlist)
    s = Store(c.state)
    s.add("Globex", "Staff Engineer", status="applied", note=LONG)
    s.add("Umbrella", "Field Engineer", status="screening", note="Referred by Ana")
    s.add("Initech", "Platform Engineer", status="queued")
    s.close()
    return c


def store_of(cfg):
    return Store(cfg.state)


def note_of(cfg, key):
    s = store_of(cfg)
    try:
        return s.find(key)[1].get("note")
    finally:
        s.close()


def test_replacing_a_note_keeps_it_and_says_so(cfg, watchlist, capsys):
    c = ("-c", str(watchlist))
    out = run(capsys, *c, "mark", "staff-engineer", "--note", "waiting").out
    assert f"replaced a {len(LONG)}-character note; bring it back with `jobwatch notes " in out
    assert "`jobwatch notes manual:globex:staff-engineer --undo`" in out
    assert note_of(cfg, "staff-engineer") == "waiting"
    shown = run(capsys, *c, "notes", "staff-engineer").out
    assert "manual:globex:staff-engineer: waiting" in shown and LONG in shown


def test_the_status_form_keeps_the_replaced_note_too(cfg, watchlist, capsys):
    c = ("-c", str(watchlist))
    run(capsys, *c, "mark", "interviewing", "staff-engineer", "--note", "waiting")
    out = run(capsys, *c, "notes", "staff-engineer", "--undo").out
    assert f"brought back a {len(LONG)}-character note, replacing a 7-character one" in out
    assert note_of(cfg, "staff-engineer") == LONG


def test_adding_a_note_or_setting_the_first_one_keeps_nothing(cfg, watchlist, capsys):
    c = ("-c", str(watchlist))
    assert "replaced" not in run(capsys, *c, "mark", "staff-engineer", "--add-note", "call Friday").out
    assert "replaced" not in run(capsys, *c, "mark", "platform-engineer", "--note", "first note").out
    s = store_of(cfg)
    try:
        assert s.note_history("manual:globex:staff-engineer") == []
        assert s.note_history("manual:initech:platform-engineer") == []
    finally:
        s.close()
    assert note_of(cfg, "staff-engineer").startswith(LONG + " 20") and note_of(cfg, "platform-engineer") == "first note"


def test_undo_twice_goes_back_and_with_nothing_replaced_it_says_so(cfg, watchlist, capsys):
    c = ("-c", str(watchlist))
    run(capsys, *c, "mark", "staff-engineer", "--note", "waiting")
    run(capsys, *c, "notes", "staff-engineer", "--undo")
    assert note_of(cfg, "staff-engineer") == LONG
    run(capsys, *c, "notes", "staff-engineer", "--undo")
    assert note_of(cfg, "staff-engineer") == "waiting"
    with pytest.raises(SystemExit, match="no replaced note"):
        cli.main([*c, "notes", "platform-engineer", "--undo"])


def test_the_mcp_tool_refuses_to_replace_a_note_unless_told_to(cfg, watchlist, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(watchlist))
    with pytest.raises(Exception, match=f"has a {len(LONG)}-character note.*add_note"):
        mcp.mark_job("staff-engineer", "interviewing", note="waiting")
    assert note_of(cfg, "staff-engineer") == LONG
    s = store_of(cfg)
    try:
        assert s.find("staff-engineer")[1]["status"] == "applied"  # nothing at all changed
    finally:
        s.close()
    assert mcp.mark_job("staff-engineer", add_note="onsite Friday").endswith(": applied")
    assert note_of(cfg, "staff-engineer").startswith(LONG + " 20")
    said = mcp.mark_job("staff-engineer", note="rewritten", replace_note=True)
    assert "Replaced a" in said and "notes manual:globex:staff-engineer --undo" in said
    assert note_of(cfg, "staff-engineer") == "rewritten"
    assert mcp.mark_job("platform-engineer", note="first note").endswith(": queued")  # no note to lose


def test_the_mcp_tool_and_cli_say_what_note_does(capsys):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    doc = mcp.mark_job.__doc__
    assert "always use it for news" in doc and "refused" in doc
    with pytest.raises(SystemExit):
        cli.main(["mark", "--help"])
    assert "REPLACES" in capsys.readouterr().out


@pytest.fixture
def archive(cfg, tmp_path):
    """A backup made while the notes were whole, then the notes replaced."""
    made, _ = backup.backup(cfg, tmp_path / "backups", day=date(2030, 1, 15))
    s = store_of(cfg)
    s.track("manual:globex:staff-engineer", note="waiting")
    s.add_note("manual:umbrella:field-engineer", "recruiter replied")
    s.close()
    return made


def test_notes_are_read_from_a_backup_without_touching_the_database(cfg, archive, watchlist, capsys):
    c = ("-c", str(watchlist))
    before = cfg.state.read_bytes()
    out = run(capsys, *c, "notes", "staff-engineer", "platform-engineer", "--from-backup", str(archive)).out
    assert f"manual:globex:staff-engineer: archive jobwatch-2030-01-15.tar.gz: {len(LONG)} characters; now 7; restore" \
        in out
    assert f"  archived: {LONG}\n  now: waiting" in out
    assert "manual:initech:platform-engineer: archive jobwatch-2030-01-15.tar.gz: 0 characters; now 0; " \
        "no archived note" in out
    assert cfg.state.read_bytes() == before and note_of(cfg, "staff-engineer") == "waiting"


def test_a_backup_can_be_named_by_its_day(cfg, archive, watchlist, capsys):
    c = ("-c", str(watchlist))
    out = run(capsys, *c, "notes", "staff-engineer", "--from-backup", "2030-01-15", "--dest", str(archive.parent)).out
    assert f"{len(LONG)} characters" in out
    with pytest.raises(SystemExit, match="no backup for 2030-01-16"):
        cli.main([*c, "notes", "staff-engineer", "--from-backup", "2030-01-16", "--dest", str(archive.parent)])
    with pytest.raises(SystemExit, match="neither a backup file nor a day"):
        cli.main([*c, "notes", "staff-engineer", "--from-backup", "yesterday"])


def test_restore_dry_run_changes_nothing_then_restore_puts_the_old_note_in_front(cfg, archive, watchlist, capsys):
    c = ("-c", str(watchlist))
    keys = ("staff-engineer", "field-engineer", "platform-engineer")
    out = run(capsys, *c, "notes", *keys, "--from-backup", str(archive), "--restore", "--dry-run").out
    assert "Dry run: nothing changed." in out and f"(would become {len(LONG) + 1 + 7})" in out
    assert note_of(cfg, "staff-engineer") == "waiting"
    out = run(capsys, *c, "notes", *keys, "--from-backup", str(archive), "--restore").out
    assert f"manual:globex:staff-engineer: restored, 7 -> {len(LONG) + 1 + 7} characters" in out
    assert note_of(cfg, "staff-engineer") == f"{LONG} waiting"
    # Umbrella's archived note is still inside the note now (a line was added since): left as it is
    assert "manual:umbrella:field-engineer: archive" in out and "already in the note" in out
    assert note_of(cfg, "field-engineer").startswith("Referred by Ana 20")
    assert note_of(cfg, "platform-engineer") is None  # no archived note: nothing written
    run(capsys, *c, "notes", "staff-engineer", "--undo")  # and the restore itself is reversible
    assert note_of(cfg, "staff-engineer") == "waiting"


def test_restoring_twice_does_not_stack_the_note(cfg, archive, watchlist, capsys):
    c = ("-c", str(watchlist))
    for _ in range(2):
        run(capsys, *c, "notes", "staff-engineer", "--from-backup", str(archive), "--restore")
    assert note_of(cfg, "staff-engineer") == f"{LONG} waiting"


def test_restore_needs_a_backup_and_undo_does_not_mix_with_one(cfg, archive, watchlist):
    c = ("-c", str(watchlist))
    with pytest.raises(SystemExit, match="--restore needs --from-backup"):
        cli.main([*c, "notes", "staff-engineer", "--restore"])
    with pytest.raises(SystemExit, match="not both"):
        cli.main([*c, "notes", "staff-engineer", "--undo", "--from-backup", str(archive)])
