"""`jobwatch resolve`: rows whose client isn't named, matched across companies to a named twin (same title, pay range
and remote setting). A dry run by default; --apply skips the unnamed copy and touches nothing else."""

import hashlib

import pytest

from jobwatch import cli, config, resolve
from jobwatch.models import Job
from jobwatch.store import Store

PAY = dict(salary_min=150_000, salary_max=180_000, currency="USD")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "state.db")
    yield s
    s.close()


def named(store, company="Initech", title="Staff Security Engineer", id_="1", where="Remote - US", **kw):
    """A job on a company's own board (greenhouse), as a fetch records it."""
    job = Job(source="greenhouse", company=company.lower(), id=id_, title=title, url=f"https://example.com/{id_}",
              company_name=company, locations=[where] if isinstance(where, str) else where, **{**PAY, **kw})
    store.sync("greenhouse", company.lower(), [*store.board_jobs("greenhouse", company.lower()).values(), job])
    return job


def unnamed(store, title="Staff Security Engineer", company="Ladders", where="United States (Remote)", pay=PAY,
            status="new", note=None):
    """A row from a source that doesn't name its client, as an alert or a list import adds it."""
    job = store.add(company, title, url=f"https://example.com/{company}/{title}".replace(" ", "-"), status=status,
                    location=where, note=note, description="For our client, we are seeking a security engineer.")
    job.set_pay(pay["salary_min"], pay["salary_max"], "USD") if pay else None
    store.update(job)
    return job


def test_a_pair_matches_across_companies_on_title_pay_and_remote_setting(store):
    twin, copy = named(store), unnamed(store)
    found = resolve.twins(store)
    assert [(t.unnamed.key, t.named.key) for t in found] == [(copy.key, twin.key)]
    text = resolve.text(found, applied=False)
    assert "Ladders: Staff Security Engineer" in text and "= Initech (new): Staff Security Engineer" in text
    assert "Nothing was changed" in text


def test_pay_rounded_to_the_thousand_is_the_same_band(store):
    twin = named(store, salary_min=150_200, salary_max=179_900)  # the alert says 150,000-180,000
    copy = unnamed(store)
    assert [(t.unnamed.key, t.named.key) for t in resolve.twins(store)] == [(copy.key, twin.key)]
    assert resolve.same_band((150_000, 180_000), (150_000, 181_000)) and not resolve.same_band(
        (150_000, 180_000), (150_000, 190_000))
    assert not resolve.same_band(None, (150_000, 180_000))


def test_explain_says_how_the_nearest_same_title_jobs_differ(store, tmp_path, capsys):
    named(store, "Hooli", salary_min=140_000, salary_max=180_000, where="Austin, TX")
    named(store, "Globex", id_="2", salary_min=150_000, salary_max=170_000)
    copy = unnamed(store)
    assert resolve.twins(store) == []
    ((job, lines),) = resolve.near_misses(store, [])
    assert job.key == copy.key
    assert lines == ["Globex (new): pay $150,000–$170,000, not $150,000–$180,000",
                     "Hooli (new): pay $140,000–$180,000, not $150,000–$180,000, on-site, not remote"]
    path = tmp_path / "jobwatch.yaml"
    path.write_text(f"companies: [greenhouse:acme]\nstate: {store.path}\n")
    cli.main(["-c", str(path), "resolve", "--explain"])
    out = capsys.readouterr().out
    assert f"no match: Staff Security Engineer  $150K–$180K  `{copy.key}`" in out
    assert "  Hooli (new): pay $140,000–$180,000" in out


def test_a_twin_whose_board_gives_no_pay_is_read_from_its_posting_text(store):
    twin = named(store, salary_min=None, salary_max=None,
                 description="About us.\nThe base pay range is $150,000 - $180,000 per year.")
    copy = unnamed(store)
    assert [(t.unnamed.key, t.named.key) for t in resolve.twins(store)] == [(copy.key, twin.key)]
    other = named(store, "Hooli", id_="2", salary_min=None, salary_max=None,
                  description="Pay is $40 - $60 per hour.")
    assert resolve.pay_of(other) is None  # an hourly rate is no yearly band
    assert [t.named.key for t in resolve.twins(store)] == [twin.key]


def test_a_country_beside_remote_is_still_remote(store):
    twin = named(store, where=["United States", "Remote"])
    copy = unnamed(store)
    assert [(t.unnamed.key, t.named.key) for t in resolve.twins(store)] == [(copy.key, twin.key)]


@pytest.mark.parametrize("twin", [
    dict(title="Security Engineer"),               # another title
    dict(title="Senior Staff Security Engineer"),  # another seniority
    dict(salary_min=160_000),                      # another pay band
    dict(salary_max=200_000),
    dict(where="Austin, TX"),                      # on-site, not remote
])
def test_a_different_title_pay_or_remote_setting_is_another_opening(store, twin):
    named(store, **twin)
    unnamed(store)
    assert resolve.twins(store) == []
    assert "No unnamed-client row has a named twin" in resolve.text([], applied=False)


def test_a_row_without_pay_or_place_proves_nothing(store):
    named(store)
    unnamed(store, pay=None)
    unnamed(store, title="Staff Security Engineer ", where="")
    assert resolve.twins(store) == []


