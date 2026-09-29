import pytest

from jobwatch import cli, config, report, watch
from jobwatch.contacts import Contacts, company_key
from jobwatch.store import Store

# LinkedIn's export starts with notes before the header.
CONNECTIONS = """﻿Notes:
"When exporting your connection data, you may notice that some of the email addresses are missing."

First Name,Last Name,URL,Email Address,Company,Position,Connected On
Ana,Li,https://www.linkedin.com/in/example-ana,,"Initech, Inc.",Staff Engineer,01 Jan 2024
Bo,Chen,https://www.linkedin.com/in/example-bo,,Initech,Recruiter,02 Jan 2024
Cy,Diaz,https://www.linkedin.com/in/example-cy,,Globex Corporation,Engineering Manager,03 Jan 2024
Dee,Park,https://www.linkedin.com/in/example-dee,,Umbrella,Analyst,04 Jan 2024
,,,,,,
"""


@pytest.fixture
def connections(tmp_path):
    path = tmp_path / "Connections.csv"
    path.write_text(CONNECTIONS, encoding="utf-8")
    return path


@pytest.mark.parametrize("a, b", [("Initech, Inc.", "initech"), ("Scale AI", "scale"), ("The Acme Company", "acme"),
                                  ("Globex Corporation", "globex"), ("Anthropic PBC", "Anthropic")])
def test_company_names_match_across_spellings(a, b):
    assert company_key(a) == company_key(b)


def test_company_key_keeps_a_name_made_only_of_filler():
    assert company_key("AI Labs") == "ai labs"


def test_load_skips_the_notes_and_blank_rows(connections):
    contacts = Contacts.load(connections)
    assert [p["name"] for p in contacts.at("Initech")] == ["Ana Li", "Bo Chen"]
    assert contacts.at("initech", "Initech Inc")[0]["position"] == "Staff Engineer"
    assert contacts.at("Nobody") == [] and contacts.at("") == []


def test_not_a_connections_file(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError, match=r"Connections\.csv"):
        Contacts.load(p)


def test_people_line():
    people = [{"name": n, "position": "Engineer" if n == "A" else ""} for n in "ABCDE"]
    assert report.people(people) == "A (Engineer), B, C and 2 more"


def add_connections(watchlist, path):
    watchlist.write_text(watchlist.read_text() + f"connections: {path}\n")


def test_digest_shows_who_you_know(web, watchlist, connections, capsys):
    add_connections(watchlist, connections)
    cli.main(["-c", str(watchlist), "run"])
    out = capsys.readouterr().out
    assert "You know: Ana Li (Staff Engineer), Bo Chen (Recruiter)" in out
    assert "Cy Diaz (Engineering Manager)" in out  # lever:globex matched by board slug


def test_missing_connections_file_only_warns(web, watchlist, tmp_path, capsys):
    add_connections(watchlist, tmp_path / "missing.csv")
    cli.main(["-c", str(watchlist), "run"])
    out = capsys.readouterr()
    assert "connections skipped" in out.err and "3 matching job(s)." in out.out


def test_queue_add_list_and_apply(web, watchlist, connections, capsys):
    add_connections(watchlist, connections)
    c = ["-c", str(watchlist)]
    cli.main([*c, "fetch"])
    assert capsys.readouterr().out.startswith("Checked")
    cli.main([*c, "queue"])
    assert "queue is empty" in capsys.readouterr().out
    cli.main([*c, "queue", "c1", "--note", "ask Ana for a referral"])
    cli.main([*c, "queue", "aaaa-1111"])
    capsys.readouterr()
    cli.main([*c, "queue"])
    out = capsys.readouterr().out
    assert out.startswith("# Apply queue (2)")
    assert out.index("Staff AI Engineer") < out.index("Machine Learning Engineer")  # first queued first
    assert "Note: ask Ana for a referral" in out and "You know: Ana Li" in out
    # Queued jobs stay out of the digest; applying takes them off the queue.
    cli.main([*c, "digest", "--all"])
    assert "Staff AI Engineer" not in capsys.readouterr().out
    cli.main([*c, "mark", "applied", "c1"])
    cli.main([*c, "queue"])
    assert "Apply queue (1)" in capsys.readouterr().out


def test_queue_shows_closed_postings(web, watchlist):
    cfg = config.load(watchlist)
    store = Store(cfg.state)
    watch.fetch_all(cfg, store)
    store.set_status(["ashby:initech:c1"], "queued")
    web.responses["https://api.ashbyhq.com/posting-api/job-board/initech?includeCompensation=true"] = {"jobs": []}
    watch.fetch_all(cfg, store)
    assert "**Closed**" in report.queue_markdown(watch.queue(cfg, store))
    store.close()


def test_show_lists_contacts(web, watchlist, connections, capsys):
    add_connections(watchlist, connections)
    cli.main(["-c", str(watchlist), "fetch"])
    cli.main(["-c", str(watchlist), "show", "c1"])
    assert "You know: Ana Li (Staff Engineer), Bo Chen (Recruiter)" in capsys.readouterr().out
