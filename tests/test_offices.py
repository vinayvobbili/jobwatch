"""Companies with an office near you: found from the jobs seen in your places, and their jobs elsewhere let through."""

from jobwatch import cli, config, offices
from jobwatch.filters import Filters, office_nearby, rejection
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.watch import warnings


def job(company: str, where: str, n: int = 1, **kw) -> Job:
    return Job(source="greenhouse", company=company.lower(), id=f"{company}-{n}", title="Security Engineer",
               url=f"https://example.com/{company}/{n}", company_name=company, locations=[where], **kw)


def test_a_job_elsewhere_passes_at_a_company_with_an_office_near_you():
    f = Filters(locations=["remote", "Boulder"], home_state="CO", nearby_offices=["Initech"])
    seattle = job("Initech", "Seattle, WA")
    remote_tx = job("Initech", "US, TX, Remote", remote=True)
    assert rejection(seattle, f) is None and rejection(remote_tx, f) is None
    assert office_nearby(seattle, f) == "Initech"
    assert rejection(job("Globex", "Seattle, WA"), f) == ("place", "location")  # no office near: still out
    assert office_nearby(job("Initech", "Boulder, CO"), f) is None  # in your places: nothing to ask
    assert rejection(job("Initech", "Seattle, WA", salary_min=90000, salary_max=100000),
                     Filters(locations=["Boulder"], nearby_offices=["Initech"], min_salary=150000))[0] == "pay"


def test_an_office_near_you_doesnt_let_in_a_job_in_another_country():
    f = Filters(locations=["remote", "Boulder"], home_state="CO", nearby_offices=["Initech"])
    for abroad in ("Sydney, Australia", "London, United Kingdom", "Bangalore, India"):
        assert rejection(job("Initech", abroad), f) == ("place", "location"), abroad
        assert office_nearby(job("Initech", abroad), f) is None
    both = Job(source="greenhouse", company="initech", id="i-9", title="Security Engineer", url="https://example.com/9",
               company_name="Initech", locations=["Toronto, Canada", "Austin, TX"])
    assert rejection(both, f) is None  # one of its places is in the US
    anywhere = Filters(locations=["remote", "Boulder"], remote_country="any", nearby_offices=["Initech"])
    assert rejection(job("Initech", "Sydney, Australia"), anywhere) is None


def test_the_queue_says_to_ask_about_the_office():
    f = Filters(locations=["remote", "Boulder"], nearby_offices=["Initech, Inc."])
    said = warnings(job("Initech", "Seattle, WA"), f)
    assert said == ["location: Seattle, WA; Initech, Inc. has an office near you: ask the recruiter about working "
                    "from it in the phone screen"]


def test_offices_are_found_from_jobs_posted_in_your_places_and_counted(tmp_path, capsys):
    path = tmp_path / "jobwatch.yaml"
    path.write_text("companies:\n  - greenhouse:acme\nfilters:\n  locations: [remote, Boulder]\n"
                    "  exclude_companies: [Hooli]\nstate: state.db\n")
    cfg = config.load(path)
    store = Store(tmp_path / "state.db")
    store.sync("greenhouse", "initech", [job("Initech", "Boulder, CO", 1), job("Initech", "Boulder, CO (Hybrid)", 2),
                                         job("Initech", "Seattle, WA", 3)])
    store.sync("greenhouse", "globex", [job("Globex", "Remote - Boulder, CO"), job("Globex", "Austin, TX", 2)])
    store.sync("greenhouse", "umbrella", [job("Umbrella", "Boulder, CO")])
    store.sync("greenhouse", "hooli", [job("Hooli", "Boulder, CO")])
    found = offices.found(cfg, store)
    # a remote job for people in Boulder isn't an office; a company left out isn't suggested
    assert [(r["name"], r["jobs"]) for r in found] == [("Initech", 2), ("Umbrella", 1)]
    assert found[0]["places"] == ["Boulder, CO", "Boulder, CO (Hybrid)"]
    cfg = offices.add(cfg, ["Initech", "initech", "Umbrella"])
    assert cfg.filters.nearby_offices == ["Initech", "Umbrella"]
    assert config.load(path).filters.exclude_companies == ["Hooli"]  # the rest of the filters kept
    assert offices.found(cfg, store) == []
    store.close()

    cli.main(["-c", str(path), "offices"])
    out = capsys.readouterr().out
    assert "Counted as having an office near you: Initech, Umbrella." in out
    assert "No other company has posted a job in Boulder." in out

    # Counted or not, `--jobs` says what a company has posted here, closed ones too
    cli.main(["-c", str(path), "offices", "--jobs", "Initech, Inc."])
    out = capsys.readouterr().out
    assert out.startswith("Initech, Inc.: 2 jobs posted in Boulder:") and "Seattle" not in out
    assert "(Boulder, CO (Hybrid))" in out and ", open · new · `greenhouse:initech:Initech-2`" in out
    cli.main(["-c", str(path), "offices", "--jobs", "Globex"])
    assert capsys.readouterr().out == "Globex: 0 jobs posted in Boulder.\n"