def test_the_best_twin_is_the_one_furthest_along(store):
    named(store, "Globex", id_="1")
    applied = named(store, "Hooli", id_="2")
    store.set_status([applied.key], "applied")
    unnamed(store)
    (t,) = resolve.twins(store)
    assert t.named.key == applied.key and t.named_record["status"] == "applied"


def test_a_closed_twin_and_another_unnamed_row_are_no_twin(store):
    gone = named(store)
    store.set_closed(gone.key, True)  # the board took it down
    assert store.find(gone.key)[1]["closed"]
    unnamed(store)
    unnamed(store, company="Globex Staffing")  # one agency's row is not another's twin
    assert resolve.twins(store) == []


def test_only_rows_today_could_list_are_looked_at(store):
    named(store)
    queued = unnamed(store, status="queued")
    applied = unnamed(store, title="Staff Security Engineer II", status="applied")
    skipped = unnamed(store, title="Staff Security Engineer III", status="skipped")
    for job in (queued, applied, skipped):
        named(store, title=job.title, id_=job.title)
    assert resolve.twins(store) == []


def test_apply_skips_the_unnamed_copy_and_leaves_everything_else(store):
    twin = named(store)
    copy = unnamed(store, note="From a LinkedIn alert")
    queued = unnamed(store, title="Principal Security Engineer", status="queued")
    named(store, title="Principal Security Engineer", id_="2")
    before = {k: store.find(k)[1] for k in (twin.key, queued.key)}
    found = resolve.twins(store)
    assert resolve.apply(store, found) == 1
    rec = store.find(copy.key)[1]
    assert rec["status"] == "skipped"
    assert rec["note"].startswith("From a LinkedIn alert\n")
    assert f"Initech's “Staff Security Engineer” ({twin.key})" in rec["note"]
    assert {k: store.find(k)[1] for k in before} == before  # the twin and the queued job are as they were
    assert resolve.twins(store) == []  # nothing left to match
    assert "marked skipped" in resolve.text(found, applied=True)


def test_naming_the_client_makes_the_row_listable_again(store):
    from jobwatch.filters import Filters, rejection
    copy = unnamed(store)
    assert rejection(store.find(copy.key)[0], Filters())[0] == "client"
    job = resolve.name_client(store, copy.key, "Umbrella")
    assert job.display_company == "Umbrella"
    assert rejection(store.find(copy.key)[0], Filters()) is None
    with pytest.raises(ValueError, match="isn't an unnamed-client row"):
        resolve.name_client(store, copy.key, "Umbrella")
    with pytest.raises(ValueError, match="which company"):
        resolve.name_client(store, unnamed(store, title="Other").key, "  ")


def test_the_filter_pass_hides_the_row_from_today_but_the_company_page_lists_it(store, tmp_path):
    from jobwatch import company, jobpass, watch
    cfg_path = tmp_path / "jobwatch.yaml"
    cfg_path.write_text(f"companies: [greenhouse:acme]\nstate: {store.path}\n")
    cfg = config.load(cfg_path)
    copy = unnamed(store)
    jobpass.forget()
    assert copy.key not in [e.job.key for e in watch.build_digest(cfg, store, include_seen=True, score_top=0).entries]
    assert watch.hidden(cfg, store)["by"] == {"client": 1}
    assert watch.hidden(cfg, store, "client")["jobs"][0]["why"] == "client not named"
    folded = company.view(cfg, store, "Ladders", every=False)
    assert folded["jobs"] == [] and folded["left_out_by"] == {"client": 1}
    assert [j["key"] for j in company.view(cfg, store, "Ladders", every=True)["jobs"]] == [copy.key]
    assert [r["key"] for r in company.search(store, "Ladders")] == ["ladders"]


def test_the_command_is_a_dry_run_unless_asked(tmp_path, capsys):
    path = tmp_path / "jobwatch.yaml"
    path.write_text(f"companies: [greenhouse:acme]\nstate: {tmp_path / 'state.db'}\n")
    s = Store(tmp_path / "state.db")
    twin, copy = named(s), unnamed(s)
    s.close()
    digest = lambda: hashlib.sha256((tmp_path / "state.db").read_bytes()).hexdigest()  # noqa: E731
    before = digest()
    cli.main(["-c", str(path), "resolve"])
    out = capsys.readouterr().out
    assert f"`{copy.key}`" in out and f"`{twin.key}`" in out and "Nothing was changed" in out
    cli.main(["-c", str(path), "resolve", "--dry-run"])
    capsys.readouterr()
    assert digest() == before
    cli.main(["-c", str(path), "resolve", "--apply"])
    assert "1 unnamed-client row(s) match a named twin. Each is marked skipped" in capsys.readouterr().out
    s = Store(tmp_path / "state.db")
    assert s.find(copy.key)[1]["status"] == "skipped" and s.find(twin.key)[1]["status"] == "new"
    s.close()
    cli.main(["-c", str(path), "resolve", "--name", copy.key, "Umbrella"])
    assert f"{copy.key}: client named Umbrella" in capsys.readouterr().out
