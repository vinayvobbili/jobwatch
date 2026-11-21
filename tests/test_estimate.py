"""Est. pay: a guess at the base for a posting that lists no pay, from a recruiter's figures, similar jobs', H-1B
filings or Levels.fyi, always marked as an estimate with its basis. Nothing here asks the network."""

import pytest

from jobwatch import cli, comps, config, estimate, lca, levels, report, watch
from jobwatch.models import Job
from jobwatch.store import Store
from jobwatch.web import App


def filings(median=170000, where="CO", count=12):
    return lca.Estimate(company="Initech", title="Platform Engineer", where=where, count=count, median=median,
                        p25=median - 10000, p75=median + 15000, levels={}, examples=[], why=[])


def job(title="Platform Engineer", **more):
    return Job(source="manual", company="initech", id=title.lower().replace(" ", "-"), title=title, url="",
               company_name="Initech", **more)


@pytest.fixture
def cfg(tmp_path):
    path = tmp_path / "jobwatch.yaml"
    path.write_text("companies: []\nstate: state.db\n")
    return config.load(path)


@pytest.fixture
def store(cfg):
    s = Store(cfg.state)
    yield s
    s.close()


def test_a_posted_range_needs_no_estimate():
    assert estimate.estimate(job(salary_min=150000, salary_max=180000), comp={"base": "130K"}) is None


def test_a_recruiters_figure_for_this_job_comes_first_then_the_offer_then_the_note():
    got = estimate.estimate(job(), comp={"base": "165-195K", "offered": "180K", "note": "170K"}, filings=filings())
    assert (got.low, got.mid, got.high, got.basis) == (165000, 180000, 195000, "recruiter")
    assert got.label() == "Est. $165K–$195K base" and got.to_dict()["estimate"] is True
    assert estimate.estimate(job(), comp={"offered": "180K"}).basis == "recruiter"
    note = estimate.estimate(job(), comp={"note": "195K most likely their max"})
    assert note.mid == 195000 and note.label() == "Est. ~$195K base" and "note" in note.detail


def test_similar_jobs_bases_give_the_lowest_middle_and_highest():
    got = estimate.estimate(job(), similar=[(150000, 170000), (160000, 190000), (140000, 160000)], filings=filings())
    assert (got.low, got.mid, got.high, got.basis, got.figures) == (140000, 160000, 190000, "similar", 3)
    assert "3 similar jobs" in got.detail


def test_h1b_filings_come_next_and_say_whose_they_are():
    own = estimate.estimate(job(), filings=filings())
    assert (own.low, own.mid, own.high, own.basis) == (160000, 170000, 185000, "lca")
    assert "this employer's filings" in own.detail and "a base, not total pay" in own.detail
    market = estimate.estimate(job(), filings=filings(where=f"CO, {lca.MARKET}"))
    assert "other employers' filings in your state for similar work" in market.detail


def test_levels_is_the_last_resort_and_only_an_estimate_counts():
    got = levels.Estimate(company="Initech", family="Software Engineer", level="L4", total=210000, base=175000,
                          ask=180000, where="US-wide", url="https://example.com", why=[])
    assert estimate.estimate(job(), result=got).basis == "levels"
    assert estimate.estimate(job(), result=got).label() == "Est. ~$175K base"
    assert estimate.estimate(job(), result=levels.PENDING) is None and estimate.estimate(job()) is None


def test_similar_jobs_are_found_by_the_kind_of_work_not_by_company(store):
    me = store.add("Initech", "Platform Engineer", status="queued")
    other = store.add("Globex", "Senior Platform Engineer", status="applied")
    unlike = store.add("Umbrella", "Marketing Manager", status="applied")
    store.set_comp(other.key, base="150-170K")
    store.set_comp(unlike.key, base="90-100K")
    store.set_comp(me.key, base="130K")  # its own row is not "similar"
    assert estimate.similar_bases(store, me) == [(150000, 170000)]


