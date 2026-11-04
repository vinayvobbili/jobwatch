"""Jobs kept under a source this version doesn't have (a board that was retired, or one from a newer version) are
still listed, and never crash a command."""

from pathlib import Path

import pytest

from jobwatch import cli, sources
from jobwatch.models import Job
from jobwatch.store import Store

from .conftest import FakeWeb

KEY = "retiredboard:retiredboard:R-584380"


@pytest.fixture
def kept(watchlist):
    """The test watchlist's store, with a queued job and an applied one from an unknown source."""
    store = Store(watchlist.parent / "state.db")
    for jid, title, status in (("R-584380", "Senior Platform Engineer", "queued"),
                               ("R-584381", "Staff Platform Engineer", "applied")):
        job = Job(source="retiredboard", company="retiredboard", id=jid, title=title, company_name="Initech",
                  url=f"https://careers.example.com/en/jobs/{jid.lower()}/", description="Build the widget platform.")
        store.keep(job)
        store.set_status([job.key], status)
    return store


def run(capsys, watchlist, *argv):
    cli.main(["-c", str(watchlist), *argv])
    return capsys.readouterr().out


@pytest.mark.parametrize("argv, shows", [
    (["queue"], "Senior Platform Engineer"),
    (["company", "Initech"], "Senior Platform Engineer"),
    (["applications"], "Staff Platform Engineer"),
    (["list", "--status", "queued"], "Senior Platform Engineer"),
    (["show", KEY], "Senior Platform Engineer"),
])
def test_commands_list_a_job_from_an_unknown_source(kept, watchlist, capsys, argv, shows):
    assert shows in run(capsys, watchlist, *argv)


def test_check_reads_the_link_of_a_job_from_an_unknown_source(kept, watchlist, capsys, monkeypatch):
    # no board to ask, so the job's own page says: still posted, or gone (HTTP 404)
    page = (Path(__file__).parent / "fixtures" / "sitemap_job.html").read_text(encoding="utf-8")
    monkeypatch.setattr(sources, "get_text", FakeWeb({"https://careers.example.com/en/jobs/r-584380/": page}))
    run(capsys, watchlist, "check")
    assert not kept.find(KEY)[1].get("closed")
    assert kept.find("R-584381")[1].get("closed")
