"""`find --try-variants`: a company's name tried in its likely variants until one finds a board."""

import pytest

from jobwatch import cli, config, sources, variants
from jobwatch.models import Job


def run(capsys, *argv):
    cli.main(list(argv))
    return capsys.readouterr()


def roles(board, *titles):
    return [Job(source="greenhouse", company=board, id=str(i), title=t, url=f"https://jobs.example/{board}/{i}",
                company_name=board.title()) for i, t in enumerate(titles, 1)]


@pytest.mark.parametrize("name, tried", [
    ("Initech Holdings, Inc.", ["Initech Holdings, Inc.", "Initech Holdings", "Initech"]),
    ("Globex Corporation", ["Globex Corporation", "Globex"]),
    ("Initech", ["Initech"]),
    ("InitechSystems", ["InitechSystems", "Initech Systems", "Initech"]),
    ("The Umbrella Group Ltd", ["The Umbrella Group Ltd", "The Umbrella Group", "The Umbrella", "Umbrella"]),
    ("Pied Piper LLC", ["Pied Piper LLC", "Pied Piper", "Pied"]),
    ("Go Inc", ["Go Inc", "Go"]),
    ("Initech-Systems", ["Initech-Systems", "Initech"]),  # the hyphenated and joined board names are probe's own
])
def test_the_variants_of_a_name(name, tried):
    assert variants.names(name) == tried


@pytest.mark.parametrize("name", ["https://jobs.lever.co/initech", "greenhouse:initech", "initech.com",
                                  "https://careers.initech.example/jobs"])
def test_a_link_an_entry_or_a_domain_is_looked_up_as_it_is(name):
    assert variants.names(name) == [name]


def test_probe_stops_at_the_first_variant_that_finds_a_board(monkeypatch):
    asked = []

    def fake(name, limited=None, untested=None):
        asked.append(name)
        return [("greenhouse", "initech", roles("initech", "Platform Engineer"))] if name == "Initech Holdings" else []

    monkeypatch.setattr(sources, "probe", fake)
    found_as, hits, tried = variants.probe("Initech Holdings, Inc.")
    assert (found_as, tried) == ("Initech Holdings", ["Initech Holdings, Inc."]) and hits[0][1] == "initech"
    assert asked == ["Initech Holdings, Inc.", "Initech Holdings"]  # "Initech" wasn't asked


def test_probe_with_no_board_anywhere_reports_every_variant_tried(monkeypatch):
    monkeypatch.setattr(sources, "probe", lambda name, limited=None, untested=None: [])
    assert variants.probe("Initech Holdings, Inc.") == (
        "Initech Holdings, Inc.", [], ["Initech Holdings, Inc.", "Initech Holdings", "Initech"])


def test_probe_prefers_a_board_with_roles_to_one_without(monkeypatch):
    answers = {"Globex Corp": [("lever", "globex-corp", [])], "Globex": [("lever", "globex", roles("globex", "SRE"))]}
    monkeypatch.setattr(sources, "probe", lambda name, limited=None, untested=None: answers.get(name, []))
    assert variants.probe("Globex Corp")[:2] == ("Globex", answers["Globex"])
    answers["Globex"] = []
    assert variants.probe("Globex Corp") == ("Globex Corp", answers["Globex Corp"], ["Globex"])


def test_find_try_variants_says_which_variant_found_the_board(monkeypatch, capsys):
    def fake(name, limited=None, untested=None):
        return [("greenhouse", "initech", roles("initech", "Platform Engineer", "Data Engineer"))] \
            if name == "Initech" else []

    monkeypatch.setattr(cli.sources, "probe", fake)
    out = run(capsys, "find", "--try-variants", "Initech Holdings, Inc.").out
    assert out.startswith("Initech Holdings, Inc.: found as 'Initech' (also tried 'Initech Holdings, Inc.', "
                          "'Initech Holdings')\n")
    assert "Initech: greenhouse:initech  (2 open roles, Initech)  https://job-boards.greenhouse.io/initech" in out
    assert "e.g. Platform Engineer" in out
    # without the flag the name is looked up as given, and nothing else
    assert "no Greenhouse" in run(capsys, "find", "Initech Holdings, Inc.").out


def test_find_try_variants_with_no_board_lists_the_names_tried(monkeypatch, capsys):
    monkeypatch.setattr(cli.sources, "probe", lambda name, limited=None, untested=None: [])
    out = run(capsys, "find", "--try-variants", "Initech Holdings, Inc.").out
    assert out.startswith("Initech Holdings, Inc.: tried the names 'Initech Holdings, Inc.', 'Initech Holdings', "
                          "'Initech'\nInitech Holdings, Inc.: no Greenhouse")


def test_find_try_variants_add_watches_the_board_found(monkeypatch, watchlist, capsys):
    monkeypatch.setattr(cli.sources, "probe", lambda name, limited=None, untested=None:
                        [("greenhouse", "initech", roles("initech", "Platform Engineer"))] if name == "Initech" else [])
    out = run(capsys, "-c", str(watchlist), "find", "--try-variants", "Initech Holdings, Inc.", "--add").out
    assert "    Watching greenhouse:initech as Initech Holdings, Inc. (" in out
    assert any(b.entry == "greenhouse:initech" for b in config.load(watchlist).boards)


def test_the_mcp_find_board_takes_try_variants(monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setattr(mcp, "_changed_since_start", lambda: None)
    monkeypatch.setattr(sources, "probe", lambda name, limited=None, untested=None:
                        [("greenhouse", "initech", roles("initech", "Platform Engineer"))] if name == "Initech" else [])
    [hit] = mcp.find_board("Initech Holdings, Inc.", try_variants=True)
    assert hit["entry"] == "greenhouse:initech" and hit["found_as"] == "Initech"
    assert mcp.find_board("Initech Holdings, Inc.") == []