def old_similar_bases(store, job, comps):
    """similar_bases as it was: store.find per comp, which read the whole table for each."""
    from jobwatch.comps import amount
    mine = lca.title_words(job.title)
    out = []
    for key, comp in comps.items():
        if key == job.key or not (base := amount(comp.get("base"))):
            continue
        try:
            other = store.find(key)[0]
        except KeyError:
            continue
        if lca.same_work(mine, lca.title_words(other.title)):
            out.append(base)
    return out


def traced(store):
    """The SQL the store runs, as a list: a full scan for an ending shows as a `LIKE` on the key."""
    seen = []
    store.db.set_trace_callback(seen.append)
    return seen


def scans(seen):
    return [s for s in seen if "key LIKE" in s]


def test_similar_bases_is_the_old_answer_without_a_scan_per_comp(store):
    titles = ["Platform Engineer", "Senior Platform Engineer", "Marketing Manager", "Staff Platform Engineer",
              "Data Engineer", "Senior Data Engineer", "Platform Reliability Engineer"]
    jobs = [store.add(f"Company {i}", t, status="queued" if i % 2 else "applied") for i, t in enumerate(titles * 3)]
    for i, j in enumerate(jobs[:14]):
        store.set_comp(j.key, base=f"{120 + i}-{140 + i}K")
    store.set_comp(jobs[14].key, note="no base here")
    comps = store.comps()
    comps["greenhouse:gone:404"] = {"base": "100-110K"}  # a comp whose job was pruned: no title, no figure
    comps["initech:ghost"] = {"base": "90-95K"}          # and one that names nothing either
    seen = traced(store)
    new = [estimate.similar_bases(store, j, comps) for j in jobs]
    new_scans = len(scans(seen))
    seen.clear()
    old = [old_similar_bases(store, j, comps) for j in jobs]
    assert new == old and any(new)
    # the old reading scanned for every comp of every job; the new one only for the two keys that name no job,
    # once each, not once a job
    assert new_scans == 2 < len(scans(seen))


def test_a_digest_of_jobs_never_scans_the_table_for_a_comp_title(cfg, store):
    jobs = [store.add(f"Company {i}", "Platform Engineer", status="queued") for i in range(40)]
    for j in jobs[:10]:
        store.set_comp(j.key, base="150-170K")
    seen = traced(store)
    comps = store.comps()
    got = [estimate.for_job(cfg, store, j, comps=comps, filings=None, result=None) for j in jobs]
    assert all(g.basis in ("recruiter", "similar") for g in got)
    assert scans(seen) == []
    assert len([s for s in seen if "json_extract(data, '$.title')" in s]) == 1  # the titles: one query for all


def test_find_by_full_key_is_an_index_lookup_and_an_ending_still_works(store):
    j = store.add("Globex", "Platform Engineer", status="queued")
    seen = traced(store)
    assert store.find(j.key)[0].key == j.key
    assert scans(seen) == []
    assert store.find(j.key.split(":")[-1].upper())[0].key == j.key  # an ending, in any case, as before
    assert len(scans(seen)) == 1


def test_for_job_reads_the_store_and_the_job_with_a_posting_has_none(cfg, store):
    me = store.add("Initech", "Platform Engineer", status="queued")
    other = store.add("Globex", "Platform Engineer", status="applied")
    store.set_comp(other.key, base="150-170K")
    got = estimate.for_job(cfg, store, me)
    assert got.basis == "similar" and got.mid == 160000
    store.set_comp(me.key, base="170-190K")
    assert estimate.for_job(cfg, store, me).basis == "recruiter"
    posted = store.add("Hooli", "Data Engineer", status="queued")
    assert estimate.for_job(cfg, store, posted) is None  # no figure anywhere
    text = estimate.render(posted, None)
    assert "no estimate" in text and f"comp {posted.key} --base" in text


def test_render_says_it_is_an_estimate_with_its_basis():
    out = estimate.render(job(), estimate.estimate(job(), filings=filings()))
    assert "Est. $160K–$185K base: an estimate, not an offer or a posted range" in out
    assert "Basis (lca)" in out and "Nothing was saved." in out
    assert "lists its pay" in estimate.render(job(salary_min=150000, salary_max=170000), None)


def test_the_comps_rows_carry_the_estimate_flagged(cfg, store):
    mine = store.add("Initech", "Platform Engineer", status="screening", applied="2026-03-09")
    store.set_comp(mine.key, base="165-195K")
    posted = store.add("Globex", "Data Engineer", status="screening", applied="2026-03-09")
    store.set_comp(posted.key, base="150K")
    rows = {r["key"]: r for r in comps.view(cfg, store)["opportunities"]}
    guess = rows[mine.key]["pay_estimate"]
    assert guess["estimate"] is True and guess["basis"] == "recruiter" and guess["label"] == "Est. $165K–$195K base"
    assert "est. pay: Est. $165K–$195K base (an estimate: " in comps.text(comps.view(cfg, store))
    assert rows[mine.key]["pay_mid"] is None  # the guess never stands in for a posted figure


def test_the_suggestion_never_reads_the_estimate(cfg, store):
    a = store.add("Initech", "Platform Engineer", status="screening", applied="2026-03-09")
    store.set_comp(a.key, role="product")
    before = comps.view(cfg, store)
    assert before["opportunities"][0]["pay_estimate"] is None
    store.set_comp(a.key, note="999K")  # a figure in the note is an estimate source
    after = comps.view(cfg, store)
    assert after["opportunities"][0]["pay_estimate"]["basis"] == "recruiter"
    assert after["suggestion"] == before["suggestion"]  # a guess never moves the ranking


def test_the_queue_and_its_digest_line_show_an_estimate(cfg, store):
    mine = store.add("Initech", "Platform Engineer", status="queued")
    other = store.add("Globex", "Platform Engineer", status="applied")
    store.set_comp(other.key, base="150-170K")
    [entry] = watch.queue(cfg, store)
    assert entry.est.basis == "similar"
    line = "\n".join(report._line(entry))
    assert "Est. $150K–$170K base (an estimate: Bases recruiters gave you for 1 similar job" in line
    assert mine.key in line


def test_the_page_card_has_est_pay_only_for_a_posting_with_no_pay(cfg, store):
    mine = store.add("Initech", "Platform Engineer", status="queued")
    other = store.add("Globex", "Platform Engineer", status="applied")
    store.set_comp(other.key, base="150-170K")
    card = App(cfg.path).get_queue({})[0]
    assert card["key"] == mine.key and card["est_pay"]["estimate"] is True and card["est_pay"]["basis"] == "similar"
    assert not card["pay_sources"][0]["value"]  # Posted says none: the guess is not its figure


def test_the_command_prints_the_estimate_and_saves_nothing(cfg, store, capsys):
    mine = store.add("Initech", "Platform Engineer", status="queued")
    other = store.add("Globex", "Platform Engineer", status="applied")
    store.set_comp(other.key, base="150-170K")
    cli.main(["-c", str(cfg.path), "comp", mine.key, "--estimate"])
    out = capsys.readouterr().out
    assert "an estimate, not an offer or a posted range" in out and "Basis (similar)" in out
    assert store.comp(mine.key) is None
    with pytest.raises(SystemExit, match="--estimate only reads"):
        cli.main(["-c", str(cfg.path), "comp", mine.key, "--estimate", "--base", "130K"])
    assert store.comp(mine.key) is None


def test_the_mcp_tools_flag_it_as_an_estimate(cfg, store, monkeypatch):
    mcp = pytest.importorskip("jobwatch.mcp_server")
    monkeypatch.setenv("JOBWATCH_CONFIG", str(cfg.path))
    mine = store.add("Initech", "Platform Engineer", status="screening", applied="2026-03-09")
    store.set_comp(mine.key, base="165-195K")
    row = mcp.get_comps(keys=[mine.key])["opportunities"][0]
    assert row["pay_estimate"]["estimate"] is True and row["pay_estimate"]["basis"] == "recruiter"
    assert mcp.get_job(mine.key)["pay_estimate"]["estimate"] is True
    assert "estimate" in mcp.get_comps.__doc__ and "estimate" in mcp.get_job.__doc__
